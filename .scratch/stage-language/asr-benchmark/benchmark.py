# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Small sequential local ASR comparison; no app imports/configuration writes."""

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import resource
import statistics
import subprocess
import sys
import threading
import time
import traceback
import unicodedata

import psutil

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except Exception as exc:
        return {"error": repr(exc)}


def snapshot():
    versions = {}
    for package in ["faster-whisper", "ctranslate2", "torch", "transformers", "huggingface-hub", "edge-tts", "av", "soundfile", "opencc", "psutil"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    processes = []
    for process in psutil.process_iter(["pid", "name", "memory_info", "create_time", "cpu_times", "cmdline"]):
        try:
            item = process.info
            args = item.pop("cmdline") or []
            item["executable"] = args[0] if args else None
            item["python_entrypoint"] = next((a for a in args[1:3] if a.endswith(".py")), None)
            item["rss"] = item.pop("memory_info").rss
            item["cpu_times"] = list(item["cpu_times"])
            processes.append(item)
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue
    config_hashes = {}
    for path in [ROOT / "config.yaml", ROOT / "config/runtime_overrides.yaml", ROOT / "config/config.yaml"]:
        if path.is_file():
            config_hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"time_utc": timestamp(), "platform": platform.platform(), "machine": platform.machine(), "python": sys.version, "versions": versions, "memory": psutil.virtual_memory()._asdict(), "loadavg": list(os.getloadavg()), "nvpmodel_query": command(["nvpmodel", "-q"]), "nvidia_smi": command(["nvidia-smi"]), "listeners": command(["ss", "-ltnp"]), "tegra_release": Path("/etc/nv_tegra_release").read_text(), "config_sha256_readonly": config_hashes, "processes": sorted(processes, key=lambda x: x["rss"], reverse=True), "gpu_memory_note": "nvidia-smi does not provide per-process GPU memory on this Orin. CUDA-visible used memory is device-global shared memory and cannot be added to RSS as separate physical RAM."}


class MemoryMonitor:
    def __init__(self):
        self.proc = psutil.Process()
        self.samples = []
        self.stop_event = threading.Event()
        try:
            self.cuda = ctypes.CDLL("libcudart.so.13")
            self.cuda.cudaMemGetInfo.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
            self.cuda.cudaMemGetInfo.restype = ctypes.c_int
        except OSError:
            self.cuda = None

    def sample(self):
        item = {"monotonic": time.perf_counter(), "rss_bytes": self.proc.memory_info().rss, "system_available_bytes": psutil.virtual_memory().available}
        if self.cuda:
            free, total = ctypes.c_size_t(), ctypes.c_size_t()
            result = self.cuda.cudaMemGetInfo(ctypes.byref(free), ctypes.byref(total))
            item["cuda_mem_get_info_status"] = result
            if result == 0:
                item.update(cuda_free_bytes=free.value, cuda_total_bytes=total.value, cuda_global_used_bytes=total.value - free.value)
        self.samples.append(item)
        return item

    def start(self):
        self.sample()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self):
        while not self.stop_event.wait(0.1):
            self.sample()

    def stop(self):
        self.stop_event.set()
        self.thread.join()
        self.sample()
        return {"sampling_seconds": 0.1, "peak_process_rss_bytes": max(x["rss_bytes"] for x in self.samples), "min_system_available_bytes": min(x["system_available_bytes"] for x in self.samples), "max_cuda_global_used_bytes": max((x.get("cuda_global_used_bytes", 0) for x in self.samples), default=0), "process_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024, "samples": self.samples}


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, token in enumerate(reference, 1):
        current = [i]
        for j, actual in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (token != actual)))
        previous = current
    return previous[-1]


def normalized(text, traditional=True):
    text = unicodedata.normalize("NFKC", text).casefold()
    if traditional:
        from opencc import OpenCC
        text = OpenCC("s2t").convert(text)
    return "".join(c for c in text if c.isalnum())


def errors(reference, hypothesis, category):
    expected, actual = normalized(reference), normalized(hypothesis)
    value = {"normalized_expected": expected, "normalized_actual": actual, "cer_edits": distance(expected, actual), "cer_reference_characters": len(expected), "cer": distance(expected, actual) / max(1, len(expected)), "raw_script_cer": distance(normalized(reference, False), normalized(hypothesis, False)) / max(1, len(normalized(reference, False)))}
    if category == "en":
        ref_words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", reference.casefold())
        hyp_words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", hypothesis.casefold())
        value.update(wer_edits=distance(ref_words, hyp_words), wer_reference_words=len(ref_words), wer=distance(ref_words, hyp_words) / max(1, len(ref_words)))
    return value


