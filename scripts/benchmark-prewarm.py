#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Compare fresh backend processes with prewarm off/on, using identical PCM.

Only scalar telemetry is saved. The synthetic utterance remains in memory;
private startup logs are removed with the temporary directory. Existing
backend or llama-server processes are never stopped by this tool.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

import aiohttp
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_voice_soak import SoakPeer, synthesize_fixture
from src.config.loader import load_config
from src.tts import edge_endpoint


class BenchmarkPeer(SoakPeer):
    def __init__(self, *args, **kwargs):
        self.received = {"audio": 0, "video": 0, "active_audio": 0}
        super().__init__(*args, **kwargs)

    async def _drain(self, track):
        try:
            while True:
                frame = await track.recv()
                self.received[track.kind] += 1
                if track.kind == "audio":
                    samples = frame.to_ndarray()
                    threshold = 0.001 if np.issubdtype(samples.dtype, np.floating) else 32
                    self.received["active_audio"] += int(np.max(np.abs(samples)) > threshold)
        except Exception:
            return


async def health(http, url):
    try:
        async with http.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
            return await response.json() if response.status == 200 else None
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None


async def fixture(voice):
    for attempt in range(4):
        try:
            return await asyncio.wait_for(synthesize_fixture("請用一句話簡短介紹臺灣。", voice), 30)
        except Exception as exc:
            switched = edge_endpoint.note_failure(exc)
            if attempt == 3 or not (switched or edge_endpoint.is_rate_limited(exc)):
                raise RuntimeError(f"fixture unavailable: {type(exc).__name__}") from None
            print(f"Fixture retry {attempt + 1}/3", flush=True)
            await asyncio.sleep(20 if edge_endpoint.is_rate_limited(exc) else 0.1)


async def trial(http, args, base_url, pcm, enabled):
    env = dict(os.environ, NOVA_AVATAR_PREWARM_ENABLED="1" if enabled else "0")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nova-prewarm-") as temporary:
        with open(Path(temporary) / "backend.log", "wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "src.server.app", "--config", args.config],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            peer = None
            try:
                while time.monotonic() - started < 120:
                    if process.poll() is not None:
                        raise RuntimeError(f"backend exited during startup: {process.returncode}")
                    status = await health(http, f"{base_url}/health")
                    if status and status.get("ready") and status.get("model_ready"):
                        break
                    await asyncio.sleep(0.25)
                else:
                    raise TimeoutError("backend did not become ready within 120 seconds")
                startup = time.monotonic() - started
                connecting = time.monotonic()
                peer = BenchmarkPeer(base_url, http, client_role=args.client_role)
                await asyncio.wait_for(peer.connect(), 120)
                connection = time.monotonic() - connecting
                metrics = await asyncio.wait_for(peer.run_turn(pcm, "short"), 90)
                if metrics.get("first_audio_seconds") is None or not peer.received["active_audio"]:
                    raise RuntimeError("trial did not deliver a spoken response")
                return {
                    "enabled": enabled, "startup_seconds": round(startup, 6),
                    "connection_seconds": round(connection, 6),
                    "prewarm": status.get("prewarm"),
                    "metrics": metrics, "received": dict(peer.received),
                }
            finally:
                try:
                    if peer is not None:
                        await peer.close()
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            await asyncio.to_thread(process.wait, timeout=20)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            await asyncio.to_thread(process.wait)
                            raise RuntimeError("backend exceeded its shutdown deadline") from None


def summarize(trials):
    summary = {}
    for enabled, name in ((False, "cold"), (True, "prewarmed")):
        group = [row for row in trials if row["enabled"] is enabled]
        def median(get):
            return round(statistics.median(get(row) for row in group), 6)
        summary[name] = {
            "trials": len(group),
            "startup_seconds": median(lambda row: row["startup_seconds"]),
            "connection_seconds": median(lambda row: row["connection_seconds"]),
            "first_audio_seconds": median(lambda row: row["metrics"]["first_audio_seconds"]),
            "asr_seconds": median(lambda row: row["metrics"]["stage_seconds"]["asr"]),
        }
    baseline = summary["cold"]["first_audio_seconds"]
    warmed = summary["prewarmed"]["first_audio_seconds"]
    summary["first_audio_reduction_seconds"] = round(baseline - warmed, 6)
    summary["first_audio_reduction_percent"] = round(100 * (baseline - warmed) / baseline, 2)
    return summary


async def run(args):
    config = load_config(config_file=args.config)
    if config.llm.provider != "llamacpp" or config.model.type != "musetalk":
        raise RuntimeError("cold comparison requires the local llama.cpp/MuseTalk path")
    protocol = "https" if config.app.ssl or (config.app.ssl_cert and config.app.ssl_key) else "http"
    base_url = args.base_url or f"{protocol}://localhost:{config.app.listenport}"
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as http:
        if await health(http, f"{base_url}/health") is not None:
            raise RuntimeError("backend is already running; cold comparison needs an unused endpoint")
        llm_url = f"http://{config.llm.llamacpp_host}:{config.llm.llamacpp_port}/health"
        if await health(http, llm_url) is not None:
            raise RuntimeError("selected llama-server is already running; its cache would invalidate the comparison")
        pcm = await fixture(args.fixture_voice)
        trials = []
        for repeat in range(args.repeats):
            for enabled in ((False, True) if repeat % 2 == 0 else (True, False)):
                if (await health(http, f"{base_url}/health") is not None
                        or await health(http, llm_url) is not None):
                    raise RuntimeError("a backend or llama-server is still running between trials")
                result = await trial(http, args, base_url, pcm, enabled)
                trials.append(result)
                print(f"trial={len(trials)} role={args.client_role} prewarm={enabled} "
                      f"startup={result['startup_seconds']:.3f}s "
                      f"first_audio={result['metrics']['first_audio_seconds']:.3f}s", flush=True)
                report = {"schema_version": 1, "client_role": args.client_role,
                          "order": "off/on, on/off", "process_cold": True,
                          "environment": {
                              "avatar": config.model.avatar_id,
                              "batch_size": config.model.batch_size,
                              "llm": Path(config.llm.model).name,
                              "stt": config.asr.type, "tts": config.tts.type,
                              "voice": config.tts.ref_file,
                              "background": config.stage.background_id,
                              "max_video_height": config.video.max_height,
                          },
                          "fixture_samples": len(pcm), "trials": trials}
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
    report["summary"] = summarize(trials)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--base-url")
    parser.add_argument("--client-role", choices=("stage", "console"), default="stage")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--fixture-voice", default="zh-TW-HsiaoChenNeural")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
