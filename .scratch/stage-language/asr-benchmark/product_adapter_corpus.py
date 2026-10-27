# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Generate eight new questions through Nova's real Edge adapter, without config."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import soundfile as sf
from faster_whisper.audio import decode_audio

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SAMPLES = [
    ("product_zh_01", "zh", "zh-TW-HsiaoChenNeural", "請問訂單編號一二三的進度？", ["訂單", "進度"], []),
    ("product_zh_02", "zh", "zh-TW-HsiaoChenNeural", "博物館明天幾點開門，星期六需要預約嗎？", ["博物館", "明天", "預約"], []),
    ("product_en_01", "en", "en-US-JennyNeural", "What time does the museum open tomorrow?", [], ["museum", "open", "tomorrow"]),
    ("product_en_02", "en", "en-US-JennyNeural", "Could you check the status of my order and explain the return policy?", [], ["order", "return", "policy"]),
    ("product_mixed_01", "mixed", "en-US-EmmaMultilingualNeural", "請幫我查一下 order number A B C one two three 的進度。", ["進度"], ["order", "number"]),
    ("product_mixed_02", "mixed", "en-US-EmmaMultilingualNeural", "這個 product 有沒有 warranty 和 return policy？", ["這個", "有沒有"], ["product", "warranty", "return", "policy"]),
    ("product_mixed_03", "mixed", "en-US-EmmaMultilingualNeural", "Can you explain 退貨流程 and tell me how many days it takes?", ["退貨", "流程"], ["explain", "days", "takes"]),
    ("product_mixed_04", "mixed", "en-US-EmmaMultilingualNeural", "我想 book a meeting room，明天 morning 還有空位嗎？", ["我想", "明天", "空位"], ["book", "meeting", "room", "morning"]),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main():
    # Product logging initializes relative logs/: keep that inside the owned folder.
    os.chdir(OUT)
    sys.path.insert(0, str(ROOT))
    from src.tts.engines.edge import _edge_communicate
    from edge_tts import communicate as transport

    audio_dir = OUT / "product-audio"
    audio_dir.mkdir(exist_ok=True)
    fixtures = []
    for sample_id, category, voice, expected, zh_anchors, en_anchors in SAMPLES:
        mp3, wav = audio_dir / f"{sample_id}.mp3", audio_dir / f"{sample_id}.wav"
        start = time.perf_counter()
        if not mp3.exists() or mp3.stat().st_size < 1000:
            await asyncio.wait_for(_edge_communicate(expected, voice).save(str(mp3)), timeout=45)
        audio = decode_audio(str(mp3), sampling_rate=16000)
        sf.write(wav, audio, 16000, subtype="PCM_16")
        assert len(audio) > 16000 and mp3.stat().st_size > 1000
        fixtures.append({"id": sample_id, "category": category, "expected": expected, "voice": voice, "audio": str(wav.relative_to(OUT)), "seconds": len(audio) / 16000, "sha256": sha(wav), "source_mp3_sha256": sha(mp3), "prepare_seconds": time.perf_counter() - start, "expected_zh_anchors": zh_anchors, "expected_en_anchors": en_anchors, "provenance": {"type": "independently authored question; single unspliced product-adapter TTS request", "text_copyright": "Copyright (c) 2026 HongXian0903", "text_spdx": "Apache-2.0", "adapter": "src.tts.engines.edge._edge_communicate(...).save", "human_speech": False, "independent_listening_completed": False}})
        print(f"PREPARED {sample_id} {voice} {len(audio) / 16000:.2f}s", flush=True)
    result = {"copyright": "Copyright (c) 2026 HongXian0903", "SPDX-License-Identifier": "Apache-2.0", "scope": "research metadata and independently authored text only; not a license grant for Microsoft voices/audio", "voice_support_source": "https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/speech-synthesis-markup-voice", "mixed_voice": "en-US-EmmaMultilingualNeural", "mixed_voice_support": "Microsoft lists English, Mandarin Chinese and Taiwanese Chinese support for this named multilingual voice; actual Edge availability confirmed by successful nonempty MP3 synthesis", "spoken_content_verification": "No listening/transcription tool available for independent human listening. Use documented multilingual voice plus both ASR candidates' Chinese/English anchor retention as a bounded cross-check; ASR agreement is not independent phonetic ground truth.", "edge_adapter_sha256": sha(ROOT / "src/tts/engines/edge.py"), "edge_connection_sha256": sha(ROOT / "src/tts/edge_connection.py"), "actual_endpoint_host": transport.WSS_URL.split('/')[2], "fixtures": fixtures}
    (OUT / "product-audio-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Generated {len(fixtures)} questions, {sum(f['seconds'] for f in fixtures):.2f}s", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
