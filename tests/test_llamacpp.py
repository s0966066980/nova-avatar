import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.llamacpp import (
    ALL_GPU_LAYERS,
    build_server_env,
    cuda_library_dirs,
    find_llama_server,
    gguf_block_count,
    resolve_gguf,
    stop_llama_on_port,
    shutdown_llama_server,
    suggest_gpu_layers,
)


class CudaLibraryDiscoveryTests(unittest.TestCase):
    def test_includes_directory_that_has_libcudart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "libcudart.so.12").write_bytes(b"x")
            found = cuda_library_dirs(extra_roots=[root])
            self.assertIn(root.resolve(), [path.resolve() for path in found])

    def test_skips_directory_without_cuda_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "readme.txt").write_text("nope")
            found = cuda_library_dirs(extra_roots=[root])
            self.assertNotIn(root.resolve(), [path.resolve() for path in found])

    def test_build_server_env_puts_cuda_dir_on_ld_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            cuda_dir = Path(tmp) / "cuda"
            bin_dir.mkdir()
            cuda_dir.mkdir()
            (cuda_dir / "libcudart.so.12").write_bytes(b"x")
            binary = bin_dir / "llama-server"
            binary.write_text("#!/bin/sh\n")
            with patch("src.llm.llamacpp.cuda_library_dirs", return_value=[cuda_dir]):
                env = build_server_env(binary)
            parts = env["LD_LIBRARY_PATH"].split(":")
            self.assertEqual(parts[0], str(bin_dir))
            self.assertIn(str(cuda_dir), parts)


class GpuLayerPlanningTests(unittest.TestCase):
    def test_fits_all_layers_when_vram_is_enough(self):
        self.assertEqual(suggest_gpu_layers(2 * 1024**3, 12000, 32), ALL_GPU_LAYERS)

    def test_external_server_offloading_all_layers_uses_the_same_sentinel(self):
        from src.llm.llamacpp import _external_gpu_layers
        with patch("src.llm.llamacpp._pids_listening_on", return_value=[4242]), patch(
                "src.llm.llamacpp._process_cmdline", return_value="llama-server -ngl all"):
            self.assertEqual(_external_gpu_layers(8080), ALL_GPU_LAYERS)

    def test_partial_offload_when_vram_is_tight(self):
        layers = suggest_gpu_layers(16 * 1024**3, 10000, 65)
        self.assertGreater(layers, 0)
        self.assertLess(layers, 65)

    def test_cpu_only_when_no_free_vram(self):
        self.assertEqual(suggest_gpu_layers(16 * 1024**3, 512, 65), 0)

    def test_reads_qwen_block_count(self):
        gguf = resolve_gguf("Qwen3.8-27B-Q4_K_M", extra_dir=str(Path.home() / "llama"))
        if gguf is None:
            self.skipTest("Qwen3.8-27B-Q4_K_M.gguf is not installed")
        self.assertEqual(gguf_block_count(gguf), 65)


class StopLlamaOnPortTests(unittest.TestCase):
    def test_refuses_to_kill_unrelated_process(self):
        with patch("src.llm.llamacpp._pids_listening_on", return_value=[4242]):
            with patch("src.llm.llamacpp._process_cmdline", return_value="python app.py"):
                with self.assertRaises(RuntimeError) as ctx:
                    stop_llama_on_port(8080)
        self.assertIn("其他程式", str(ctx.exception))

    def test_stops_leftover_llama_server(self):
        killed = []

        def fake_kill(pid, sig):
            killed.append((pid, sig))
            if sig == 15:
                raise ProcessLookupError

        with patch("src.llm.llamacpp._pids_listening_on", return_value=[335955]):
            with patch(
                "src.llm.llamacpp._process_cmdline",
                return_value="/home/oliver/llama/llama.cpp/build/bin/llama-server -m LFM.gguf",
            ):
                with patch("src.llm.llamacpp.os.kill", side_effect=fake_kill):
                    stop_llama_on_port(8080)
        self.assertEqual(killed[0][0], 335955)


