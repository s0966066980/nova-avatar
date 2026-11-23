# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""控制台引導式 Matcha-TTS 語音蒸餾與微調工作管理模組。"""

from __future__ import annotations

import base64
import collections
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Any

from src.server.runtime_settings import SettingsError
from src.utils.logging import logger
from src.utils.paths import get_project_root

STEP_ORDER = ("corpus", "distill", "train", "export")
ALL_STEPS = STEP_ORDER + ("full",)
TEACHER_EDGETTS = "edgetts"
TEACHER_COSYVOICE = "cosyvoice"

EDGE_LICENSE_TAG = "Research / Non-commercial"
COSYVOICE_LICENSE_TAG = "Apache-2.0 Pipeline · Local Prompt"

DEFAULT_EDGE_VOICES: tuple[dict[str, str], ...] = (
    {"id": "zh-TW-HsiaoChenNeural", "label": "zh-TW 曉臻（女聲，預設）", "lang": "zh-TW"},
    {"id": "zh-TW-YunJheNeural", "label": "zh-TW 雲哲（男聲）", "lang": "zh-TW"},
    {"id": "zh-TW-HsiaoYuNeural", "label": "zh-TW 曉雨（女聲）", "lang": "zh-TW"},
    {"id": "en-US-JennyNeural", "label": "en-US Jenny（美式女聲）", "lang": "en-US"},
    {"id": "en-US-AriaNeural", "label": "en-US Aria（美式女聲）", "lang": "en-US"},
    {"id": "en-US-GuyNeural", "label": "en-US Guy（美式男聲）", "lang": "en-US"},
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,48}$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,80}$")

_MAX_LOG_LINES = 160
_LOCK = threading.Lock()
_CURRENT_JOB: TtsTrainingJob | None = None
_ACTIVE_PROC: subprocess.Popen[str] | None = None
_CANCEL_EVENT = threading.Event()


@dataclass
class TtsTrainingConfig:
    """語音訓練流水線設定。"""

    slug: str = "zh-tw-custom"
    teacher: str = TEACHER_EDGETTS
    # Step 1: Corpus
    corpus_hours: float = 0.25
    corpus_seed: int = 42
    preserve_existing: bool = True
    extra_sentences: str = ""
    # Step 2: Teacher synthesis
    edge_voice: str = "zh-TW-HsiaoChenNeural"
    prompt_wav: str = "data/tts/prompts/zh-TW-YunJheNeural.cosy24k.v2.wav"
    prompt_txt: str = "data/tts/prompts/zh-TW-YunJheNeural.cosy24k.v2.txt"
    whisper_model: str = "small"
    asr_device: str = "cuda"
    min_asr_sim: float = 0.65
    delay_seconds: float = 0.15
    distill_limit: int = 0
    resume_distill: bool = True
    skip_asr: bool = False
    # Step 3: Matcha fine-tune
    epochs: int = 20
    batch_size: int = 6
    lr: float = 3e-5
    encoder_lr_scale: float = 0.25
    proj_lr_scale: float = 0.35
    freeze_emb: bool = True
    freeze_encoder_body: bool = False
    full_seq: bool = True
    pad_silence_ms: int = 120
    encoder_anchor: float = 0.05
    dur_bounds_weight: float = 1.0
    # Step 4: ONNX export
    num_ode_steps: int = 4

    def validate(self) -> None:
        if not _SLUG_RE.match(self.slug):
            raise SettingsError(
                "模型代號格式不正確（請使用 2-49 字元小寫英數字、連字號、底線或點）"
            )
        if self.teacher not in {TEACHER_EDGETTS, TEACHER_COSYVOICE}:
            raise SettingsError("不支援的教師聲線來源（僅支援 edgetts 或 cosyvoice）")
        if not (0.02 <= float(self.corpus_hours) <= 10.0):
            raise SettingsError("語料目標時數必須介於 0.02 與 10.0 小時之間")
        if not (0.0 <= float(self.min_asr_sim) <= 1.0):
            raise SettingsError("Whisper 語音相似度門檻必須介於 0.0 與 1.0 之間")
        if self.asr_device not in {"cuda", "cpu"}:
            raise SettingsError("Whisper QA 裝置必須為 cuda 或 cpu")
        if not (1 <= int(self.epochs) <= 200):
            raise SettingsError("訓練 Epochs 必須介於 1 與 200 之間")
        if not (1 <= int(self.batch_size) <= 64):
            raise SettingsError("Batch Size 必須介於 1 與 64 之間")
        if not (1e-6 <= float(self.lr) <= 1e-2):
            raise SettingsError("Learning Rate 超出合理範圍（1e-6 ~ 1e-2）")
        if not (0 <= int(self.pad_silence_ms) <= 500):
            raise SettingsError("句末補靜音長度必須介於 0 與 500 毫秒之間")
        if not (2 <= int(self.num_ode_steps) <= 16):
            raise SettingsError("ONNX ODE 步數必須介於 2 與 16 之間")


