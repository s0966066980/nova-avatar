# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Reuse a documented synthetic fixture and create six independent prompts."""

import asyncio
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

import edge_tts
import edge_tts.communicate
import numpy as np
import soundfile as sf
from faster_whisper.audio import decode_audio

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SAMPLES = [
    ("zh_01", "zh", "zh-TW-HsiaoChenNeural", "請問圖書館星期六幾點開門，我可以在網路上預約座位嗎？"),
    ("zh_02", "zh", "zh-TW-YunJheNeural", "我想知道台北車站附近有沒有無障礙入口，請用簡單的方式說明。"),
    ("en_01", "en", "en-US-JennyNeural", "What time does the library open on Saturday, and can I reserve a seat online?"),
    ("en_02", "en", "en-US-GuyNeural", "Could you explain how to change the language without losing our conversation?"),
    ("mixed_01", "mixed", "zh-TW-HsiaoChenNeural", "請幫我查一下 meeting room 的開放時間，然後用 English 回答。"),
    ("mixed_02", "mixed", "en-US-JennyNeural", "Can you switch to 中文 and explain how to book a meeting room?"),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def official_fallback():
    audio_dir = OUT / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    fixtures = []

    def add(sample_id, category, expected, audio, provenance):
        wav = audio_dir / f"{sample_id}.wav"
        sf.write(wav, audio, 16000, subtype="PCM_16")
        fixtures.append({"id": sample_id, "category": category, "expected": expected, "audio": str(wav.relative_to(OUT)), "seconds": len(audio) / 16000, "sha256": sha(wav), "provenance": provenance})
        return fixtures[-1]

    sources = [
        ("zh_fixture_01", ".scratch/recording-stutter/audio-source.wav", ".scratch/recording-stutter/audio-after.json"),
        ("zh_fixture_02", ".scratch/recording-stutter/audio-final-chat-source.wav", ".scratch/recording-stutter/audio-final-chat.json"),
    ]
    for sample_id, source_rel, metadata_rel in sources:
        metadata = json.loads((ROOT / metadata_rel).read_text())
        expected = metadata.get("played_text") or next(event["played_text"] for event in metadata["events"] if event.get("type") == "turn_committed")
        source = ROOT / source_rel
        add(sample_id, "zh", expected, decode_audio(str(source), sampling_rate=16000), {"type": "existing synthetic Edge playback source; not a microphone capture", "source_audio": source_rel, "source_audio_sha256": sha(source), "transcript_evidence": metadata_rel, "human_accent_validation": False})

    revision = "86098128c0b4f24f0e2aa2994de830614b474227"
    url = f"https://raw.githubusercontent.com/openai/whisper/{revision}/tests/jfk.flac"
    jfk = audio_dir / "openai-jfk.flac"
    with urllib.request.urlopen(url, timeout=30) as response:
        jfk.write_bytes(response.read())
    add("en_openai_jfk", "en", "And so, my fellow Americans, ask not what your country can do for you, ask what you can do for your country.", decode_audio(str(jfk), sampling_rate=16000), {"type": "official OpenAI Whisper test fixture; historical public speech, not modern conversation validation", "repo": "openai/whisper", "revision": revision, "source_url": url, "source_audio_sha256": sha(jfk), "transcript_note": "predeclared familiar speech wording, not generated from benchmark hypotheses"})

    rows_url = "https://datasets-server.huggingface.co/rows?dataset=hf-internal-testing/librispeech_asr_dummy&config=clean&split=validation&offset=0&length=1"
    with urllib.request.urlopen(rows_url, timeout=30) as response:
        data = json.load(response)
    row = data["rows"][0]["row"]
    asset_url = row["audio"][0]["src"]
    assert "/5be91486e11a2d616f4ec5db8d3fd248585ac07a/" in asset_url
    libri = audio_dir / "hf-librispeech-1272-128104-0000.flac"
    with urllib.request.urlopen(asset_url, timeout=30) as response:
        libri.write_bytes(response.read())
    # Persist canonical provenance, not an expiring signed URL.
    row["audio"][0]["src"] = asset_url.split("?")[0]
    (OUT / "official-english-row.json").write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
    add("en_hf_librispeech", "en", row["text"], decode_audio(str(libri), sampling_rate=16000), {"type": "official Hugging Face public ASR test fixture", "repo": "hf-internal-testing/librispeech_asr_dummy", "revision": "5be91486e11a2d616f4ec5db8d3fd248585ac07a", "sample_id": row["id"], "rows_api": rows_url, "source_audio_url": asset_url.split("?")[0], "source_audio_sha256": sha(libri), "original_corpus": "LibriSpeech dev-clean, derived from public LibriVox readings; corpus CC-BY-4.0", "corpus_license_url": "https://www.openslr.org/12"})

    # Dependent stress probes; explicitly not natural within-sentence code-switching.
    for sample_id, first, second in [("mixed_splice_zh_en", fixtures[0], fixtures[2]), ("mixed_splice_en_zh", fixtures[3], fixtures[0])]:
        audio = np.concatenate([decode_audio(str(OUT / first["audio"]), sampling_rate=16000), np.zeros(5600, dtype=np.float32), decode_audio(str(OUT / second["audio"]), sampling_rate=16000)])
        add(sample_id, "mixed", first["expected"] + " " + second["expected"], audio, {"type": "constructed cross-language splice", "components": [first["id"], second["id"]], "gap_seconds": 0.35, "independent_sample": False, "human_code_switching_validation": False})
    write = {"mode": "official_fallback_after_edge_403", "fixture_search": "Found Chinese synthetic playback source WAVs and saved exact synthesis text under .scratch; no verified English/mixed fixtures found in bounded search.", "edge_failure": {"installed": "edge-tts 7.2.8", "baseline": "HTTP 403 websocket handshake with SEC_MS_GEC_VERSION=1-143.0.3650.75", "one_process_probe": "HTTP 403 also with protocol version 2 matching official edge-tts master bd44c1d; package/config untouched", "cause": "unresolved server rejection; protocol version change alone did not resolve"}, "limitations": ["only four distinct underlying recordings", "two Chinese sources are clean synthetic speech; not human-accent validation", "English fixtures are familiar public test content and not independent held-out evaluation", "mixed fixtures concatenate utterances and do not validate natural within-sentence code-switching", "reference text normalization is approximate; not a broad quality ranking"], "fixtures": fixtures}
    (OUT / "audio-manifest.json").write_text(json.dumps(write, ensure_ascii=False, indent=2) + "\n")
    print(f"Prepared official fallback: {len(fixtures)} fixtures / {sum(x['seconds'] for x in fixtures):.2f}s", flush=True)


async def main():
    audio_dir = OUT / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    fixtures = []
    # One-process compatibility probe, matching official edge-tts master at
    # bd44c1d1aaebdc1db7f47456ee12431b42ec7cac; installed package is untouched.
    edge_tts.communicate.SEC_MS_GEC_VERSION = "2-143.0.3650.75"
    # This is generated playback text, not a private microphone recording.
    original = ROOT / ".scratch/recording-stutter/audio-source.wav"
    probe = ROOT / ".scratch/recording-stutter/audio-after.json"
    metadata = json.loads(probe.read_text())
    expected = next(event["played_text"] for event in metadata["events"] if event.get("type") == "turn_committed")
    assert expected == "今天的測試會先確認聲音是否連續。接著比較嘴型推理造成的等待。最後記錄整段語音的播放時間。"
    copied = audio_dir / "existing_zh.wav"
    samples = decode_audio(str(original), sampling_rate=16000)
    sf.write(copied, samples, 16000, subtype="PCM_16")
    fixtures.append({"id": "existing_zh", "category": "zh", "expected": expected, "audio": str(copied.relative_to(OUT)), "seconds": len(samples) / 16000, "sha256": sha(copied), "provenance": {"type": "existing synthetic Edge playback fixture", "source_audio": str(original.relative_to(ROOT)), "source_audio_sha256": sha(original), "transcript_evidence": str(probe.relative_to(ROOT)), "voice": "not independently reverified for original fixture"}})
    for sample_id, category, voice, text in SAMPLES:
        mp3 = audio_dir / f"{sample_id}.mp3"
        wav = audio_dir / f"{sample_id}.wav"
        if not mp3.exists() or mp3.stat().st_size < 1000:
            print(f"SYNTHESIZE {sample_id}: {voice}", flush=True)
            await edge_tts.Communicate(text, voice, rate="+0%", volume="+0%", pitch="+0Hz").save(str(mp3))
        audio = decode_audio(str(mp3), sampling_rate=16000)
        sf.write(wav, audio, 16000, subtype="PCM_16")
        fixtures.append({"id": sample_id, "category": category, "expected": text, "audio": str(wav.relative_to(OUT)), "seconds": len(audio) / 16000, "sha256": sha(wav), "provenance": {"type": "independently authored synthetic Edge TTS", "voice": voice, "rate": "+0%", "source_mp3_sha256": sha(mp3), "generator": "edge-tts 7.2.8; process-local SEC_MS_GEC_VERSION=2-143.0.3650.75 matching upstream bd44c1d", "human_accent_validation": False}})
    (OUT / "audio-manifest.json").write_text(json.dumps({"fixture_search": "Found existing synthetic Chinese playback sources under .scratch; no verified English/mixed fixtures identified in bounded search. Reused one with documented exact transcript and generated six new prompts without accessing live TTS configuration.", "author": "HongXian0903, 2026", "text_spdx": "Apache-2.0", "generated_audio_terms": "Synthetic audio requested through existing Edge TTS; not claimed to be an independently licensed public corpus.", "limitations": ["not human accent validation", "clean synthetic audio only", "mixed script pronunciation depends on chosen voice", "references describe submitted synthesis text; not independently audited phonetic transcriptions"], "fixtures": fixtures}, ensure_ascii=False, indent=2) + "\n")
    print(f"Prepared {len(fixtures)} fixtures / {sum(x['seconds'] for x in fixtures):.2f}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-fallback", action="store_true")
    args = parser.parse_args()
    if args.official_fallback:
        official_fallback()
    else:
        asyncio.run(main())