class ShutdownOwnedServerTests(unittest.TestCase):
    def test_shutdown_stops_only_owned_process_and_is_idempotent(self):
        import src.llm.llamacpp as llamacpp

        class Process:
            def __init__(self):
                self.terminate_count = 0
                self.kill_count = 0

            def poll(self):
                return None if self.terminate_count == 0 else 0

            def terminate(self):
                self.terminate_count += 1

            def wait(self, timeout):
                return 0

            def kill(self):
                self.kill_count += 1

        process = Process()
        with patch.object(llamacpp, "_server_proc", process), patch.object(
            llamacpp, "_loaded_model", "LFM"
        ):
            shutdown_llama_server()
            shutdown_llama_server()

        self.assertEqual(process.terminate_count, 1)
        self.assertEqual(process.kill_count, 0)
        self.assertIsNone(llamacpp._server_proc)
        self.assertEqual(llamacpp._loaded_model, "")

    def test_shutdown_does_not_discover_or_kill_external_server(self):
        import src.llm.llamacpp as llamacpp

        with patch.object(llamacpp, "_server_proc", None), patch.object(
            llamacpp, "stop_llama_on_port"
        ) as stop:
            shutdown_llama_server()

        stop.assert_not_called()


class LlamaServerLaunchEnvTests(unittest.TestCase):
    def test_llama_server_loads_with_discovered_cuda_libs(self):
        binary = find_llama_server()
        if binary is None:
            self.skipTest("llama-server is not installed")
        env = build_server_env(binary)
        result = subprocess.run(
            [str(binary), "-h"],
            env=env,
            cwd=str(binary.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertNotIn("libcudart.so.12", combined)
        self.assertEqual(result.returncode, 0, combined[-500:])


class ModelInfoCacheTests(unittest.TestCase):
    def test_loading_another_model_replaces_the_cached_context_size(self):
        import src.llm.llamacpp as llamacpp
        from src.llm import context_usage

        sizes = iter([4096, 8192])

        class Props:
            def __init__(self):
                self.value = next(sizes)

            def raise_for_status(self):
                pass

            def json(self):
                return {"default_generation_settings": {"n_ctx": self.value}}

        url = llamacpp.openai_base_url("127.0.0.1", 18080)
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            context_usage.requests, "get", side_effect=lambda *_, **__: Props()
        ) as get, patch.object(llamacpp, "server_status", return_value={"running": False}), patch.object(
            llamacpp, "_stop_owned_server"
        ), patch.object(llamacpp, "find_llama_server", return_value=Path(tmp) / "llama-server"), patch.object(
            llamacpp, "build_server_env", return_value={}
        ), patch.object(llamacpp, "has_cuda_backend", return_value=False), patch.object(
            llamacpp, "get_project_root", return_value=Path(tmp)
        ), patch.object(llamacpp.subprocess, "Popen"), patch.object(llamacpp, "_wait_until_ready"):
            for name, size in (("first", 4096), ("second", 8192)):
                (Path(tmp) / f"{name}.gguf").write_bytes(b"GGUF")
                # GPU placement is not under test; accept the CPU-only fake.
                self.assertEqual(llamacpp.ensure_server(
                    name, extra_dir=tmp, port=18080, allow_partial_offload=True), url)
                calls = get.call_count
                # The answer path reads the cache; it never asks /props itself.
                self.assertEqual(context_usage.cached_capacity(url), size)
                self.assertEqual(get.call_count, calls)


def _write_gguf(path: Path, block_count: int, size_bytes: int) -> Path:
    """A minimal GGUF header with *.block_count, sparse-padded to size_bytes."""
    key = b"llama.block_count"
    header = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, 1)
    header += struct.pack("<Q", len(key)) + key + struct.pack("<I", 4) + struct.pack("<I", block_count)
    path.write_bytes(header)
    os.truncate(path, size_bytes)
    return path


class FakeLlamaProcess:
    def __init__(self, cmd, stdout=None, **_kwargs):
        self.cmd = cmd
        self.returncode = None
        if stdout is not None and FakeLlamaProcess.log_text:
            stdout.write(FakeLlamaProcess.log_text.encode())
            stdout.flush()

    log_text = ""

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.returncode = -9