@dataclass
class TtsTrainingJob:
    """背景語音訓練任務狀態。"""

    id: str
    slug: str
    mode: str
    teacher: str
    status: str = "queued"  # queued | running | done | failed | cancelled
    current_step: str = ""
    progress: int = 0
    message: str = "等待執行"
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    step_states: dict[str, str] = field(
        default_factory=lambda: {step: "pending" for step in STEP_ORDER}
    )
    logs: collections.deque[str] = field(
        default_factory=lambda: collections.deque(maxlen=_MAX_LOG_LINES)
    )
    output_model_dir: str = ""
    license_tag: str = EDGE_LICENSE_TAG

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "mode": self.mode,
            "teacher": self.teacher,
            "status": self.status,
            "current_step": self.current_step,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "step_states": dict(self.step_states),
            "logs": list(self.logs),
            "output_model_dir": self.output_model_dir,
            "license_tag": self.license_tag,
            "non_commercial": self.teacher == TEACHER_EDGETTS,
        }


def parse_training_config(payload: dict[str, Any] | None) -> TtsTrainingConfig:
    """解析並驗證前端傳入的訓練設定。"""
    raw = payload if isinstance(payload, dict) else {}
    defaults = TtsTrainingConfig()
    cfg = TtsTrainingConfig(
        slug=str(raw.get("slug") or defaults.slug).strip().lower(),
        teacher=str(raw.get("teacher") or defaults.teacher).strip().lower(),
        corpus_hours=float(raw.get("corpus_hours", defaults.corpus_hours)),
        corpus_seed=int(raw.get("corpus_seed", defaults.corpus_seed)),
        preserve_existing=bool(raw.get("preserve_existing", defaults.preserve_existing)),
        extra_sentences=str(raw.get("extra_sentences") or ""),
        edge_voice=str(raw.get("edge_voice") or defaults.edge_voice).strip(),
        prompt_wav=str(raw.get("prompt_wav") or defaults.prompt_wav).strip(),
        prompt_txt=str(raw.get("prompt_txt") or defaults.prompt_txt).strip(),
        whisper_model=str(raw.get("whisper_model") or defaults.whisper_model).strip(),
        asr_device=str(raw.get("asr_device") or defaults.asr_device).strip().lower(),
        min_asr_sim=float(raw.get("min_asr_sim", defaults.min_asr_sim)),
        delay_seconds=float(raw.get("delay_seconds", defaults.delay_seconds)),
        distill_limit=int(raw.get("distill_limit", defaults.distill_limit)),
        resume_distill=bool(raw.get("resume_distill", defaults.resume_distill)),
        skip_asr=bool(raw.get("skip_asr", defaults.skip_asr)),
        epochs=int(raw.get("epochs", defaults.epochs)),
        batch_size=int(raw.get("batch_size", defaults.batch_size)),
        lr=float(raw.get("lr", defaults.lr)),
        encoder_lr_scale=float(raw.get("encoder_lr_scale", defaults.encoder_lr_scale)),
        proj_lr_scale=float(raw.get("proj_lr_scale", defaults.proj_lr_scale)),
        freeze_emb=bool(raw.get("freeze_emb", defaults.freeze_emb)),
        freeze_encoder_body=bool(raw.get("freeze_encoder_body", defaults.freeze_encoder_body)),
        full_seq=bool(raw.get("full_seq", defaults.full_seq)),
        pad_silence_ms=int(raw.get("pad_silence_ms", defaults.pad_silence_ms)),
        encoder_anchor=float(raw.get("encoder_anchor", defaults.encoder_anchor)),
        dur_bounds_weight=float(raw.get("dur_bounds_weight", defaults.dur_bounds_weight)),
        num_ode_steps=int(raw.get("num_ode_steps", defaults.num_ode_steps)),
    )
    cfg.validate()
    return cfg


