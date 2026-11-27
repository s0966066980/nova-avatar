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
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from nova_contracts.tts import strip_visual_markup
from nova_tts.base import State
from nova_tts.engines.prefetching import PrefetchingTTS
from nova_tts.voice_models import VoiceModel, list_voice_models
from nova_core.utils.logging import logger

MODEL_TYPE = "matcha-tts"
LENGTH_SCALE = 1.0
NOISE_SCALE = 0.667
# Peak level after synthesis, leaving headroom before the int16 conversion.
PEAK = 0.88

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
    cleaned = strip_visual_markup(text)
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


class MatchaTTS(PrefetchingTTS):
    """Speaks with the role profile's voice model, CPU-only via sherpa-onnx.

    The next fragment is synthesised while the current one plays, and a flush
    drops it (see ``PrefetchingTTS``).
    """

    LOG_NAME = "matcha"

    def __init__(self, config, sink):
        super().__init__(config, sink)
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

    def _synthesize_fragment(
        self, text: str, textevent: dict, alive: Callable[[], bool] | None = None
    ) -> np.ndarray:
        if self._voice is None:
            raise VoiceModelUnavailable(self._problem)
        return self._synthesize(self._voice, text, alive)
