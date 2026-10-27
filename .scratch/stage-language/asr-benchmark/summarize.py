# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Summarize recorded observations without rerunning model inference."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

OUT = Path(__file__).resolve().parent


def median(values):
    return statistics.median(values)


def main():
    models = {}
    per_fixture = []
    for label in ["small", "large-v3-turbo"]:
        data = json.loads((OUT / f"results-{label}-cuda.json").read_text())
        assert data["status"] == "passed", label
        warm = [row for row in data["runs"] if row["phase"] == "warm"]
        categories = {}
        for category in ["zh", "en", "mixed"]:
            rows = [row for row in warm if row["category"] == category]
            categories[category] = {
                "warm_median_seconds": median([row["transcribe_seconds"] for row in rows]),
                "weighted_cer": sum(row["metrics"]["cer_edits"] for row in rows) / sum(row["metrics"]["cer_reference_characters"] for row in rows),
                "weighted_wer": sum(row["metrics"].get("wer_edits", 0) for row in rows) / sum(row["metrics"].get("wer_reference_words", 0) for row in rows) if category == "en" else None,
            }
        models[label] = {
            "device": data["device"], "compute_type": data["actual_compute_type"],
            "model_load_seconds": data["model_load_seconds"],
            "cold_first_decode_seconds": data["runs"][0]["transcribe_seconds"],
            "load_plus_first_decode_seconds": data["model_load_seconds"] + data["runs"][0]["transcribe_seconds"],
            "warm_median_seconds": median([row["transcribe_seconds"] for row in warm]),
            "warm_range_seconds": [min(row["transcribe_seconds"] for row in warm), max(row["transcribe_seconds"] for row in warm)],
            "peak_process_rss_gib": data["memory_observations"]["peak_process_rss_bytes"] / 2**30,
            "rss_before_load_gib": data["memory_before_load"]["rss_bytes"] / 2**30,
            "rss_after_load_gib": data["memory_after_load"]["rss_bytes"] / 2**30,
            "min_system_available_gib": data["memory_observations"]["min_system_available_bytes"] / 2**30,
            "cuda_global_before_gib": data["memory_before_load"].get("cuda_global_used_bytes", 0) / 2**30,
            "cuda_global_peak_gib": data["memory_observations"]["max_cuda_global_used_bytes"] / 2**30,
            "categories": categories,
        }
        for sample_id in dict.fromkeys(row["sample_id"] for row in warm):
            rows = [row for row in warm if row["sample_id"] == sample_id]
            first = rows[0]
            per_fixture.append({"model": label, "sample_id": sample_id, "category": first["category"], "audio_seconds": first["audio_seconds"], "warm_median_seconds": median([row["transcribe_seconds"] for row in rows]), "warm_seconds": [row["transcribe_seconds"] for row in rows], "transcript_stable": len({row["transcript"] for row in rows}) == 1, "expected": first["expected"], "transcript": first["transcript"], "detected_language": first["detected_language"], "cer": first["metrics"]["cer"], "raw_script_cer": first["metrics"]["raw_script_cer"], "wer": first["metrics"].get("wer")})
    before = json.loads((OUT / "environment-before.json").read_text())
    after = json.loads((OUT / "environment-after.json").read_text())
    before_services = [p for p in before["processes"] if p["name"] in {"java", "llama-server", "mysqld", "silo"} or p["python_entrypoint"] in {"api/ragflow_server.py", "rag/svr/task_executor.py", "admin/server/admin_server.py", "rag/svr/sync_data_source.py"}]
    after_ids = {(p["pid"], p["create_time"]) for p in after["processes"]}
    service_state = [{"pid": p["pid"], "name": p["name"], "entrypoint": p["python_entrypoint"], "present_before_and_after": (p["pid"], p["create_time"]) in after_ids} for p in before_services]
    app_candidates = [p for p in before["processes"] if p["python_entrypoint"] and Path(p["python_entrypoint"]).name in {"app.py", "main.py", "run_server.py"}]
    summary = {"copyright": "Copyright (c) 2026 HongXian0903", "SPDX-License-Identifier": "Apache-2.0", "scope": "research records only; not a license for model weights or third-party audio", "generated_utc": datetime.now(timezone.utc).isoformat(), "benchmark_started_utc": before["time_utc"], "benchmark_completed_utc": after["time_utc"], "models": models, "per_fixture": per_fixture, "formal_config_hashes_unchanged": before["config_sha256_readonly"] == after["config_sha256_readonly"], "power_query_unchanged": before["nvpmodel_query"]["stdout"] == after["nvpmodel_query"]["stdout"], "background_services": service_state, "avatar_service_present": bool(app_candidates), "avatar_service_detection": "heuristic entrypoint check plus manually reviewed recorded processes/listeners; does not establish rendering activity", "avatar_rendering_load_verified": False, "limitation": "This records background-service coexistence. Full live-avatar shared-load acceptance was not exercised."}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    with (OUT / "transcripts.csv").open("w", newline="") as stream:
        keys = ["model", "sample_id", "category", "audio_seconds", "warm_median_seconds", "detected_language", "cer", "raw_script_cer", "wer", "expected", "transcript", "transcript_stable"]
        writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(per_fixture)
    print(json.dumps(models, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
