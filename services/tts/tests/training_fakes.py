# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Training test rig and fake child processes: no real subprocess, model or GPU."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from nova_tts.training.jobs import (
    TrainingJobManager,
    TrainingParams,
    TrainingPaths,
    TrainingSettings,
)
from nova_tts.training import edge_teacher
from nova_tts.training.corpus import REVIEW_CONFIRMED, CorpusStore
from nova_tts.training.gpu_probe import VramReading
from nova_tts.training.usage import SOURCE_SELF_RECORDED
from nova_tts.voice_models import REQUIRED_FILES


class FakeProcess:
    """A scripted child process.

    ``lines`` is what it prints; ``returncode`` is its exit code once the lines are
    out (``None`` keeps it running until it is signalled). ``ignore_term`` makes it
    survive SIGTERM so that the kill escalation can be observed. ``on_line`` receives
    each line written to its standard input and may return reply lines. ``pid`` is what a
    tracked spawn records in the job state.
    """

    def __init__(
        self,
        lines: Sequence[str] = (),
        returncode: int | None = 0,
        *,
        ignore_term: bool = False,
        on_line: Callable[[str], Sequence[str]] | None = None,
        release: threading.Event | None = None,
        pid: int | None = None,
    ) -> None:
        self.pid = pid
        self.signals: list[str] = []
        self.written: list[str] = []
        self._ignore_term = ignore_term
        self._on_line = on_line
        self._out: queue.Queue[str | None] = queue.Queue()
        self._exited = threading.Event()
        self._code = returncode
        self.returncode: int | None = None
        for line in lines:
            self._out.put(line + "\n")
        if returncode is not None and release is None:
            self._finish(returncode)
        elif returncode is not None and release is not None:
            threading.Thread(target=self._finish_when, args=(release, returncode), daemon=True).start()

    def _finish_when(self, release: threading.Event, code: int) -> None:
        release.wait(30)
        self._finish(code)

    def _finish(self, code: int) -> None:
        if self._exited.is_set():
            return
        self.returncode = code
        self._exited.set()
        self._out.put(None)

    def readline(self) -> str:
        item = self._out.get()
        if item is None:
            self._out.put(None)
            return ""
        return item

    def write_line(self, text: str) -> None:
        self.written.append(text)
        if self._on_line is not None:
            for reply in self._on_line(text):
                self._out.put(reply + "\n")

    def terminate(self) -> None:
        self.signals.append("TERM")
        if not self._ignore_term:
            self._finish(-15)

    def kill(self) -> None:
        self.signals.append("KILL")
        self._finish(-9)

    def wait(self, timeout: float | None = None) -> int:
        if not self._exited.wait(timeout):
            raise subprocess.TimeoutExpired("fake", timeout or 0)
        assert self.returncode is not None
        return self.returncode


class FakeSpawner:
    """A ``Spawn`` that records every command and returns the process a handler builds.

    ``handler(command, env, cwd)`` returns the ``FakeProcess``; it may also create
    files (a training script writes checkpoints), as the real child would.
    """

    def __init__(self, handler: Callable[[Sequence[str], Mapping[str, str], Path], FakeProcess]) -> None:
        self.handler = handler
        self.commands: list[list[str]] = []
        self.envs: list[Mapping[str, str]] = []
        self.cwds: list[Path] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, command: Sequence[str], env: Mapping[str, str], cwd: Path) -> FakeProcess:
        self.commands.append(list(command))
        self.envs.append(dict(env))
        self.cwds.append(cwd)
        process = self.handler(command, env, cwd)
        self.processes.append(process)
        return process


def argument(command: Sequence[str], flag: str) -> str:
    """The value that follows ``flag`` in ``command``."""
    return command[list(command).index(flag) + 1]


