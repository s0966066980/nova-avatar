import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.asr import factory
from src.asr.engines.funasr import (
    REQUIRED_MODEL_FILES,
    convert_funasr_text,
    resolve_funasr_model,
)


class FunASRLocalModelTests(unittest.TestCase):
    def test_converts_simplified_output_to_taiwan_traditional(self):
        self.assertEqual(
            convert_funasr_text("软件和鼠标", "traditional-tw"),
            "軟體和滑鼠",
        )

    def test_can_keep_original_simplified_output(self):
        self.assertEqual(
            convert_funasr_text("软件和鼠标", "simplified"),
            "软件和鼠标",
        )

    def test_factory_forwards_selected_model_to_funasr(self):
        engine = factory.create_asr_engine(
            "funasr",
            model_size="/models/paraformer-zh",
        )

        self.assertEqual(engine.model_name, "/models/paraformer-zh")

    def test_paraformer_alias_prefers_complete_local_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            for filename in REQUIRED_MODEL_FILES:
                (model_dir / filename).write_bytes(b"model")

            with patch("src.asr.engines.funasr.LOCAL_MODEL_DIR", model_dir):
                self.assertEqual(resolve_funasr_model("paraformer-zh"), str(model_dir))

    def test_paraformer_alias_falls_back_when_local_model_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.asr.engines.funasr.LOCAL_MODEL_DIR", Path(tmp)):
                self.assertEqual(resolve_funasr_model("paraformer-zh"), "paraformer-zh")

    def test_model_load_disables_network_update_check(self):
        from src.asr.engines.funasr import FunASR

        auto_model = Mock(return_value=object())
        with patch("funasr.AutoModel", auto_model):
            engine = FunASR(
                config=SimpleNamespace(asr=SimpleNamespace(device="cpu")),
                model_name="/models/paraformer-zh",
            )
            engine.ensure_ready()

        auto_model.assert_called_once_with(
            model="/models/paraformer-zh",
            disable_update=True,
            device="cpu",
        )

    def test_auto_device_resolves_to_available_backend(self):
        from src.asr.engines.funasr import FunASR

        with patch("src.asr.engines.funasr.torch.cuda.is_available", return_value=False):
            engine = FunASR(
                config=SimpleNamespace(asr=SimpleNamespace(device="auto")),
                model_name="/models/paraformer-zh",
            )

        self.assertEqual(engine.device, "cpu")


# ------------------------------------------------- Fun-ASR-Nano-2512 weights


def test_fun_asr_nano_download_is_pinned_and_complete():
    from scripts import fun_asr_nano_weights

    (source,) = fun_asr_nano_weights.MODELS
    assert source.repo == "FunAudioLLM/Fun-ASR-Nano-2512"
    assert len(source.revision) == 40 and int(source.revision, 16) >= 0
    assert all(len(digest) == 64 and int(digest, 16) >= 0 for digest in source.files.values())
    # Everything funasr's FunASRNano loader reads from a local model folder.
    assert {
        "config.yaml", "configuration.json", "model.pt", "multilingual.tiktoken",
        "Qwen3-0.6B/config.json", "Qwen3-0.6B/tokenizer.json", "Qwen3-0.6B/tokenizer_config.json",
        "Qwen3-0.6B/vocab.json", "Qwen3-0.6B/merges.txt",
    } <= set(source.files)
    # No model code is fetched: the model class comes from the pinned funasr package.
    assert not any(name.endswith(".py") for name in source.files)


def test_fun_asr_nano_download_passes_pinned_revision_and_files(tmp_path):
    from scripts import fun_asr_nano_weights

    calls = []
    fun_asr_nano_weights.download(tmp_path, snapshot=lambda repo, **kwargs: calls.append((repo, kwargs)))
    (source,) = fun_asr_nano_weights.MODELS
    assert calls == [(source.repo, {
        "revision": source.revision,
        "local_dir": str(tmp_path / source.local_dir),
        "allow_patterns": sorted(source.files),
    })]


def test_fun_asr_nano_check_fails_when_weights_are_missing(tmp_path):
    from scripts import fun_asr_nano_weights

    with pytest.raises(SystemExit, match=r"model\.pt \(missing\)"):
        fun_asr_nano_weights.main(["--check", "--root", str(tmp_path)])


if __name__ == "__main__":
    unittest.main()
