# Derived from mtkresearch/BreezyVoice (MediaTek Research), single_inference.py
# get_bopomofo_rare, commit d592c9d3e8927a0f53f68616387060dcd32a05ea.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE, NOTICE and THIRD_PARTY_NOTICES.md.

"""BreezyVoice text frontend for the owned CosyVoice server process.

BreezyVoice is a CosyVoice-v1 model trained on Taiwanese Mandarin with
auxiliary 注音 hints: a rare character, or one read other than its most
common way, is written as ``字[:ㄓㄨ4]``. g2pW predicts each
reading; BreezyVoice's own frequency tables (``word_utils.py``) decide which
ones to spell out. Text that already carries a ``[:...]`` hint keeps it.

The tables are read with ``ast.literal_eval``: the downloaded file is data and
is never executed. This module imports torch, g2pw and CosyVoice only inside
the functions that need them, so the pure helpers run in any interpreter.
"""
from __future__ import annotations

import ast
import contextlib
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Sequence

MARKER_FILE = "word_utils.py"
G2PW_MODEL_DIR = Path("g2pw") / "G2PWModel"
G2PW_TOKENIZER_DIR = Path("g2pw") / "bert-base-chinese"
RARE_CHAR_FREQUENCY = 500
UNCOMMON_READING_FREQUENCY = 10000
# BreezyVoice decodes speech tokens with plain top-k sampling (k=25).
TOP_K = 25
# g2pW is a BERT-base ONNX model run on the CPU for every fragment.
G2PW_THREADS = int(os.environ.get("BREEZYVOICE_G2PW_THREADS", "") or 6)
# BreezyVoice's cosyvoice.yaml predates the ``sampling`` argument that current
# CosyVoice's TransformerLM requires; this override supplies it.
YAML_OVERRIDES = "llm:\n  sampling: !name:breezyvoice_frontend.top_k_sampling\n"


@dataclass(frozen=True)
class ReadingTables:
    frequency: Counter = field(default_factory=Counter)
    readings: dict = field(default_factory=dict)
    always_annotate: frozenset = frozenset()


def is_breezyvoice_dir(model_dir: str | Path) -> bool:
    directory = Path(model_dir)
    return (directory / "cosyvoice.yaml").is_file() and (directory / MARKER_FILE).is_file()