def workspace_paths(repo_root: Path, slug: str) -> dict[str, Path]:
    """回傳指定模型代號的工作目錄與輸出路徑。"""
    if not _SLUG_RE.match(slug):
        raise SettingsError("模型代號格式不正確")
    distill_dir = repo_root / "data/tts/training" / slug
    return {
        "distill_dir": distill_dir,
        "corpus": distill_dir / "corpus.jsonl",
        "manifest": distill_dir / "manifest.jsonl",
        "ckpt_dir": distill_dir / "ckpt",
        "export_dir": repo_root / "models/tts" / slug,
        "base_ckpt": repo_root / ".local/matcha-base/pytorch_model_sherpa.bin",
        "cosy_python": repo_root / ".local/cosyvoice3/venv/bin/python",
        "cosy_model": repo_root / ".local/cosyvoice3/model",
        "matcha_src": repo_root / ".local/cosyvoice3/CosyVoice/third_party/Matcha-TTS",
    }


def _resolve_repo_subpath(repo_root: Path, rel_or_abs: str) -> Path:
    """確保參考音檔路徑留在 repo 根目錄底下，防止路徑遍歷。"""
    candidate = Path(rel_or_abs)
    resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
    root_resolved = repo_root.resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise SettingsError("參考檔案路徑必須位於專案目錄內")
    return resolved


def _jsonl_stats(path: Path) -> tuple[int, float]:
    """統計 JSONL 語料行數與累計時長（秒）。"""
    if not path.is_file():
        return 0, 0.0
    count = 0
    seconds = 0.0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                count += 1
                try:
                    item = json.loads(stripped)
                    seconds += float(item.get("duration", item.get("est_seconds", 0.0)) or 0.0)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
    except OSError:
        return 0, 0.0
    return count, seconds


def _pick_checkpoint(ckpt_dir: Path) -> Path | None:
    best = ckpt_dir / "best.pt"
    if best.is_file():
        return best
    latest = ckpt_dir / "latest.pt"
    if latest.is_file():
        return latest
    return None


def _list_prompts(repo_root: Path) -> list[dict[str, str]]:
    prompt_dir = repo_root / "data/tts/prompts"
    if not prompt_dir.is_dir():
        return []
    items: list[dict[str, str]] = []
    for wav in sorted(prompt_dir.glob("*.wav")):
        txt = wav.with_suffix(".txt")
        if txt.is_file():
            items.append(
                {
                    "id": wav.stem,
                    "wav": wav.relative_to(repo_root).as_posix(),
                    "txt": txt.relative_to(repo_root).as_posix(),
                }
            )
    return items