def worker(label, device="cuda", compute="float16", fallback_probe=False):
    from faster_whisper import WhisperModel
    import ctranslate2
    fixtures = json.loads((OUT / "audio-manifest.json").read_text())["fixtures"]
    result = {"model": label, "device": device, "requested_compute_type": compute, "started_utc": timestamp(), "cold_definition": "new worker/model process; OS filesystem caches not flushed; imports and CUDA memory-probe context initialization precede the load timer; first decode includes lazy decode/kernel initialization", "parameters": {"language": None, "task": "transcribe", "beam_size": 5, "vad_filter": False, "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "condition_on_previous_text": True, "cpu_threads": 4, "num_workers": 1}, "ct2_supported_compute_types": sorted(ctranslate2.get_supported_compute_types(device)), "runs": []}
    monitor = MemoryMonitor()
    monitor.start()
    result["memory_before_load"] = monitor.sample()
    model = None
    try:
        started = time.perf_counter()
        model = WhisperModel(str(ROOT / "models" / f"whisper-{label}"), device=device, compute_type=compute, cpu_threads=4, num_workers=1, local_files_only=True)
        result["model_load_seconds"] = time.perf_counter() - started
        result["actual_compute_type"] = model.model.compute_type
        result["memory_after_load"] = monitor.sample()
        plan = [("cold_first_decode", 0, fixtures[0])]
        if not fallback_probe:
            plan.extend(("warm", repeat, fixture) for repeat in [1, 2] for fixture in fixtures)
        for phase, repeat, fixture in plan:
            before = monitor.sample()
            started = time.perf_counter()
            segments, info = model.transcribe(str(OUT / fixture["audio"]), language=None, task="transcribe", beam_size=5, vad_filter=False)
            materialized = list(segments)  # lazy iterator must finish inside timer
            elapsed = time.perf_counter() - started
            text = "".join(s.text for s in materialized).strip()
            run = {"phase": phase, "repeat": repeat, "sample_id": fixture["id"], "category": fixture["category"], "expected": fixture["expected"], "transcript": text, "audio_seconds": fixture["seconds"], "transcribe_seconds": elapsed, "rtf": elapsed / fixture["seconds"], "detected_language": info.language, "language_probability": info.language_probability, "segments": [{"start": s.start, "end": s.end, "text": s.text, "avg_logprob": s.avg_logprob, "temperature": s.temperature} for s in materialized], "metrics": errors(fixture["expected"], text, fixture["category"]), "memory_before": before, "memory_after": monitor.sample()}
            result["runs"].append(run)
            print(f"RESULT {label} {device} {phase}/{repeat} {fixture['id']} {elapsed:.3f}s: {text}", flush=True)
            write_json(OUT / f"results-{label}-{device}.json", result)
        result["status"] = "passed"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        result["native_library_diagnostics"] = command(["ldconfig", "-p"])
        print(f"FAILED {label} {device}: {exc}", flush=True)
    finally:
        result["memory_observations"] = monitor.stop()
        result["completed_utc"] = timestamp()
        write_json(OUT / f"results-{label}-{device}.json", result)
        del model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["small", "large-v3-turbo"])
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute", default="float16")
    parser.add_argument("--fallback-probe", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.device, args.compute, args.fallback_probe)
        return
    write_json(OUT / "environment-before.json", snapshot())
    for label in ["small", "large-v3-turbo"]:
        with (OUT / f"worker-{label}-cuda.log").open("w") as log:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", label], stdout=log, stderr=subprocess.STDOUT)
        result_path = OUT / f"results-{label}-cuda.json"
        if process.returncode or not result_path.exists() or json.loads(result_path.read_text()).get("status") != "passed":
            print(f"CUDA failed for {label}; trying CPU INT8 once", flush=True)
            with (OUT / f"worker-{label}-cpu.log").open("w") as log:
                subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", label, "--device", "cpu", "--compute", "int8", "--fallback-probe"], stdout=log, stderr=subprocess.STDOUT)
        else:
            result = json.loads(result_path.read_text())
            warm = [x["transcribe_seconds"] for x in result["runs"] if x["phase"] == "warm"]
            print(f"COMPLETED {label}: warm median={statistics.median(warm):.3f}s, peak RSS={result['memory_observations']['peak_process_rss_bytes'] / 2**30:.2f}GiB", flush=True)
    write_json(OUT / "environment-after.json", snapshot())
    print("BENCHMARK finished; model worker processes have exited", flush=True)


if __name__ == "__main__":
    main()