def load_reading_tables(path: str | Path) -> ReadingTables:
    """Read BreezyVoice's ``word_utils.py`` literals without executing it."""
    tree = ast.parse(Path(path).read_text("utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
                and value.func.id in {"Counter", "defaultdict"} and value.args:
            value = value.args[-1]
            if isinstance(value, ast.Name):
                continue  # ``defaultdict(list, char2phn)`` re-wraps a loaded table
        values[node.targets[0].id] = ast.literal_eval(value)
    missing = {"char2phn", "word_to_dataset_frequency", "always_augment_chars"} - values.keys()
    if missing:
        raise ValueError(f"{path} 缺少 BreezyVoice 讀音表：{', '.join(sorted(missing))}")
    return ReadingTables(
        frequency=Counter(values["word_to_dataset_frequency"]),
        readings=dict(values["char2phn"]),
        always_annotate=frozenset(values["always_augment_chars"]),
    )


def annotate_readings(text: str, readings: Sequence[str | None], tables: ReadingTables) -> str:
    """Spell out the 注音 of rare characters and of uncommon readings.

    ``readings`` holds g2pW's prediction per character of ``text`` (None when
    it has none). Mirrors BreezyVoice's ``get_bopomofo_rare``, except that a
    character without a prediction is never annotated.
    """
    pieces = []
    for index, char in enumerate(text):
        reading = readings[index] if index < len(readings) else None
        following = text[index + 1] if index + 1 < len(text) else None
        frequency = tables.frequency.get(char, 0)
        known = tables.readings.get(char, [])
        annotate = False
        if reading is not None and following != "[":
            if frequency < RARE_CHAR_FREQUENCY:
                annotate = True
            elif len(known) >= 2 and reading != known[0] and (
                    frequency < UNCOMMON_READING_FREQUENCY or char in tables.always_annotate):
                annotate = True
        pieces.append(f"{char}[:{reading}]" if annotate else char)
    return "".join(pieces)


def top_k_sampling(weighted_scores, decoded_tokens, sampling: int = TOP_K):
    """BreezyVoice's speech-token sampler, in current CosyVoice's signature."""
    prob, indices = weighted_scores.softmax(dim=-1).topk(int(sampling or TOP_K))
    return indices[prob.multinomial(1, replacement=True)].item()


def load_breezyvoice_model(model_dir: str | Path, cli=None, load_wav=None):
    """Build current CosyVoice's v1 ``CosyVoice`` from BreezyVoice weights.

    ``cli`` is ``cosyvoice.cli.cosyvoice``; its YAML loader gets
    YAML_OVERRIDES for the duration of the constructor only.
    """
    if cli is None:
        import cosyvoice.cli.cosyvoice as cli
    original = cli.load_hyperpyyaml

    def load_with_overrides(stream, overrides=None, **kwargs):
        return original(stream, overrides=YAML_OVERRIDES, overrides_must_match=False)

    cli.load_hyperpyyaml = load_with_overrides
    try:
        model = cli.CosyVoice(str(model_dir))
    finally:
        cli.load_hyperpyyaml = original
    match_prompt_feature_rate(model, load_wav)
    return model


def match_prompt_feature_rate(model, load_wav=None) -> None:
    """Compute the prompt mel at the model's own rate (22.05 kHz for CosyVoice v1).

    Current CosyVoice's frontend always resamples the prompt to 24 kHz before its
    mel extractor, which for a v1 model shifts the prompt's spectrum (BreezyVoice
    itself resamples to 22.05 kHz). Same steps as CosyVoice's
    ``_extract_speech_feat`` (Apache-2.0, Alibaba), at ``model.sample_rate``.
    """
    frontend = model.frontend
    rate = int(model.sample_rate)
    if load_wav is None:
        from cosyvoice.utils.file_utils import load_wav
    import torch

    def extract_speech_feat(prompt_wav):
        speech = load_wav(prompt_wav, rate)
        feat = frontend.feat_extractor(speech).squeeze(dim=0).transpose(0, 1).to(frontend.device)
        feat = feat.unsqueeze(dim=0)
        return feat, torch.tensor([feat.shape[1]], dtype=torch.int32).to(frontend.device)

    frontend._extract_speech_feat = extract_speech_feat


@contextlib.contextmanager
def cpu_onnx_sessions(module, threads: int = G2PW_THREADS) -> Iterator[None]:
    """g2pw 0.1.1 builds its ONNX session without ``providers``; GPU builds of
    onnxruntime refuse that, so pin the session it creates to the CPU (with
    more than its hard-coded 2 threads: g2pW runs on every fragment)."""
    original = module.onnxruntime.InferenceSession

    def build(path, sess_options=None, **kwargs):
        kwargs.setdefault("providers", ["CPUExecutionProvider"])
        if sess_options is not None:
            sess_options.intra_op_num_threads = threads
        return original(path, sess_options=sess_options, **kwargs)

    module.onnxruntime.InferenceSession = build
    try:
        yield
    finally:
        module.onnxruntime.InferenceSession = original


class BreezyVoiceFrontend:
    """Normalize and annotate text before it reaches the BreezyVoice LLM."""

    def __init__(self, model_dir: str | Path,
                 normalize: Callable[[str], str] | None = None,
                 converter: Callable[[str], list] | None = None):
        directory = Path(model_dir)
        self.tables = load_reading_tables(directory / MARKER_FILE)
        self.normalize = normalize or (lambda text: text)
        self.converter = converter or self._load_g2pw(directory)

    @staticmethod
    def _load_g2pw(directory: Path):
        model = directory / G2PW_MODEL_DIR
        tokenizer = directory / G2PW_TOKENIZER_DIR
        if not (model / "g2pw.onnx").is_file() or not (tokenizer / "vocab.txt").is_file():
            raise FileNotFoundError(
                f"找不到 g2pW 模型或分詞表（{model}、{tokenizer}）；請執行 scripts/breezyvoice_weights.py"
            )
        from g2pw import api

        with cpu_onnx_sessions(api):
            converter = api.G2PWConverter(model_dir=str(model), model_source=str(tokenizer),
                                          style="bopomofo", turnoff_tqdm=True)
        # The archive's config asks for 2 DataLoader workers, which would fork
        # processes for every sentence; 0 cannot be passed (it reads as unset).
        converter.num_workers = 0
        return converter

    def prepare(self, text: str) -> str:
        normalized = self.normalize((text or "").strip())
        if not normalized:
            return normalized
        readings = self.converter(normalized)[0]
        return annotate_readings(normalized, readings, self.tables)