def _list_trained_models(repo_root: Path) -> list[dict[str, Any]]:
    tts_root = repo_root / "models/tts"
    if not tts_root.is_dir():
        return []
    models: list[dict[str, Any]] = []
    for entry in sorted(tts_root.iterdir()):
        if not entry.is_dir():
            continue
        if not ((entry / "model.onnx").is_file() and (entry / "tokens.txt").is_file()):
            continue
        meta: dict[str, Any] = {}
        meta_path = entry / "training_metadata.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        has_notice = (entry / "NOTICE-NON-COMMERCIAL.txt").is_file()
        non_commercial = bool(
            meta.get("non_commercial", False)
            or has_notice
            or meta.get("teacher") == TEACHER_EDGETTS
        )
        license_tag = str(
            meta.get("license_tag")
            or (EDGE_LICENSE_TAG if non_commercial else "Apache-2.0 / Check Model Terms")
        )
        models.append(
            {
                "slug": entry.name,
                "path": f"models/tts/{entry.name}",
                "teacher": str(meta.get("teacher") or ""),
                "voice": str(meta.get("voice") or ""),
                "license_tag": license_tag,
                "non_commercial": non_commercial,
                "created_at": meta.get("created_at"),
            }
        )
    return models


def inspect_workspace(slug: str, repo_root: Path | None = None) -> dict[str, Any]:
    """檢查指定模型工作區的各步驟就緒狀態與產物統計。"""
    root = repo_root or get_project_root()
    paths = workspace_paths(root, slug)
    corpus_lines, corpus_sec = _jsonl_stats(paths["corpus"])
    manifest_lines, manifest_sec = _jsonl_stats(paths["manifest"])
    ckpt = _pick_checkpoint(paths["ckpt_dir"])
    export_ready = (paths["export_dir"] / "model.onnx").is_file() and (
        paths["export_dir"] / "tokens.txt"
    ).is_file()
    return {
        "slug": slug,
        "distill_dir": paths["distill_dir"].relative_to(root).as_posix(),
        "export_dir": paths["export_dir"].relative_to(root).as_posix(),
        "corpus_ready": corpus_lines > 0,
        "corpus_lines": corpus_lines,
        "corpus_hours": round(corpus_sec / 3600.0, 3),
        "manifest_ready": manifest_lines > 0,
        "manifest_lines": manifest_lines,
        "manifest_hours": round(manifest_sec / 3600.0, 3),
        "ckpt_ready": ckpt is not None,
        "ckpt_file": ckpt.name if ckpt else "",
        "export_ready": export_ready,
    }


