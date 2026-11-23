# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""CPU-only Matcha-TTS ONNX engine backed by sherpa-onnx."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from src.server.reply_streaming.channel import PlayableFragment
from src.tts.base import BaseTTS, State, sanitize_speech_text
from src.tts.pcm_emitter import TurnPCMEmitter
from src.utils.logging import logger

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MODEL_ROOTS = (
    "models/tts",
    ".local/tts-models",
)
_FALLBACK_ZH_EN_DIR = "models/tts/matcha-icefall-zh-en"
_FST_NAMES = ("phone-zh.fst", "date-zh.fst", "number-zh.fst")
_ASCII_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_CJK_DUNHAO_RE = re.compile(r"(?<=[\u4e00-\u9fff])\s*、\s*(?=[\u4e00-\u9fff])")
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


@dataclass(frozen=True)
class MatchaModelPaths:
    """Resolved file paths required to load one Matcha-TTS ONNX bundle."""

    model_dir: Path
    acoustic_model: Path
    vocoder: Path
    lexicon: Path
    tokens: Path
    rule_fsts: tuple[Path, ...] = ()

    @property
    def display_id(self) -> str:
        return self.model_dir.name


def _resolve_candidate_path(raw: str, repo_root: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _pick_acoustic_model(model_dir: Path) -> Optional[Path]:
    for name in ("model.onnx", "model-steps-3.onnx"):
        candidate = model_dir / name
        if candidate.is_file():
            return candidate
    onnx_files = sorted(
        p for p in model_dir.glob("*.onnx") if "vocos" not in p.name.lower()
    )
    return onnx_files[0] if onnx_files else None


def _pick_vocoder(model_dir: Path, repo_root: Path) -> Optional[Path]:
    for pattern in ("vocos-16khz-univ.onnx", "vocos*.onnx"):
        matches = sorted(model_dir.glob(pattern))
        if matches and matches[0].is_file():
            return matches[0]
    fallback = repo_root / _FALLBACK_ZH_EN_DIR / "vocos-16khz-univ.onnx"
    return fallback if fallback.is_file() else None


def _pick_lexicon(model_dir: Path) -> Optional[Path]:
    for name in ("lexicon.txt", "lexicon_zh_en.txt"):
        candidate = model_dir / name
        if candidate.is_file():
            return candidate
    return None


def _collect_rule_fsts(model_dir: Path, repo_root: Path) -> tuple[Path, ...]:
    fsts: list[Path] = []
    fallback_dir = repo_root / _FALLBACK_ZH_EN_DIR
    for name in _FST_NAMES:
        local = model_dir / name
        if local.is_file():
            fsts.append(local)
        elif fallback_dir != model_dir and (fallback_dir / name).is_file():
            fsts.append(fallback_dir / name)
    return tuple(fsts)


def _read_onnx_model_type(onnx_path: Path) -> Optional[str]:
    try:
        import onnx

        model = onnx.load(str(onnx_path), load_external_data=False)
    except Exception:
        return None
    for prop in getattr(model, "metadata_props", ()):
        if getattr(prop, "key", "") == "model_type":
            return str(prop.value or "").strip().lower() or None
    return None


def _bundle_incompatibility_reason(model_dir: Path, acoustic: Path) -> Optional[str]:
    if (model_dir / "voices.bin").is_file():
        return f"{model_dir.name} 是 Kokoro 模型（含 voices.bin），不支援以 Matcha-TTS 載入"
    model_type = _read_onnx_model_type(acoustic)
    if model_type is not None and model_type != "matcha-tts":
        return f"{model_dir.name} 的 ONNX model_type={model_type!r}，僅支援 'matcha-tts'"
    has_local_vocoder = any(model_dir.glob("vocos*.onnx"))
    if not has_local_vocoder and model_type != "matcha-tts":
        return f"{model_dir.name} 缺少 vocos*.onnx 且未標記為 matcha-tts"
    return None


def _paths_from_dir(model_dir: Path, repo_root: Path) -> Optional[MatchaModelPaths]:
    if not model_dir.is_dir():
        return None
    acoustic = _pick_acoustic_model(model_dir)
    if acoustic is None or _bundle_incompatibility_reason(model_dir, acoustic) is not None:
        return None
    vocoder = _pick_vocoder(model_dir, repo_root)
    lexicon = _pick_lexicon(model_dir)
    tokens = model_dir / "tokens.txt"
    if not (vocoder and lexicon and tokens.is_file()):
        return None
    return MatchaModelPaths(
        model_dir=model_dir,
        acoustic_model=acoustic,
        vocoder=vocoder,
        lexicon=lexicon,
        tokens=tokens,
        rule_fsts=_collect_rule_fsts(model_dir, repo_root),
    )


def discover_matcha_models(repo_root: Path | None = None) -> list[MatchaModelPaths]:
    """Return valid local Matcha-TTS ONNX bundles ordered with trained models first."""
    root = _REPO_ROOT if repo_root is None else Path(repo_root)
    discovered: list[MatchaModelPaths] = []
    seen_dirs: set[Path] = set()
    for rel_root in _DEFAULT_MODEL_ROOTS:
        parent = root / rel_root
        if not parent.is_dir():
            continue
        direct = _paths_from_dir(parent, root)
        if direct is not None and direct.model_dir not in seen_dirs:
            seen_dirs.add(direct.model_dir)
            discovered.append(direct)
        for child in sorted(parent.iterdir()):
            if not child.is_dir():
                continue
            resolved = _paths_from_dir(child, root)
            if resolved is not None and resolved.model_dir not in seen_dirs:
                seen_dirs.add(resolved.model_dir)
                discovered.append(resolved)
    return discovered


def resolve_matcha_model_paths(
    model_spec: str = "",
    *,
    repo_root: Path | None = None,
) -> MatchaModelPaths:
    """Resolve explicit or default local Matcha-TTS ONNX assets."""
    root = _REPO_ROOT if repo_root is None else Path(repo_root)
    spec = str(model_spec or "").strip()
    if spec:
        candidate = _resolve_candidate_path(spec, root)
        if candidate.is_file() and candidate.suffix.lower() == ".onnx":
            model_dir = candidate.parent
            reason = _bundle_incompatibility_reason(model_dir, candidate)
            if reason is not None:
                raise FileNotFoundError(reason)
            vocoder = _pick_vocoder(model_dir, root)
            lexicon = _pick_lexicon(model_dir)
            tokens = model_dir / "tokens.txt"
            if vocoder and lexicon and tokens.is_file():
                return MatchaModelPaths(
                    model_dir=model_dir,
                    acoustic_model=candidate,
                    vocoder=vocoder,
                    lexicon=lexicon,
                    tokens=tokens,
                    rule_fsts=_collect_rule_fsts(model_dir, root),
                )
        elif candidate.is_dir():
            resolved = _paths_from_dir(candidate, root)
            if resolved is not None:
                return resolved
            acoustic = _pick_acoustic_model(candidate)
            if acoustic is not None:
                reason = _bundle_incompatibility_reason(candidate, acoustic)
                if reason is not None:
                    raise FileNotFoundError(reason)
        raise FileNotFoundError(f"Matcha TTS model assets not found at: {spec}")

    discovered = discover_matcha_models(root)
    if discovered:
        return discovered[0]
    raise FileNotFoundError(
        "No local Matcha TTS model found under models/tts or .local/tts-models"
    )


def load_lexicon_words(lexicon_path: Path) -> set[str]:
    """Read known headwords from a sherpa-onnx Matcha lexicon file."""
    words: set[str] = set()
    with lexicon_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            parts = raw_line.strip().split(maxsplit=1)
            if parts:
                words.add(parts[0])
    return words


def _build_t2s_converter():
    try:
        from opencc import OpenCC
    except ImportError:
        return None
    return OpenCC("t2s")


def _expand_ascii_word(word: str, lexicon_words: Optional[set[str]]) -> str:
    if not lexicon_words:
        return word
    lower = word.lower()
    if lower in lexicon_words:
        return lower
    parts = [piece for piece in _CAMEL_BOUNDARY_RE.split(word) if piece]
    if len(parts) > 1:
        expanded = [_expand_ascii_word(piece, lexicon_words) for piece in parts]
        return " ".join(expanded)
    if (word.isupper() or "'" not in word) and all(
        ch.lower() in lexicon_words for ch in lower
    ):
        if word.isupper() and len(word) >= 2:
            return " ".join(lower)
    return lower


def normalize_matcha_text(
    text: str,
    *,
    lexicon_words: Optional[set[str]] = None,
    converter=None,
) -> str:
    """Normalize Traditional Chinese and bilingual English tokens for Matcha-TTS."""
    cleaned = sanitize_speech_text(text)
    if not cleaned:
        return ""
    for src, dst in _SIMPLIFIED_LEXICON_REPLACEMENTS.items():
        if src in cleaned:
            cleaned = cleaned.replace(src, dst)
    if converter is not None:
        cleaned = converter.convert(cleaned)
    # Remove enumeration dunhao between Chinese characters so sherpa-onnx does
    # not split phrases like "準確、有用" into isolated 5-char clauses.
    cleaned = _CJK_DUNHAO_RE.sub("", cleaned)
    if lexicon_words:
        cleaned = _ASCII_WORD_RE.sub(
            lambda match: _expand_ascii_word(match.group(0), lexicon_words),
            cleaned,
        )
    return re.sub(r"\s+", " ", cleaned).strip()


class MatchaTTS(BaseTTS):
    """Offline Matcha-TTS engine running CPU-only ONNX inference via sherpa-onnx."""

    def __init__(self, config, parent):
        super().__init__(config, parent)
        tts_cfg = getattr(config, "tts", None)
        model_spec = str(getattr(tts_cfg, "model", "") or "").strip()
        if not model_spec:
            ref = str(getattr(tts_cfg, "ref_file", "") or "").strip()
            if ref and ("/" in ref or "\\" in ref or Path(ref).exists()):
                model_spec = ref
        self.num_threads = max(1, int(getattr(tts_cfg, "num_threads", 4) or 4))
        self.length_scale = float(getattr(tts_cfg, "length_scale", 1.0) or 1.0)
        self.noise_scale = float(getattr(tts_cfg, "noise_scale", 0.667) or 0.667)
        self.model_paths = resolve_matcha_model_paths(model_spec)
        self._lexicon_words = load_lexicon_words(self.model_paths.lexicon)
        self._converter = _build_t2s_converter()
        self._synth_lock = threading.Lock()
        self._tts = self._create_offline_tts()
        logger.info(
            "MatchaTTS initialized model=%s threads=%d length_scale=%.2f",
            self.model_paths.model_dir,
            self.num_threads,
            self.length_scale,
        )

    def _create_offline_tts(self):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "MatchaTTS requires sherpa-onnx>=2.0. Install with: "
                'uv pip install -e ".[matcha]"'
            ) from exc

        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                    acoustic_model=str(self.model_paths.acoustic_model),
                    vocoder=str(self.model_paths.vocoder),
                    lexicon=str(self.model_paths.lexicon),
                    tokens=str(self.model_paths.tokens),
                    noise_scale=self.noise_scale,
                    length_scale=self.length_scale,
                ),
                num_threads=self.num_threads,
                provider="cpu",
                debug=False,
            ),
            rule_fsts=",".join(str(p) for p in self.model_paths.rule_fsts),
            max_num_sentences=1,
        )
        return sherpa_onnx.OfflineTts(tts_config)

    def _synthesize_samples(self, text: str) -> tuple[np.ndarray, int]:
        normalized = normalize_matcha_text(
            text,
            lexicon_words=self._lexicon_words,
            converter=self._converter,
        )
        if not normalized:
            return np.empty(0, dtype=np.float32), self.sample_rate
        with self._synth_lock:
            generated = self._tts.generate(
                normalized,
                sid=0,
                speed=1.0,
                callback=lambda _samples, _progress: 1 if self.state == State.RUNNING else 0,
            )
        samples = np.asarray(generated.samples, dtype=np.float32).reshape(-1)
        out_sr = int(getattr(generated, "sample_rate", self.sample_rate) or self.sample_rate)
        if samples.size and out_sr != self.sample_rate:
            import resampy

            samples = resampy.resample(samples, out_sr, self.sample_rate).astype(
                np.float32, copy=False
            )
            out_sr = self.sample_rate
        if samples.size:
            peak = float(np.max(np.abs(samples)))
            if peak > 0.88:
                samples = (samples * (0.88 / peak)).astype(np.float32, copy=False)
        return samples, out_sr

    def _emit_synthesized(
        self,
        text: str,
        textevent: dict,
        *,
        chunk_guard: Optional[Callable[[int], bool]] = None,
        discard_uncommitted: Optional[Callable[[], bool]] = None,
    ) -> None:
        samples, _ = self._synthesize_samples(text)
        if self.state != State.RUNNING or (
            discard_uncommitted is not None and discard_uncommitted()
        ):
            return
        if samples.size == 0:
            self.notify_fragment_synthesis_failed(textevent, "tts_empty_audio")
            return
        emitter = TurnPCMEmitter(
            self,
            text,
            textevent,
            chunk_guard=chunk_guard,
        )
        slice_size = max(self.chunk * 4, 1280)
        for offset in range(0, samples.size, slice_size):
            if self.state != State.RUNNING or emitter.cancelled:
                return
            emitter.feed_pcm(samples[offset : offset + slice_size])
        if self.state == State.RUNNING and not emitter.cancelled:
            emitter.finish_pcm()

    def txt_to_audio(self, msg: tuple[str, dict]) -> None:
        text, textevent = msg
        started_at = time.perf_counter()
        try:
            self._emit_synthesized(text, textevent)
        except Exception:
            logger.exception("Matcha TTS synthesis failed")
            self.notify_fragment_synthesis_failed(
                textevent,
                "tts_exhausted_before_audio",
            )
        finally:
            logger.info(
                "-------matcha tts total time:%.4fs",
                time.perf_counter() - started_at,
            )

    def synthesize_fragment(
        self,
        fragment: PlayableFragment,
        *,
        chunk_guard: Callable[[int], bool],
        retry_budget=None,
        fragment_committed=None,
        discard_uncommitted: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Synchronously synthesize one fenced fragment into 20ms PCM frames."""
        del retry_budget, fragment_committed
        envelope = fragment.envelope
        textevent = {
            "turn_id": envelope.turn_id,
            "generation": envelope.generation,
            "fragment_sequence": envelope.sequence,
        }
        try:
            self._emit_synthesized(
                fragment.text,
                textevent,
                chunk_guard=chunk_guard,
                discard_uncommitted=discard_uncommitted,
            )
        except Exception:
            logger.exception("Matcha TTS fragment synthesis failed")
            self.notify_fragment_synthesis_failed(
                textevent,
                "tts_exhausted_before_audio",
            )
