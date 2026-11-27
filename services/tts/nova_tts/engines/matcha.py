# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""CPU-only Matcha-TTS engine backed by sherpa-onnx.

A role profile names its voice model (聲線模型) by catalog ID in
``tts.ref_file`` (see ``nova_tts.voice_models``); the same voice model speaks
zh-TW and en-US. The thread count is the server-wide ``matcha.num_threads``;
``length_scale`` and ``noise_scale`` are fixed. A loaded voice model is shared
by every engine that uses it, so roles and sessions do not load it again.

A voice model that is not chosen, not listed or not loadable never makes the
engine speak with another voice: like BreezyVoice without its reference
recording, every reply fragment then fails with a message saying what to fix.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from queue import Empty
from typing import Any, Callable

import numpy as np

from nova_tts.base import BaseTTS, State, sanitize_speech_text
from nova_tts.pcm_emitter import TurnPCMEmitter
from nova_tts.voice_models import VoiceModel, list_voice_models
from nova_core.utils.logging import logger

MODEL_TYPE = "matcha-tts"
LENGTH_SCALE = 1.0
NOISE_SCALE = 0.667
# Peak level after synthesis, leaving headroom before the int16 conversion.
PEAK = 0.88
# Fragments synthesised and held ahead of the one being emitted. Synthesis runs
# far faster than real time, so one is enough to hide it behind playback.
MAX_HELD_FRAGMENTS = 1

_ASCII_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_CJK_DUNHAO_RE = re.compile(r"(?<=[一-鿿])\s*、\s*(?=[一-鿿])")
# Taiwanese terms whose word-level simplified form differs from the per-character t2s.
_SIMPLIFIED_LEXICON_REPLACEMENTS = {
    "軟體": "软件",
    "硬體": "硬件",
    "記憶體": "内存",
    "網路": "网络",
    "伺服器": "服务器",
    "資料庫": "数据库",
    "滑鼠": "鼠标",
    "螢幕": "屏幕",
}


class VoiceModelUnavailable(RuntimeError):
    """The profile's voice model cannot be used; the message says how to fix it."""


def resolve_voice_model(model_id: str) -> VoiceModel:
    """The listed voice model ``model_id``; never another one."""
    if not model_id:
        raise VoiceModelUnavailable("Matcha 需要在數位人設定檔的「聲音」選擇聲線模型")
    for model in list_voice_models():
        if model.id == model_id:
            return model
    raise VoiceModelUnavailable(
        f"聲線模型「{model_id[:120]}」不在 models/tts 清單中（目錄不存在、檔案不齊或缺少使用限制標示 "
        "voice.json）；請把聲線模型複製到 models/tts/ 後重新套用，或在數位人設定檔改選聲線模型"
    )