def get_training_snapshot(
    slug: str = "zh-tw-custom",
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """取得環境前置檢查、教師聲線清單、工作區進度與目前任務狀態。"""
    root = repo_root or get_project_root()
    safe_slug = slug.strip().lower() if slug and _SLUG_RE.match(slug.strip().lower()) else "zh-tw-custom"
    paths = workspace_paths(root, safe_slug)
    cosy_py = paths["cosy_python"]
    with _LOCK:
        job_data = _CURRENT_JOB.to_dict() if _CURRENT_JOB else None

    return {
        "prerequisites": {
            "python_main": sys.executable,
            "cosy_venv_ready": cosy_py.is_file(),
            "cosy_venv_path": ".local/cosyvoice3/venv/bin/python",
            "base_ckpt_ready": paths["base_ckpt"].is_file(),
            "base_ckpt_path": ".local/matcha-base/pytorch_model_sherpa.bin",
            "cosyvoice_model_ready": paths["cosy_model"].is_dir(),
            "matcha_src_ready": paths["matcha_src"].is_dir(),
        },
        "edge_voices": list(DEFAULT_EDGE_VOICES),
        "prompts": _list_prompts(root),
        "trained_models": _list_trained_models(root),
        "workspace": inspect_workspace(safe_slug, root),
        "job": job_data,
        "license_tags": {
            TEACHER_EDGETTS: EDGE_LICENSE_TAG,
            TEACHER_COSYVOICE: COSYVOICE_LICENSE_TAG,
        },
    }


def training_in_progress() -> bool:
    with _LOCK:
        return _CURRENT_JOB is not None and _CURRENT_JOB.status in {"queued", "running"}


def append_custom_sentences(corpus_path: Path, extra_sentences: str) -> int:
    """將使用者手動填入的自訂訓練句附加到 corpus.jsonl（自動去重）。"""
    lines = [line.strip() for line in (extra_sentences or "").splitlines() if line.strip()]
    if not lines:
        return 0
    existing_texts: set[str] = set()
    existing_count = 0
    if corpus_path.is_file():
        for raw in corpus_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            existing_count += 1
            try:
                existing_texts.add(str(json.loads(raw).get("text", "")).strip())
            except json.JSONDecodeError:
                pass
    added = 0
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    with corpus_path.open("a", encoding="utf-8") as handle:
        for sentence in lines:
            if sentence in existing_texts:
                continue
            existing_texts.add(sentence)
            is_zh = bool(_CJK_RE.search(sentence))
            est_seconds = round(max(1.2, len(sentence) * (0.24 if is_zh else 0.08)), 2)
            item = {
                "id": f"custom_{existing_count + added:05d}",
                "language": "zh" if is_zh else "en",
                "text": sentence,
                "est_seconds": est_seconds,
            }
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            added += 1
    return added


def build_step_command(
    step: str,
    cfg: TtsTrainingConfig,
    *,
    repo_root: Path | None = None,
) -> list[str]:
    """依步驟建立對應的 tools/tts-distill CLI 指令（供執行與單元測試驗證）。"""
    root = repo_root or get_project_root()
    paths = workspace_paths(root, cfg.slug)
    scripts_dir = root / "tools/tts-distill"

    if step == "corpus":
        cmd = [
            sys.executable,
            str(scripts_dir / "build_corpus.py"),
            "--hours",
            str(cfg.corpus_hours),
            "--seed",
            str(cfg.corpus_seed),
            "--output",
            str(paths["corpus"]),
        ]
        if cfg.preserve_existing:
            cmd.append("--preserve-existing")
        return cmd

    if step == "distill":
        if cfg.teacher == TEACHER_EDGETTS:
            cmd = [
                sys.executable,
                str(scripts_dir / "distill_edge_teacher.py"),
                "--corpus",
                str(paths["corpus"]),
                "--out-dir",
                str(paths["distill_dir"]),
                "--voice",
                cfg.edge_voice,
                "--whisper-model",
                cfg.whisper_model,
                "--asr-device",
                cfg.asr_device,
                "--min-asr-sim",
                str(cfg.min_asr_sim),
                "--delay-seconds",
                str(cfg.delay_seconds),
            ]
        else:
            prompt_wav = _resolve_repo_subpath(root, cfg.prompt_wav)
            prompt_txt = _resolve_repo_subpath(root, cfg.prompt_txt)
            cmd = [
                str(paths["cosy_python"]),
                str(scripts_dir / "distill_teacher.py"),
                "--corpus",
                str(paths["corpus"]),
                "--out-dir",
                str(paths["distill_dir"]),
                "--prompt-wav",
                str(prompt_wav),
                "--prompt-txt",
                str(prompt_txt),
                "--cosyvoice-dir",
                str(paths["cosy_model"]),
                "--whisper-model",
                cfg.whisper_model,
                "--min-asr-sim",
                str(cfg.min_asr_sim),
            ]
        if cfg.distill_limit > 0:
            cmd.extend(["--limit", str(cfg.distill_limit)])
        if cfg.resume_distill:
            cmd.append("--resume")
        if cfg.skip_asr:
            cmd.append("--skip-asr")
        return cmd

    if step == "train":
        cmd = [
            str(paths["cosy_python"]),
            str(scripts_dir / "train_matcha.py"),
            "--manifest",
            str(paths["manifest"]),
            "--base-ckpt",
            str(paths["base_ckpt"]),
            "--out-dir",
            str(paths["ckpt_dir"]),
            "--batch-size",
            str(cfg.batch_size),
            "--epochs",
            str(cfg.epochs),
            "--lr",
            str(cfg.lr),
            "--encoder-lr-scale",
            str(cfg.encoder_lr_scale),
            "--proj-lr-scale",
            str(cfg.proj_lr_scale),
            "--pad-silence-ms",
            str(cfg.pad_silence_ms),
            "--encoder-anchor",
            str(cfg.encoder_anchor),
            "--dur-bounds-weight",
            str(cfg.dur_bounds_weight),
        ]
        if cfg.freeze_emb:
            cmd.append("--freeze-emb")
        if cfg.freeze_encoder_body:
            cmd.append("--freeze-encoder-body")
        if cfg.full_seq:
            cmd.append("--full-seq")
        return cmd

    if step == "export":
        ckpt = _pick_checkpoint(paths["ckpt_dir"]) or (paths["ckpt_dir"] / "best.pt")
        return [
            str(paths["cosy_python"]),
            str(scripts_dir / "export_matcha_onnx.py"),
            "--ckpt",
            str(ckpt),
            "--output-dir",
            str(paths["export_dir"]),
            "--num-ode-steps",
            str(cfg.num_ode_steps),
        ]

    raise SettingsError(f"不支援的訓練步驟：{step}")


def write_export_notices(export_dir: Path, cfg: TtsTrainingConfig) -> None:
    """寫入匯出模型中繼資料與 Edge-TTS 非商業授權告示。"""
    export_dir.mkdir(parents=True, exist_ok=True)
    non_commercial = cfg.teacher == TEACHER_EDGETTS
    license_tag = EDGE_LICENSE_TAG if non_commercial else COSYVOICE_LICENSE_TAG
    metadata = {
        "slug": cfg.slug,
        "teacher": cfg.teacher,
        "voice": cfg.edge_voice if non_commercial else cfg.prompt_wav,
        "license_tag": license_tag,
        "non_commercial": non_commercial,
        "epochs": cfg.epochs,
        "num_ode_steps": cfg.num_ode_steps,
        "created_at": time.time(),
    }
    (export_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    notice_path = export_dir / "NOTICE-NON-COMMERCIAL.txt"
    if non_commercial:
        notice_path.write_text(
            (
                "Classification: Research / Non-commercial\n"
                f"Teacher source: Microsoft Edge-TTS ({cfg.edge_voice})\n\n"
                "This distilled Matcha-TTS checkpoint and ONNX bundle were trained using\n"
                "synthetic audio generated by Microsoft Edge-TTS and are restricted to\n"
                "Research / Non-commercial use only. Commercial redistribution or\n"
                "production commercial deployment is prohibited.\n"
            ),
            encoding="utf-8",
        )
    elif notice_path.is_file():
        notice_path.unlink()


def _validate_step_prerequisites(step: str, cfg: TtsTrainingConfig, repo_root: Path) -> None:
    paths = workspace_paths(repo_root, cfg.slug)
    steps = STEP_ORDER if step == "full" else (step,)

    if "distill" in steps:
        if step == "distill" and not paths["corpus"].is_file():
            raise SettingsError("尚未產生語料（corpus.jsonl），請先執行步驟 1「建立語料」")
        if cfg.teacher == TEACHER_COSYVOICE:
            if not paths["cosy_python"].is_file():
                raise SettingsError("找不到 CosyVoice3 訓練虛擬環境（.local/cosyvoice3/venv/bin/python）")
            if not paths["cosy_model"].is_dir():
                raise SettingsError("找不到本機 CosyVoice3 模型目錄（.local/cosyvoice3/model）")
            prompt_wav = _resolve_repo_subpath(root := repo_root, cfg.prompt_wav)
            prompt_txt = _resolve_repo_subpath(root, cfg.prompt_txt)
            if not prompt_wav.is_file() or not prompt_txt.is_file():
                raise SettingsError("找不到 CosyVoice3 參考音檔與對應文字檔")

    if "train" in steps:
        if not paths["cosy_python"].is_file():
            raise SettingsError("找不到 CUDA 訓練環境（.local/cosyvoice3/venv/bin/python）")
        if not paths["base_ckpt"].is_file():
            raise SettingsError("找不到 Matcha 基礎權重（.local/matcha-base/pytorch_model_sherpa.bin）")
        if step == "train":
            lines, _ = _jsonl_stats(paths["manifest"])
            if lines <= 0:
                raise SettingsError("尚未完成有效的 Whisper QA 教師音檔清單（manifest.jsonl），請先執行步驟 2")

    if "export" in steps:
        if not paths["cosy_python"].is_file():
            raise SettingsError("找不到 ONNX 匯出環境（.local/cosyvoice3/venv/bin/python）")
        if step == "export" and _pick_checkpoint(paths["ckpt_dir"]) is None:
            raise SettingsError("尚未找到訓練完成的 checkpoint（best.pt / latest.pt），請先執行步驟 3")


def _run_subprocess(
    cmd: list[str],
    *,
    cwd: Path,
    job: TtsTrainingJob,
    step_label: str,
) -> int:
    global _ACTIVE_PROC
    job.logs.append(f"[{step_label}] $ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    with _LOCK:
        _ACTIVE_PROC = proc
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip()
            if text:
                job.logs.append(text)
            if _CANCEL_EVENT.is_set() and proc.poll() is None:
                proc.terminate()
        return proc.wait()
    finally:
        with _LOCK:
            if _ACTIVE_PROC is proc:
                _ACTIVE_PROC = None


def start_training_step(
    *,
    step: str,
    cfg: TtsTrainingConfig,
    session_count: int = 0,
    repo_root: Path | None = None,
) -> TtsTrainingJob:
    """啟動背景語音訓練步驟（單一步驟或 full 全流程）。"""
    global _CURRENT_JOB
    if step not in ALL_STEPS:
        raise SettingsError(f"不支援的訓練步驟：{step}")
    cfg.validate()
    root = repo_root or get_project_root()

    heavy_gpu = step in {"train", "full"} or (
        step == "distill" and (cfg.teacher == TEACHER_COSYVOICE or (cfg.asr_device == "cuda" and not cfg.skip_asr))
    )
    if heavy_gpu and session_count > 0:
        raise SettingsError(
            "有活躍連線執行中，執行蒸餾或 GPU 訓練前請先中斷連線以釋放顯存",
            status=409,
            extra={"need_disconnect": True},
        )

    _validate_step_prerequisites(step, cfg, root)

    with _LOCK:
        if _CURRENT_JOB is not None and _CURRENT_JOB.status in {"queued", "running"}:
            raise SettingsError("已有語音訓練任務正在執行中，請稍候或先取消目前任務", status=409)
        _CANCEL_EVENT.clear()
        job_id = f"tts-train-{int(time.time())}"
        steps_to_run = list(STEP_ORDER if step == "full" else (step,))
        step_states = {
            name: ("pending" if name in steps_to_run else "skipped")
            for name in STEP_ORDER
        }
        job = TtsTrainingJob(
            id=job_id,
            slug=cfg.slug,
            mode=step,
            teacher=cfg.teacher,
            status="running",
            current_step=steps_to_run[0],
            progress=2,
            message=f"準備執行步驟：{steps_to_run[0]}",
            step_states=step_states,
            output_model_dir=f"models/tts/{cfg.slug}",
            license_tag=EDGE_LICENSE_TAG if cfg.teacher == TEACHER_EDGETTS else COSYVOICE_LICENSE_TAG,
        )
        _CURRENT_JOB = job

    def _runner() -> None:
        paths = workspace_paths(root, cfg.slug)
        total = len(steps_to_run)
        step_titles = {
            "corpus": "步驟 1：建立中英雙語訓練語料",
            "distill": "步驟 2：教師聲線合成與 Whisper QA 驗收",
            "train": "步驟 3：Matcha-TTS CUDA 聲學模型微調",
            "export": "步驟 4：匯出 ONNX 模型並寫入授權標註",
        }
        try:
            for idx, cur in enumerate(steps_to_run):
                if _CANCEL_EVENT.is_set():
                    job.status = "cancelled"
                    job.step_states[cur] = "cancelled"
                    job.message = "任務已由使用者取消"
                    return
                job.current_step = cur
                job.step_states[cur] = "running"
                job.progress = max(5, int((idx / total) * 100))
                job.message = step_titles[cur]

                cmd = build_step_command(cur, cfg, repo_root=root)
                rc = _run_subprocess(cmd, cwd=root, job=job, step_label=cur)
                if _CANCEL_EVENT.is_set():
                    job.status = "cancelled"
                    job.step_states[cur] = "cancelled"
                    job.message = "任務已由使用者取消"
                    return
                if rc != 0:
                    raise RuntimeError(f"{step_titles[cur]} 失敗（exit code {rc}）")

                if cur == "corpus" and cfg.extra_sentences.strip():
                    added = append_custom_sentences(paths["corpus"], cfg.extra_sentences)
                    if added:
                        job.logs.append(f"[corpus] 已額外加入 {added} 筆自訂語料句")
                elif cur == "export":
                    write_export_notices(paths["export_dir"], cfg)
                    job.logs.append(
                        f"[export] 已寫入授權與模型資訊（{job.license_tag}）至 {paths['export_dir']}"
                    )

                job.step_states[cur] = "done"
                job.progress = min(99, int(((idx + 1) / total) * 100))

            job.status = "done"
            job.progress = 100
            job.message = f"完成：{step_titles[steps_to_run[-1]]}"
        except Exception as exc:
            logger.exception("TTS 訓練任務失敗：%s", exc)
            if job.current_step:
                job.step_states[job.current_step] = "failed"
            job.status = "failed"
            job.error = str(exc)
            job.message = f"失敗：{exc}"
        finally:
            job.finished_at = time.time()

    threading.Thread(target=_runner, daemon=True, name=f"tts-train-{cfg.slug}").start()
    return job


def cancel_training_job() -> dict[str, Any]:
    """中止目前正在執行的語音訓練任務。"""
    _CANCEL_EVENT.set()
    with _LOCK:
        proc = _ACTIVE_PROC
        job = _CURRENT_JOB
    if proc is not None and proc.poll() is None:
        try:
            proc.send_signal(signal.SIGTERM)
        except OSError:
            pass
    if job is not None and job.status in {"queued", "running"}:
        job.message = "正在停止訓練程序…"
    return job.to_dict() if job is not None else {"status": "idle"}


def default_preview_text_for_voice(voice: str) -> str:
    """依 Edge-TTS 聲線語系回傳對應的預設試聽短句。"""
    lower = voice.lower()
    if lower.startswith("en-"):
        return "Hello, this is a preview of the selected Edge TTS teacher voice."
    if lower.startswith("ja-"):
        return "こんにちは、選択中の音声のテスト再生です。"
    return "您好，這是目前選擇的 Edge-TTS 教師聲線試聽範例。"


async def synthesize_edge_voice_preview(voice: str, text: str | None = None) -> str:
    """使用專案既有的 EdgeConnectionPool 合成教師聲線試聽音訊（MP3 Data URI）。"""
    clean_voice = (voice or "").strip()
    if not _VOICE_ID_RE.match(clean_voice):
        raise SettingsError("請輸入或選擇有效的 Edge-TTS 聲線名稱（例如 zh-TW-HsiaoChenNeural）")

    sample_text = (text or "").strip() or default_preview_text_for_voice(clean_voice)
    if len(sample_text) > 120:
        sample_text = sample_text[:120]

    from src.tts.edge_connection import EdgeConnectionPool

    pool = EdgeConnectionPool(max_idle=1)
    chunks: list[bytes] = []
    try:
        async for chunk in pool.stream(sample_text, clean_voice):
            if chunk.get("type") == "audio":
                data = chunk.get("data")
                if data:
                    chunks.append(data)
        audio_bytes = b"".join(chunks)
    except SettingsError:
        raise
    except Exception as exc:
        raise SettingsError(f"Edge-TTS 試聽失敗：{exc}", status=502) from exc
    finally:
        await pool.close()

    if not audio_bytes:
        raise SettingsError("Edge-TTS 試聽未產生音訊，請檢查聲線名稱或網路連線", status=502)

    return "data:audio/mpeg;base64," + base64.b64encode(audio_bytes).decode("ascii")
