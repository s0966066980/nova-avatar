#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Validate the checked-in Nova Avatar project contract and optional services.

The default check is offline and leaves no artifacts behind. ``--smoke`` adds
real calls to the configured OpenAI-compatible LLM endpoint and Edge TTS. Use
``--output`` only when a generated Edge TTS MP3 should be retained.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.loader import load_config


ROOT = Path(__file__).resolve().parent.parent
OK, FAIL = "\033[32m✓\033[0m", "\033[31m✗\033[0m"
REQUIRED_FILES = {
    "LICENSE": ("Apache License",),
    "NOTICE": ("Kedreamix", "Linly-Talker-Stream", "LiveTalking"),
    "THIRD_PARTY_NOTICES.md": ("MuseTalk", "Wav2Lip", "Research / Non-commercial"),
    "third_party/licenses/MuseTalk-LICENSE.txt": (),
    "third_party/licenses/Wav2Lip-NON-COMMERCIAL-NOTICE.txt": (),
    "docs/software-stack.md": ("Nova Avatar Software Stack",),
    "docs/source-attribution-audit.md": ("Source Attribution Audit",),
    "docs/current-project-workflow.md": ("Current Project Workflow", "清除過往工作項目"),
}
REQUIRED_MODULES = ("openai", "edge_tts", "yaml")


def _fail(message: str) -> None:
    raise RuntimeError(f"{FAIL} {message}")


def check_config(config_file: str | None):
    cfg = load_config(config_file)
    source = config_file or "config/config.yaml"
    print(f"{OK} 設定載入: {source}")
    print(f"    Avatar: {cfg.model.type} / {cfg.model.avatar_id}")
    print(f"    STT   : {cfg.asr.type} / {cfg.asr.model_size}")
    print(f"    VAD   : {cfg.vad.type} / {'enabled' if cfg.vad.enabled else 'disabled'}")
    print(f"    LLM   : {cfg.llm.provider} / {cfg.llm.model} @ {cfg.llm.base_url}")
    print(f"    TTS   : {cfg.tts.type} / {cfg.tts.ref_file}")
    return cfg


def check_project_contract() -> None:
    """Check stable, offline release prerequisites without contacting services."""
    for relative, required_text in REQUIRED_FILES.items():
        path = ROOT / relative
        if not path.is_file():
            _fail(f"缺少必要專案檔案: {relative}")
        text = path.read_text(encoding="utf-8") if required_text else ""
        missing = [value for value in required_text if value not in text]
        if missing:
            _fail(f"{relative} 缺少必要內容: {', '.join(missing)}")

    missing_modules = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if missing_modules:
        _fail(f"缺少已宣告的 Python 依賴: {', '.join(missing_modules)}")
    print(f"{OK} 品牌、授權與 release 文件契約正常")
    print(f"{OK} 核心 Python 整合依賴可匯入")


def check_commercial_profile() -> None:
    profile = ROOT / "config/config_commercial.yaml"
    cfg = load_config(str(profile))
    if cfg.model.type != "musetalk":
        _fail("commercial review profile 必須選用 musetalk")
    print(f"{OK} 商業審查設定檔使用 {cfg.model.type}")


def check_llm_smoke(cfg) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=cfg.llm.api_key, base_url=cfg.llm.base_url)
    t0 = time.perf_counter()
    stream = client.chat.completions.create(
        model=cfg.llm.model,
        messages=[{"role": "user", "content": "請只回答：Nova Avatar smoke test"}],
        stream=True,
        extra_body=cfg.llm.extra_body or None,
    )
    first, reply = None, ""
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            if first is None:
                first = time.perf_counter() - t0
            reply += chunk.choices[0].delta.content
    if not reply.strip():
        _fail("LLM smoke test 未取得文字回覆")
    first_text = f"{first:.2f}s" if first is not None else "n/a"
    print(f"{OK} {cfg.llm.provider} LLM 串流正常  首字延遲 {first_text}")
    return reply.strip()


def check_edgetts_smoke(cfg, text: str, output: Path | None) -> None:
    import edge_tts

    async def run() -> bytes:
        voices = {voice["ShortName"] for voice in await edge_tts.list_voices()}
        if cfg.tts.ref_file not in voices:
            _fail(f"Edge TTS 找不到語音 {cfg.tts.ref_file}")
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, cfg.tts.ref_file).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    audio = asyncio.run(run())
    if not audio:
        _fail("Edge TTS 未產生音訊")
    print(f"{OK} Edge TTS 合成正常  {len(audio) / 1024:.1f} KB")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(audio)
        print(f"    音檔已寫入: {output}")


def check_tts_smoke(cfg, text: str, output: Path | None) -> None:
    if cfg.tts.type != "edgetts":
        _fail(
            f"整合 smoke 尚無 {cfg.tts.type!r} 的無副作用 adapter；"
            "請使用該引擎的專用測試或切換到已支援的 edgetts 後重試"
        )
    check_edgetts_smoke(cfg, text, output)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", help="YAML 設定檔，預設為 config/config.yaml")
    parser.add_argument("--smoke", action="store_true", help="呼叫目前設定的 LLM 與 TTS")
    parser.add_argument("--output", type=Path, help="僅在 smoke 時寫入生成的 Edge TTS MP3")
    args = parser.parse_args(argv)
    if args.output is not None and not args.smoke:
        parser.error("--output requires --smoke")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print("=" * 54)
    cfg = check_config(args.config)
    check_project_contract()
    check_commercial_profile()
    if args.smoke:
        print("-" * 54)
        reply = check_llm_smoke(cfg)
        check_tts_smoke(cfg, reply, args.output)
    print("=" * 54)
    print("全部通過：Nova Avatar 專案檢查正常。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
