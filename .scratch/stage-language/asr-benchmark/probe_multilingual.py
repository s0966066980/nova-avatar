# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""One targeted small-only multilingual=True comparison against saved baseline."""

import inspect
import json
from pathlib import Path
import statistics
import time

from faster_whisper import WhisperModel

from benchmark import OUT, ROOT, MemoryMonitor, errors, snapshot, timestamp, write_json


def main():
    assert inspect.signature(WhisperModel.transcribe).parameters["multilingual"].default is False
    baseline = json.loads((OUT / "results-small-cuda.json").read_text())
    fixtures = json.loads((OUT / "audio-manifest.json").read_text())["fixtures"]
    result = {
        "copyright": "Copyright (c) 2026 HongXian0903",
        "SPDX-License-Identifier": "Apache-2.0",
        "started_utc": timestamp(), "model": "small",
        "local_model_path": str(ROOT / "models/whisper-small"),
        "baseline_file": "results-small-cuda.json",
        "change": "multilingual=False (baseline default) -> True; all other model/transcribe kwargs unchanged",
        "parameters": {**baseline["parameters"], "multilingual": True},
        "baseline_comparison": "Each variant warm measurement is compared with the two saved baseline warm measurements; separate runs, not randomized/interleaved.",
        "environment_before": snapshot(), "runs": [],
    }
    monitor = MemoryMonitor()
    monitor.start()
    model = None
    try:
        started = time.perf_counter()
        model = WhisperModel(str(ROOT / "models/whisper-small"), device="cuda", compute_type="float16", cpu_threads=4, num_workers=1, local_files_only=True)
        result["load_seconds"] = time.perf_counter() - started
        result["actual_compute_type"] = model.model.compute_type

        def decode(fixture):
            started = time.perf_counter()
            segments, info = model.transcribe(str(OUT / fixture["audio"]), language=None, task="transcribe", beam_size=5, vad_filter=False, multilingual=True)
            segments = list(segments)
            elapsed = time.perf_counter() - started
            return "".join(s.text for s in segments).strip(), info, segments, elapsed

        # One unscored first decode warms the new worker, as in the baseline.
        text, info, segments, elapsed = decode(fixtures[0])
        result["unscored_warmup"] = {"sample_id": fixtures[0]["id"], "seconds": elapsed, "transcript": text}
        for fixture in fixtures:
            text, info, segments, elapsed = decode(fixture)
            original = [r for r in baseline["runs"] if r["phase"] == "warm" and r["sample_id"] == fixture["id"]]
            row = {
                "sample_id": fixture["id"], "category": fixture["category"],
                "expected": fixture["expected"], "transcript": text,
                "audio_seconds": fixture["seconds"], "transcribe_seconds": elapsed,
                "rtf": elapsed / fixture["seconds"], "detected_language": info.language,
                "language_probability": info.language_probability,
                "segments": [{"start": s.start, "end": s.end, "text": s.text, "temperature": s.temperature} for s in segments],
                "metrics": errors(fixture["expected"], text, fixture["category"]),
                "baseline_transcript": original[0]["transcript"],
                "baseline_metrics": original[0]["metrics"],
                "baseline_warm_seconds": [r["transcribe_seconds"] for r in original],
                "baseline_warm_median_seconds": statistics.median(r["transcribe_seconds"] for r in original),
                "same_raw_transcript_as_baseline": text == original[0]["transcript"],
            }
            result["runs"].append(row)
            print(f"{fixture['id']} {elapsed:.3f}s baseline={row['baseline_warm_median_seconds']:.3f}s same={row['same_raw_transcript_as_baseline']}: {text}", flush=True)
            write_json(OUT / "variant-small-multilingual-true.json", result)
        result["status"] = "passed"
    except Exception as exc:
        import traceback
        result["status"] = "failed"
        result["error"] = {"message": str(exc), "traceback": traceback.format_exc()}
        raise
    finally:
        result["memory_observations"] = monitor.stop()
        del model
        result["environment_after"] = snapshot()
        result["observed_formal_config_hashes_unchanged"] = result["environment_before"]["config_sha256_readonly"] == result["environment_after"]["config_sha256_readonly"]
        result["power_query_unchanged"] = result["environment_before"]["nvpmodel_query"]["stdout"] == result["environment_after"]["nvpmodel_query"]["stdout"]
        result["completed_utc"] = timestamp()
        write_json(OUT / "variant-small-multilingual-true.json", result)


if __name__ == "__main__":
    main()