class FullGpuStartupTests(unittest.TestCase):
    """ensure_server must run every layer on the GPU unless partial offload is allowed."""

    def setUp(self):
        import src.llm.llamacpp as llamacpp

        self.llamacpp = llamacpp
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        self.binary = bin_dir / "llama-server"
        self.binary.write_text("#!/bin/sh\n")
        (bin_dir / "libggml-cuda.so").write_bytes(b"x")
        # 32 layers, 5 GiB: needs 5120 MiB + 2048 MiB reserve on the GPU.
        self.model = _write_gguf(root / "Test-9B.gguf", 32, 5 * 1024**3)
        self.launched = []
        self.running = False
        FakeLlamaProcess.log_text = ""

        def popen(cmd, **kwargs):
            self.launched.append(cmd)
            self.running = True
            return FakeLlamaProcess(cmd, **kwargs)

        def status(host="127.0.0.1", port=8080):
            return {"running": self.running, "owned": False, "loaded_model": "",
                    "base_url": f"http://{host}:{port}/v1", "binary": ""}

        patches = [
            patch.object(llamacpp, "_server_proc", None),
            patch.object(llamacpp, "_loaded_model", ""),
            patch.object(llamacpp, "_gpu_offload", None),
            patch.object(llamacpp, "get_project_root", return_value=root),
            patch.object(llamacpp, "find_llama_server", return_value=self.binary),
            patch.object(llamacpp, "server_status", side_effect=status),
            patch.object(llamacpp, "cuda_library_dirs", return_value=[]),
            patch.object(llamacpp.subprocess, "Popen", side_effect=popen),
            patch.object(llamacpp, "gpu_processes", return_value=[
                (4242, "/home/oliver/nova-avatar/.venv/bin/python3", 10738),
                (90297, "/usr/local/bin/ollama", 1628),
            ]),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.tmp.cleanup)

    def _ngl(self, cmd):
        return int(cmd[cmd.index("-ngl") + 1]) if "-ngl" in cmd else 0

    def test_refuses_partial_offload_and_names_vram_need_and_holders(self):
        with patch.object(self.llamacpp, "cuda_free_mb", return_value=4000):
            with self.assertRaises(self.llamacpp.GpuOffloadError) as ctx:
                self.llamacpp.ensure_server(str(self.model), port=18080)
        message = str(ctx.exception)
        self.assertEqual(self.launched, [])
        self.assertIn("7168 MiB", message)
        self.assertIn("4000 MiB", message)
        self.assertIn("ollama", message)
        self.assertIn("10738 MiB", message)
        self.assertIn("llamacpp_allow_partial_offload", message)
        self.assertEqual(self.llamacpp.gpu_offload_status()["full"], False)

    def test_full_gpu_launch_uses_all_layers(self):
        with patch.object(self.llamacpp, "cuda_free_mb", return_value=20000):
            self.llamacpp.ensure_server(str(self.model), port=18080)
        self.assertEqual(self._ngl(self.launched[-1]), ALL_GPU_LAYERS)
        self.assertEqual(self.llamacpp.gpu_offload_status(),
                         {"full": True, "gpu_layers": 32, "total_layers": 32, "error": ""})

    def test_explicit_partial_offload_launches_and_reports_not_full(self):
        with patch.object(self.llamacpp, "cuda_free_mb", return_value=4000):
            self.llamacpp.ensure_server(str(self.model), port=18080, allow_partial_offload=True)
        ngl = self._ngl(self.launched[-1])
        self.assertGreater(ngl, 0)
        self.assertLess(ngl, 32)
        status = self.llamacpp.gpu_offload_status()
        self.assertEqual((status["full"], status["gpu_layers"], status["total_layers"]),
                         (False, ngl, 32))

    def test_server_that_finds_no_usable_gpu_is_stopped(self):
        FakeLlamaProcess.log_text = (
            "warning: no usable GPU found, --gpu-layers option will be ignored\n"
        )
        with patch.object(self.llamacpp, "cuda_free_mb", return_value=20000):
            with self.assertRaises(self.llamacpp.GpuOffloadError) as ctx:
                self.llamacpp.ensure_server(str(self.model), port=18080)
        self.assertIn("no usable GPU found", str(ctx.exception))
        self.assertIsNone(self.llamacpp._server_proc)
        self.assertEqual(self.llamacpp.gpu_offload_status()["full"], False)

    def test_gemma_e2b_launches_without_thinking_and_with_its_vision_projector(self):
        root = Path(self.tmp.name)
        model = _write_gguf(root / "gemma-4-E2B_q4_0-it.gguf", 35, 3 * 1024**3)
        projector = root / "gemma-4-E2B-it-mmproj.gguf"
        projector.write_bytes(b"GGUF")
        with patch.object(self.llamacpp, "cuda_free_mb", return_value=20000):
            self.llamacpp.ensure_server(str(model), port=18080)
        cmd = self.launched[-1]
        self.assertEqual(cmd[cmd.index("--reasoning") + 1], "off")
        self.assertEqual(cmd[cmd.index("--reasoning-budget") + 1], "0")
        self.assertEqual(cmd[cmd.index("--mmproj") + 1], str(projector))
        self.assertEqual(self._ngl(cmd), ALL_GPU_LAYERS)

    def test_each_launch_is_marked_in_the_shared_log(self):
        with patch.object(self.llamacpp, "cuda_free_mb", return_value=20000):
            self.llamacpp.ensure_server(str(self.model), port=18080)
        log = (Path(self.tmp.name) / "logs" / "llama-server.log").read_text()
        self.assertIn("nova-avatar 啟動 llama-server", log)
        self.assertIn(f"-ngl {ALL_GPU_LAYERS}", log)

    def test_cpu_only_build_is_refused_by_default(self):
        (self.binary.parent / "libggml-cuda.so").unlink()
        with self.assertRaises(self.llamacpp.GpuOffloadError):
            self.llamacpp.ensure_server(str(self.model), port=18080)
        self.assertEqual(self.launched, [])


