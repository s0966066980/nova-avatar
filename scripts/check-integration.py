#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""接入自檢：驗證 config、Ollama LLM 與 EdgeTTS 是否可用。

用法（需在專案根目錄）：
    uv run python scripts/check-integration.py [config/config_wav2lip.yaml]

不依賴任何 Avatar 模組，可在安裝 wav2lip / MuseTalk 之前先跑。
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.loader import load_config

OK, FAIL = "\033[32m✓\033[0m", "\033[31m✗\033[0m"


def check_config(config_file):
    cfg = load_config(config_file)
    print(f"{OK} 設定載入: {config_file or 'config/config.yaml'}")
    print(f"    TTS   : {cfg.tts.type} / {cfg.tts.ref_file}")
    print(f"    LLM   : {cfg.llm.model} @ {cfg.llm.base_url}")
    print(f"    額外   : {cfg.llm.extra_body or '(無)'}")
    print(f"    Avatar: {cfg.model.type} / {cfg.model.avatar_id}")
    return cfg


def check_llm(cfg):
    from openai import OpenAI

    client = OpenAI(api_key=cfg.llm.api_key, base_url=cfg.llm.base_url)
    prompt = str(cfg.llm.assistant_profile.system_prompt or "").strip()
    if not prompt:
        prompt = Path("config/prompt_en.txt").read_text(encoding="utf-8").strip()

    t0 = time.perf_counter()
    stream = client.chat.completions.create(
        model=cfg.llm.model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": "你好，請簡短自我介紹"},
        ],
        stream=True,
        extra_body=cfg.llm.extra_body or None,
    )

    first, reply = None, ""
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            if first is None:
                first = time.perf_counter() - t0
            reply += chunk.choices[0].delta.content

    print(f"{OK} Ollama 串流正常  首字延遲 {first:.2f}s / 總計 {time.perf_counter()-t0:.2f}s")
    print(f"    回覆: {reply.strip()[:80]}")
    return reply.strip()


def check_tts(cfg, text):
    import edge_tts

    async def run():
        voices = [v["ShortName"] for v in await edge_tts.list_voices()]
        if cfg.tts.ref_file not in voices:
            raise SystemExit(f"{FAIL} EdgeTTS 找不到語音 {cfg.tts.ref_file}")
        print(f"{OK} EdgeTTS 語音存在: {cfg.tts.ref_file}")

        t0 = time.perf_counter()
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text or "測試語音合成", cfg.tts.ref_file).stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return audio, time.perf_counter() - t0

    audio, elapsed = asyncio.run(run())
    if not audio:
        raise SystemExit(f"{FAIL} EdgeTTS 未產生音訊")

    out = Path("logs/tts_check.mp3")
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(audio)
    print(f"{OK} EdgeTTS 合成成功  {len(audio)/1024:.1f} KB / {elapsed:.2f}s  → {out}")


if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    print("=" * 46)
    cfg = check_config(config_file)
    print("-" * 46)
    reply = check_llm(cfg)
    print("-" * 46)
    check_tts(cfg, reply)
    print("=" * 46)
    print("全部通過，Ollama + EdgeTTS 接入正常。")