def tone_wav(seconds: float = 1.5, rate: int = 16000, amplitude: float = 0.3) -> bytes:
    """A WAV of silence, a 220 Hz tone and silence: it passes the audio quality check."""
    import io

    import numpy as np
    import soundfile as sf

    t = np.arange(int(rate * seconds)) / rate
    body = amplitude * np.sin(2 * np.pi * 220 * t)
    mono = np.concatenate([np.zeros(int(rate * 0.3)), body, np.zeros(int(rate * 0.3))]).astype("float32")
    buffer = io.BytesIO()
    sf.write(buffer, mono, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


TOOLS = Path(__file__).resolve().parents[3] / "tools" / "tts-distill"


TOKENS = {" ": 1, ",": 4, "wo3": 11, "you3": 12, "san1": 13, "ge4": 14, "ping2": 15, "guo3": 16,
          "er4": 17, "ling2": 18, "liu4": 19, "nian2": 20, "dian4": 21, "hua4": 22}


LEXICON = ["我 wo3", "有 you3", "三 san1", "个 ge4", "苹果 ping2 guo3", "二 er4", "零 ling2", "六 liu4",
           "年 nian2", "电话 dian4 hua4"]


TEXTS = ["我有三個蘋果", "二零二六年", "我有電話"]


ENOUGH_VRAM_MIB = 9830


@dataclass
class Rig:
    manager: TrainingJobManager
    store: CorpusStore
    paths: TrainingPaths
    spawner: FakeSpawner
    state: dict
    trained: list[list[dict]]


def make_paths(tmp_path: Path, *, with_env: bool = True) -> TrainingPaths:
    root = tmp_path / "project"
    base = root / "models" / "tts" / "matcha-icefall-zh-en"
    base.mkdir(parents=True)
    (base / "tokens.txt").write_text("".join(f"{t} {i}\n" for t, i in TOKENS.items()), encoding="utf-8")
    (base / "lexicon.txt").write_text("\n".join(LEXICON) + "\n", encoding="utf-8")
    (base / "vocos-16khz-univ.onnx").write_bytes(b"vocoder")
    (base / "number-zh.fst").write_bytes(b"fst")
    python = root / ".local" / "matcha-train" / "venv" / "bin" / "python"
    checkpoint = root / ".local" / "matcha-base" / "pytorch_model_sherpa.bin"
    if with_env:
        for path in (python, checkpoint):
            path.parent.mkdir(parents=True)
            path.write_bytes(b"x")
    return TrainingPaths(root, python, checkpoint, base, TOOLS, tmp_path / "voices")


def make_store(tmp_path: Path, source: str = SOURCE_SELF_RECORDED, texts=TEXTS) -> CorpusStore:
    store = CorpusStore(tmp_path / "corpora")
    store.create("voice", source)
    for text in texts:
        line = store.add_line("voice", tone_wav(), ".wav", text)
        store.set_review("voice", line.id, REVIEW_CONFIRMED)
    return store


def rig(
    tmp_path: Path,
    *,
    source: str = SOURCE_SELF_RECORDED,
    texts=TEXTS,
    with_env: bool = True,
    train_lines=("epoch=1 step=1/4 loss=6.9 ema=6.9", "epoch=1 step=4/4 loss=5.5 ema=5.6"),
    train_code: int | None = 0,
    train_ignores_term: bool = False,
    export_code: int = 0,
    transcript: dict[str, str] | None = None,
    transcriber_error: Exception | None = None,
    verify_error: Exception | None = None,
    vram: VramReading = VramReading(ENOUGH_VRAM_MIB),
    settings: TrainingSettings = TrainingSettings(),
    synthesize=None,
    train_release: threading.Event | None = None,
    whisper_process: FakeProcess | None = None,
) -> Rig:
    store = make_store(tmp_path, source, texts)
    paths = make_paths(tmp_path, with_env=with_env)
    trained: list[list[dict]] = []
    state: dict = {"transcriber_models": [], "verified": [], "orphans": [], "synth_calls": [], "transcribing": False}

    def handler(command, env, cwd):
        if list(command[1:3]) == ["-m", "nova_tts.training.whisper_worker"]:
            assert whisper_process is not None
            return whisper_process
        script = Path(command[1]).name
        if script == "train_matcha.py":
            manifest = Path(argument(command, "--manifest"))
            trained.append([json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()])
            out = Path(argument(command, "--out-dir"))
            out.mkdir(parents=True, exist_ok=True)
            (out / "best.pt").write_bytes(b"weights")
            return FakeProcess(train_lines, train_code, ignore_term=train_ignores_term, release=train_release)
        if script == "export_matcha_onnx.py":
            out = Path(argument(command, "--output-dir"))
            out.mkdir(parents=True, exist_ok=True)
            for name in (*REQUIRED_FILES, "number-zh.fst"):
                (out / name).write_bytes(name.encode())
            state["export_command"] = list(command)
            return FakeProcess(["Exported Matcha ONNX bundle"], export_code)
        raise AssertionError(f"unexpected child: {command}")

    spawner = FakeSpawner(handler)

    @contextmanager
    def transcriber(model: str):
        state["transcriber_models"].append(model)
        if transcriber_error is not None:
            raise transcriber_error
        by_id = {line.id: line.text for line in store.get("voice").lines}
        heard = transcript or {}

        def transcribe(path: Path) -> str:
            line_id = path.stem
            return heard.get(line_id, by_id[line_id])

        yield transcribe

    def verify(bundle: Path, cancel: threading.Event) -> None:
        state["verified"].append(sorted(p.name for p in bundle.iterdir()))
        if verify_error is not None:
            raise verify_error

    def default_synthesize(store_, slug, sentences, **kwargs):
        state["synth_calls"].append({"slug": slug, "sentences": list(sentences), **kwargs})
        return edge_teacher.SynthesisReport(len(sentences), 0, 0, 0, 0, len(sentences), False, False, ())

    manager = TrainingJobManager(
        store=store,
        paths=paths,
        settings=lambda: settings,
        params=TrainingParams(batch_size=2, epochs=1, num_workers=0, vram_sample_seconds=0),
        vram_probe=lambda: vram,
        spawn=spawner,
        synthesize=synthesize or default_synthesize,
        transcriber_factory=None if whisper_process is not None else transcriber,
        verify_bundle=verify,
        orphan_stopper=lambda pid: state["orphans"].append(pid) or True,
        transcription_active=lambda: state["transcribing"],
    )
    return Rig(manager, store, paths, spawner, state, trained)


def edge_synthesis(texts=TEXTS):
    def synthesize(store, slug, sentences, **kwargs):
        for text in texts:
            line = store.add_line(slug, tone_wav(), ".wav", text)
            store.set_review(slug, line.id, REVIEW_CONFIRMED)
        kwargs["on_progress"](edge_teacher.Progress(1, 1, "x", edge_teacher.STATUS_STORED))
        return edge_teacher.SynthesisReport(len(sentences), len(texts), 0, 0, 0, 0, False, False, ())

    return synthesize