def _model_type(model: VoiceModel) -> str | None:
    """The ``model_type`` metadata of the acoustic model, read with onnxruntime."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    options.log_severity_level = 3
    try:
        session = ort.InferenceSession(
            str(model.acoustic_model), options, providers=["CPUExecutionProvider"]
        )
    except Exception as exc:
        raise VoiceModelUnavailable(
            f"無法讀取聲線模型「{model.id}」的 {model.acoustic_model.name}：{exc}"
        ) from exc
    return session.get_modelmeta().custom_metadata_map.get("model_type")


def load_lexicon_words(lexicon) -> set[str]:
    """Known headwords of a sherpa-onnx Matcha lexicon file."""
    words: set[str] = set()
    with open(lexicon, encoding="utf-8") as handle:
        for raw_line in handle:
            parts = raw_line.strip().split(maxsplit=1)
            if parts:
                words.add(parts[0])
    return words


@dataclass
class _LoadedVoice:
    tts: Any  # sherpa_onnx.OfflineTts
    lexicon_words: set[str]
    # sherpa-onnx's OfflineTts is shared, so its synthesis runs one text at a time.
    lock: threading.Lock


_loaded: dict[tuple[VoiceModel, int], _LoadedVoice] = {}
_loading = threading.Lock()


def load_voice_model(model: VoiceModel, num_threads: int) -> _LoadedVoice:
    """The loaded voice model, loading it on first use."""
    key = (model, num_threads)
    with _loading:
        if key not in _loaded:
            _loaded[key] = _load(model, num_threads)
        return _loaded[key]


def _load(model: VoiceModel, num_threads: int) -> _LoadedVoice:
    model_type = _model_type(model)
    if model_type != MODEL_TYPE:
        raise VoiceModelUnavailable(
            f"聲線模型「{model.id}」不是 Matcha-TTS 模型（model_type={model_type!r}）"
        )
    import sherpa_onnx

    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=str(model.acoustic_model),
                vocoder=str(model.vocoder),
                lexicon=str(model.lexicon),
                tokens=str(model.tokens),
                noise_scale=NOISE_SCALE,
                length_scale=LENGTH_SCALE,
            ),
            num_threads=num_threads,
            provider="cpu",
            debug=False,
        ),
        rule_fsts=",".join(str(path) for path in model.rule_fsts),
        max_num_sentences=1,
    )
    # sherpa-onnx ends the process on an invalid configuration; check it first.
    if not config.validate():
        raise VoiceModelUnavailable(f"聲線模型「{model.id}」的檔案無法由 sherpa-onnx 載入")
    started_at = time.perf_counter()
    tts = sherpa_onnx.OfflineTts(config)
    logger.info("Matcha 聲線模型 %s 已載入（%d 執行緒，%.2fs）",
                model.id, num_threads, time.perf_counter() - started_at)
    return _LoadedVoice(tts, load_lexicon_words(model.lexicon), threading.Lock())


def _build_t2s_converter():
    from opencc import OpenCC

    return OpenCC("t2s")


def _expand_ascii_word(word: str, lexicon_words: set[str] | None) -> str:
    if not lexicon_words:
        return word
    lower = word.lower()
    if lower in lexicon_words:
        return lower
    parts = [piece for piece in _CAMEL_BOUNDARY_RE.split(word) if piece]
    if len(parts) > 1:
        return " ".join(_expand_ascii_word(piece, lexicon_words) for piece in parts)
    # Spell out unknown acronyms letter by letter.
    if word.isupper() and len(word) >= 2 and all(ch in lexicon_words for ch in lower):
        return " ".join(lower)
    return lower


def normalize_matcha_text(text: str, *, lexicon_words: set[str] | None = None, converter=None) -> str:
    """Traditional Chinese and bilingual English text as the Matcha lexicon spells it."""
    cleaned = sanitize_speech_text(text)
    if not cleaned:
        return ""
    for src, dst in _SIMPLIFIED_LEXICON_REPLACEMENTS.items():
        cleaned = cleaned.replace(src, dst)
    if converter is not None:
        cleaned = converter.convert(cleaned)
    # Remove enumeration dunhao between Chinese characters so sherpa-onnx does
    # not split phrases like "準確、有用" into isolated clauses.
    cleaned = _CJK_DUNHAO_RE.sub("", cleaned)
    if lexicon_words:
        cleaned = _ASCII_WORD_RE.sub(lambda match: _expand_ascii_word(match.group(0), lexicon_words), cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def generate_speech(
    voice: _LoadedVoice,
    text: str,
    *,
    converter=None,
    keep_going: Callable[[], bool] | None = None,
    default_rate: int = 16000,
) -> tuple[np.ndarray, int]:
    """Speak ``text`` with a loaded voice model: float samples at the model's own rate.

    Synthesis holds the voice model's lock, so the live engine and any other caller
    of the same loaded model take turns. ``keep_going`` is polled while generating;
    returning False stops it early (the samples so far are returned). Blocking CPU
    work: async callers use ``asyncio.to_thread``. Text that normalises to nothing
    gives no samples.
    """
    normalized = normalize_matcha_text(text, lexicon_words=voice.lexicon_words, converter=converter)
    if not normalized:
        return np.empty(0, dtype=np.float32), default_rate
    with voice.lock:
        generated = voice.tts.generate(
            normalized,
            sid=0,
            speed=1.0,
            callback=lambda _samples, _progress: 1 if keep_going is None or keep_going() else 0,
        )
    samples = np.asarray(generated.samples, dtype=np.float32).reshape(-1)
    return samples, int(getattr(generated, "sample_rate", default_rate) or default_rate)


def limit_peak(samples: np.ndarray) -> np.ndarray:
    """``samples`` scaled down, if needed, to ``PEAK`` so the int16 conversion keeps headroom."""
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > PEAK:
        return (samples * (PEAK / peak)).astype(np.float32, copy=False)
    return samples


@dataclass
class _HeldFragment:
    """A synthesised fragment waiting for its turn to be emitted."""

    msg: tuple[str, dict]
    samples: np.ndarray | None
    error: Exception | None = None


class MatchaTTS(BaseTTS):
    """Speaks with the role profile's voice model, CPU-only via sherpa-onnx.

    While fragment N is emitted and plays, a synthesis thread already turns
    fragment N+1 into PCM and holds it (at most ``MAX_HELD_FRAGMENTS``), so the
    next fragment follows without waiting for synthesis. ``flush_talk`` bumps an
    epoch under the same lock that guards the held fragments and the queue
    reads: held and in-flight fragments of an older epoch are dropped, never
    emitted.
    """

    LOG_NAME = "matcha"

    def __init__(self, config, parent):
        super().__init__(config, parent)
        self.voice_model_id = str(getattr(config.tts, "ref_file", "") or "").strip()
        self._voice: _LoadedVoice | None = None
        self._problem = ""
        try:
            model = resolve_voice_model(self.voice_model_id)
            self._voice = load_voice_model(model, config.matcha.num_threads)
        except VoiceModelUnavailable as exc:
            self._problem = str(exc)
            logger.error("Matcha TTS 無法使用：%s", exc)
        except Exception as exc:
            self._problem = f"聲線模型「{self.voice_model_id}」載入失敗：{exc}"
            logger.exception("Matcha TTS 無法使用")
        self._converter = _build_t2s_converter()
        # Guards the held fragments, the epoch and the synthesis thread's queue reads.
        self._cv = threading.Condition()
        self._held: deque[_HeldFragment] = deque()
        self._epoch = 0
        self._synthesizing = False

    def _synthesize(
        self,
        voice: _LoadedVoice,
        text: str,
        alive: Callable[[], bool] | None = None,
    ) -> np.ndarray:
        samples, rate = generate_speech(
            voice,
            text,
            converter=self._converter,
            # Stop generating once the turn is interrupted.
            keep_going=lambda: self.state == State.RUNNING and (alive is None or alive()),
            default_rate=self.sample_rate,
        )
        if samples.size and rate != self.sample_rate:
            import resampy

            samples = resampy.resample(samples, rate, self.sample_rate).astype(np.float32, copy=False)
        return limit_peak(samples)

    def txt_to_audio(self, msg: tuple[str, dict]) -> None:
        """Synthesize and emit one fragment now (no prefetch); raises when it fails."""
        text, textevent = msg
        try:
            if self._voice is None:
                raise VoiceModelUnavailable(self._problem)
            started_at = time.perf_counter()
            samples = self._synthesize(self._voice, text)
            self._emit_samples(text, textevent, samples, started_at)
        except Exception:
            logger.exception(self.LOG_NAME)
            self.notify_fragment_synthesis_failed(textevent, "tts_exhausted_before_audio")
            raise

    # -- prefetch: one synthesis thread feeds the emitting thread ---------------------

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None:
        super().put_msg_txt(msg, datainfo)
        with self._cv:
            self._cv.notify_all()

    def flush_talk(self) -> None:
        """Drop queued text, held fragments and the in-flight synthesis of the old turn."""
        with self._cv:
            super().flush_talk()
            self._epoch += 1
            self._held.clear()
            self._cv.notify_all()

    def has_pending_work(self) -> bool:
        with self._cv:
            return super().has_pending_work() or self._synthesizing or bool(self._held)

    def process_tts(self, quit_event) -> None:
        synthesis = threading.Thread(
            target=self._synthesis_loop, args=(quit_event,), name="matcha-synthesis", daemon=True
        )
        synthesis.start()
        try:
            self._emission_loop(quit_event)
        finally:
            self.state = State.PAUSE
            with self._cv:
                self._held.clear()
                self._cv.notify_all()
            synthesis.join(timeout=5)
            logger.info("ttsreal thread stop")

    def _synthesis_loop(self, quit_event) -> None:
        """Turn queued text into held fragments, at most ``MAX_HELD_FRAGMENTS`` ahead."""
        while not quit_event.is_set():
            with self._cv:
                msg = None
                if len(self._held) < MAX_HELD_FRAGMENTS:
                    # Read the queue under the lock flush_talk holds, so a message
                    # can never be paired with the epoch of the turn after it.
                    try:
                        msg = self.msgqueue.get_nowait()
                    except Empty:
                        msg = None
                if msg is None:
                    self._cv.wait(0.1)
                    continue
                epoch = self._epoch
                self.state = State.RUNNING
                self._synthesizing = True
            held = self._synthesize_held(msg, lambda: self._epoch == epoch)
            with self._cv:
                self._synthesizing = False
                if epoch == self._epoch:
                    self._held.append(held)
                self._cv.notify_all()

    def _synthesize_held(self, msg: tuple[str, dict], alive: Callable[[], bool]) -> _HeldFragment:
        text, _ = msg
        try:
            if self._voice is None:
                raise VoiceModelUnavailable(self._problem)
            return _HeldFragment(msg, self._synthesize(self._voice, text, alive))
        except Exception as exc:
            logger.exception(self.LOG_NAME)
            # Reported when the fragment's turn in the order comes up, not now:
            # the fragment before it may still be playing.
            return _HeldFragment(msg, None, exc)

    def _emission_loop(self, quit_event) -> None:
        while not quit_event.is_set():
            with self._cv:
                if not self._held:
                    self._cv.wait(0.1)
                    continue
                held = self._held.popleft()
                epoch = self._epoch
                self._synthesis_active.set()
                self._cv.notify_all()
            text, textevent = held.msg
            if held.error is not None:
                self.notify_fragment_synthesis_failed(textevent, "tts_exhausted_before_audio")
            else:
                try:
                    self._emit_samples(text, textevent, held.samples, time.perf_counter(), epoch)
                except Exception:
                    logger.exception(self.LOG_NAME)
                    self.notify_fragment_synthesis_failed(textevent, "tts_exhausted_before_audio")
            self._settle(textevent, epoch, quit_event)

    def _settle(self, eventpoint: dict, epoch: int, quit_event) -> None:
        """Wait for the emitted fragment to finish playing, unless another is ready.

        A held fragment is emitted at once: the bounded playback queue paces it,
        so it follows the current one without a gap. ``_synthesis_active`` stays
        set until nothing is left to say.
        """
        while not quit_event.is_set():
            with self._cv:
                if self._epoch != epoch:
                    break
                if self._held:
                    return
                idle = not self._synthesizing and self.msgqueue.empty()
            if idle and self._playback_ended(eventpoint):
                break
            time.sleep(0.01)
        self._synthesis_active.clear()

    def _playback_ended(self, eventpoint: dict) -> bool:
        if not eventpoint.get("turn_id"):
            return True
        ended = getattr(self.parent, "fragment_playback_ended", None)
        return bool(ended(eventpoint)) if callable(ended) else True

    def _turn_accepted(self, textevent: dict) -> bool:
        """Whether the fragment's turn is still the live one (ADR 0007 fence)."""
        accepts = getattr(self.parent, "accepts_media", None)
        if not callable(accepts) or not textevent.get("turn_id"):
            return True
        return bool(accepts(textevent, "tts_held_fragment"))

    def _emit_samples(
        self,
        text: str,
        textevent: dict,
        samples: np.ndarray | None,
        started_at: float,
        epoch: int | None = None,
    ) -> None:
        """Emit synthesized PCM as 20 ms frames; nothing of an older epoch or turn is played."""

        def current() -> bool:
            return (
                self.state == State.RUNNING
                and (epoch is None or self._epoch == epoch)
                and self._turn_accepted(textevent)
            )

        if not current():
            return
        if samples is None or not samples.size:
            self.notify_fragment_synthesis_failed(textevent, "tts_empty_audio")
            return
        emitter = TurnPCMEmitter(self, text, textevent, chunk_guard=lambda _sequence: current())
        logged = False

        def note_first_audio() -> None:
            nonlocal logged
            if not logged and emitter.emitted:
                logged = True
                logger.info("%s first audio:%.4fs", self.LOG_NAME, time.perf_counter() - started_at)

        slice_size = max(self.chunk * 4, 1280)
        for offset in range(0, samples.size, slice_size):
            if not current() or emitter.cancelled:
                return
            emitter.feed_pcm(samples[offset : offset + slice_size])
            note_first_audio()
        if current() and not emitter.cancelled:
            emitter.finish_pcm()
            note_first_audio()
