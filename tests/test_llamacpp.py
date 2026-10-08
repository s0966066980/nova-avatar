import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.llamacpp import (
    build_server_env,
    cuda_library_dirs,
    cuda_free_mb,
    find_llama_server,
    gguf_block_count,
    list_gguf_models,
    resolve_gguf,
    stop_llama_on_port,
    shutdown_llama_server,
    suggest_gpu_layers,
)


class CudaLibraryDiscoveryTests(unittest.TestCase):
    def test_finds_jetson_build_without_path_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / ".local" / "jetson" / "llama.cpp" / "build" / "bin" / "llama-server"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n")
            binary.chmod(0o755)
            with patch("src.llm.llamacpp.shutil.which", return_value=None), patch(
                "src.llm.llamacpp.get_project_root", return_value=root
            ), patch("src.llm.llamacpp.Path.home", return_value=root / "home"):
                self.assertEqual(find_llama_server(), binary)

    def test_server_symlink_resolves_to_cuda_build_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "build" / "llama-server"
            binary.parent.mkdir()
            binary.write_text("#!/bin/sh\n")
            launcher = root / "llama-server"
            launcher.symlink_to(binary)
            with patch("src.llm.llamacpp.shutil.which", return_value=str(launcher)):
                self.assertEqual(find_llama_server(), binary.resolve())

    def test_includes_cuda_13_library_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "libcudart.so.13").write_bytes(b"x")
            self.assertIn(root.resolve(), [path.resolve() for path in cuda_library_dirs([root])])

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


class ModelDiscoveryTests(unittest.TestCase):
    def test_finds_project_model_with_stale_configured_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "llama" / "Qwen3.5-4B-UD-Q4_K_XL.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"GGUF")
            with patch("src.llm.llamacpp.get_project_root", return_value=root), patch(
                "src.llm.llamacpp.Path.home", return_value=root / "home"
            ):
                stale_dir = str(root / "old-llama")
                self.assertEqual(resolve_gguf(model.stem, stale_dir), model)
                self.assertEqual(resolve_gguf(model.name, stale_dir), model)
                self.assertEqual([item["path"] for item in list_gguf_models(stale_dir)], [str(model)])
                self.assertEqual(resolve_gguf(model.stem), model)

    def test_relative_configured_directory_returns_absolute_model_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "llama" / "model.gguf"
            model.parent.mkdir()
            model.write_bytes(b"GGUF")
            with patch("src.llm.llamacpp.get_project_root", return_value=root):
                self.assertEqual(resolve_gguf("model", "./llama"), model.resolve())

    def test_explicit_directory_takes_priority_over_project_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configured = root / "custom" / "model.gguf"
            project = root / "llama" / "model.gguf"
            for model in (configured, project):
                model.parent.mkdir(parents=True)
                model.write_bytes(b"GGUF")
            with patch("src.llm.llamacpp.get_project_root", return_value=root):
                self.assertEqual(resolve_gguf("model", str(configured.parent)), configured)

    def test_project_directory_is_listed_once_when_also_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "llama" / "model.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"GGUF")
            with patch("src.llm.llamacpp.get_project_root", return_value=root), patch(
                "src.llm.llamacpp.Path.home", return_value=root / "home"
            ):
                self.assertEqual(len(list_gguf_models(str(model.parent))), 1)


class GpuLayerPlanningTests(unittest.TestCase):
    def test_jetson_queries_cuda_when_smi_memory_is_unsupported(self):
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(
            is_available=lambda: True,
            mem_get_info=lambda: (12 * 1024**3, 16 * 1024**3),
        ))
        with patch("subprocess.check_output", return_value="[N/A]\n"), patch.dict(
            sys.modules, {"torch": fake_torch}
        ):
            self.assertEqual(cuda_free_mb(), 12288)

    def test_cpu_host_without_smi_returns_zero(self):
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
        with patch("subprocess.check_output", side_effect=FileNotFoundError), patch.dict(
            sys.modules, {"torch": fake_torch}
        ):
            self.assertEqual(cuda_free_mb(), 0)

    def test_fits_all_layers_when_vram_is_enough(self):
        self.assertEqual(suggest_gpu_layers(2 * 1024**3, 12000, 32), 99)

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


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    unittest.main()