class StartupOrderTests(unittest.TestCase):
    """llama-server claims its VRAM before the avatar model loads."""

    def _run_startup(self, ensure_server):
        from src.config.schema import Config
        from src.server import app
        from src.server.state import state

        config = Config()
        config.llm.provider = "llamacpp"
        config.llm.model = "Test-9B"
        config.model.type = "musetalk"
        config.model.avatar_id = "demo"
        calls = []

        def ensure(*args, **kwargs):
            calls.append(("llm", kwargs.get("allow_partial_offload")))
            return ensure_server(*args, **kwargs)

        def prepare(_config):
            calls.append(("avatar", None))
            return object(), object()

        previous = (state.config, state.model, state.avatar, state.model_ready)
        try:
            state.config = config
            with patch("src.llm.llamacpp.ensure_server", side_effect=ensure), \
                    patch.object(app, "prepare_avatar_model", side_effect=prepare), \
                    patch("src.avatars.catalog.avatar_bootable", return_value=(True, "")):
                app._load_startup_models()
            return calls, state.model_ready
        finally:
            state.config, state.model, state.avatar, state.model_ready = previous

    def test_llama_server_starts_before_the_avatar_model(self):
        calls, model_ready = self._run_startup(lambda *a, **k: "http://127.0.0.1:8080/v1")
        self.assertEqual(calls, [("llm", False), ("avatar", None)])
        self.assertTrue(model_ready)

    def test_gpu_shortfall_keeps_the_console_reachable(self):
        from src.llm.llamacpp import GpuOffloadError

        def refuse(*_args, **_kwargs):
            raise GpuOffloadError("顯存不足")

        with self.assertLogs("src.utils.logging", level="ERROR"):
            calls, model_ready = self._run_startup(refuse)
        self.assertEqual(calls, [("llm", False), ("avatar", None)])
        self.assertTrue(model_ready)


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    unittest.main()
