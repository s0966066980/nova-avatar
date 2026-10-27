# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Compare both candidates once on the same eight product-generated questions."""

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.request

from benchmark import OUT, ROOT, MemoryMonitor, errors, normalized, snapshot, timestamp, write_json


def health(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return {"url": url, "status": response.status, "body": response.read(20000).decode(errors="replace")}
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def anchors(text, fixture):
    actual = normalized(text)
    return {"zh": {term: normalized(term) in actual for term in fixture["expected_zh_anchors"]}, "en": {term: normalized(term) in actual for term in fixture["expected_en_anchors"]}}


def worker(label, run_id):
    from faster_whisper import WhisperModel
    fixtures = json.loads((OUT / "product-audio-manifest.json").read_text())["fixtures"]
    data = {"copyright": "Copyright (c) 2026 HongXian0903", "SPDX-License-Identifier": "Apache-2.0", "run_id": run_id, "model": label, "local_model_path": str(ROOT / "models" / f"whisper-{label}"), "started_utc": timestamp(), "environment_before": snapshot(), "health_before": [health("http://127.0.0.1:8010/health"), health("http://127.0.0.1:8080/health")], "parameters": {"device": "cuda", "compute_type": "float16", "cpu_threads": 4, "num_workers": 1, "language": None, "task": "transcribe", "beam_size": 5, "vad_filter": False, "multilingual": False}, "runs": [], "timing_note": "one unscored first decode, then one measured warm decode per fixture; separate workers, same fixed corpus; import/CUDA probe time excluded"}
    monitor = MemoryMonitor()
    monitor.start()
    model = None
    try:
        started = time.perf_counter()
        model = WhisperModel(data["local_model_path"], device="cuda", compute_type="float16", cpu_threads=4, num_workers=1, local_files_only=True)
        data["model_load_seconds"] = time.perf_counter() - started
        data["actual_compute_type"] = model.model.compute_type

        def transcribe(fixture):
            started = time.perf_counter()
            segments, info = model.transcribe(str(OUT / fixture["audio"]), language=None, task="transcribe", beam_size=5, vad_filter=False)
            segments = list(segments)
            return "".join(segment.text for segment in segments).strip(), info, segments, time.perf_counter() - started

        text, info, segments, elapsed = transcribe(fixtures[0])
        data["unscored_warmup"] = {"sample_id": fixtures[0]["id"], "transcript": text, "seconds": elapsed}
        for fixture in fixtures:
            text, info, segments, elapsed = transcribe(fixture)
            row = {"sample_id": fixture["id"], "category": fixture["category"], "voice": fixture["voice"], "expected": fixture["expected"], "transcript": text, "audio_seconds": fixture["seconds"], "warm_transcribe_seconds": elapsed, "rtf": elapsed / fixture["seconds"], "detected_language": info.language, "language_probability": info.language_probability, "metrics": errors(fixture["expected"], text, fixture["category"]), "anchors": anchors(text, fixture), "segments": [{"start": s.start, "end": s.end, "text": s.text, "temperature": s.temperature} for s in segments]}
            data["runs"].append(row)
            write_json(OUT / f"{run_id}-{label}.json", data)
            print(f"RESULT {label} {fixture['id']} {elapsed:.3f}s {info.language}: {text}", flush=True)
        data["status"] = "passed"
    except Exception as exc:
        import traceback
        data["status"] = "failed"
        data["error"] = {"message": str(exc), "traceback": traceback.format_exc()}
        raise
    finally:
        data["memory_observations"] = monitor.stop()
        del model
        data["environment_after"] = snapshot()
        data["completed_utc"] = timestamp()
        data["observed_config_hashes_unchanged"] = data["environment_before"]["config_sha256_readonly"] == data["environment_after"]["config_sha256_readonly"]
        data["observed_power_query_unchanged"] = data["environment_before"]["nvpmodel_query"]["stdout"] == data["environment_after"]["nvpmodel_query"]["stdout"]
        write_json(OUT / f"{run_id}-{label}.json", data)


def app_state(environment):
    return [{"pid": p["pid"], "name": p["name"], "entrypoint": p["python_entrypoint"], "create_time": p["create_time"], "rss": p["rss"], "cpu_times": p["cpu_times"]} for p in environment["processes"] if p["python_entrypoint"] == "src/server/app.py" or p["name"] == "llama-server"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["small", "large-v3-turbo"])
    parser.add_argument("--run-id", default="product-corpus")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.run_id)
        return
    results = {}
    for label in ["small", "large-v3-turbo"]:
        with (OUT / f"{args.run_id}-{label}.log").open("w") as log:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", label, "--run-id", args.run_id], stdout=log, stderr=subprocess.STDOUT, check=True)
        results[label] = json.loads((OUT / f"{args.run_id}-{label}.json").read_text())
    keys = ["small", "large-v3-turbo"]
    rows = [{"sample_id": first["sample_id"], "category": first["category"], "expected": first["expected"], **{label: next(r for r in results[label]["runs"] if r["sample_id"] == first["sample_id"]) for label in keys}} for first in results["small"]["runs"]]
    workload_states = {label: {"before": app_state(results[label]["environment_before"]), "after": app_state(results[label]["environment_after"])} for label in keys}
    service_ids = [{(p["pid"], p["create_time"]) for p in workload_states[label][when]} for label in keys for when in ["before", "after"]]
    summary = {"copyright": "Copyright (c) 2026 HongXian0903", "SPDX-License-Identifier": "Apache-2.0", "results": rows, "warm_median_seconds": {label: statistics.median(r["warm_transcribe_seconds"] for r in results[label]["runs"]) for label in keys}, "same_application_and_llama_processes_across_candidates": all(s == service_ids[0] for s in service_ids), "background_workload_states": workload_states, "health_checks": {label: results[label]["health_before"] for label in keys}, "limitation": "App/LLM resident workload differs from earlier fallback corpus. Same resident process identities do not prove identical instantaneous activity or live avatar frame/TTS/LLM-generation stress. Synthetic multilingual voice and ASR anchor agreement do not establish human accent quality.", "config_hashes_same_between_candidates": results["small"]["environment_before"]["config_sha256_readonly"] == results["large-v3-turbo"]["environment_before"]["config_sha256_readonly"]}
    write_json(OUT / f"{args.run_id}-summary.json", summary)
    print(json.dumps({"warm_median_seconds": summary["warm_median_seconds"], "same_background_processes": summary["same_application_and_llama_processes_across_candidates"], "config_same": summary["config_hashes_same_between_candidates"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
