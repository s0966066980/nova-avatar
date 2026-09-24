import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.avatars.builder import build_character
from src.avatars.mouth_quality import (
    QualityError,
    enhance_generated_mouth,
    enhance_from_config,
    normalize_quality,
    quality_from_model,
)
from src.config.schema import Config
from src.server.import_jobs import start_import_job
from src.server.runtime_settings import (
    SettingsError,
    apply_mouth_quality,
    current_snapshot,
)


def _high_contrast_mouth(size: int = 256) -> np.ndarray:
    image = np.full((size, size, 3), 90, dtype=np.uint8)
    image[140:190, 70:186] = (20, 20, 220)
    image[155:175, 110:146] = (240, 240, 240)
    return image


def _detail_score(image: np.ndarray) -> float:
    return float(np.var(image.astype(np.float32)))


class MouthEnhanceTests(unittest.TestCase):
    def test_lanczos_plus_sharpen_keeps_more_detail_than_linear(self):
        source = _high_contrast_mouth()
        target = (512, 512)
        linear = enhance_generated_mouth(
            source, target, interpolation="linear", sharpen=0.0
        )
        enhanced = enhance_generated_mouth(
            source, target, interpolation="lanczos", sharpen=0.5
        )
        self.assertEqual(enhanced.shape, (512, 512, 3))
        self.assertGreater(_detail_score(enhanced), _detail_score(linear))

    def test_zero_sharpen_leaves_resized_pixels_unchanged_from_resize_only(self):
        source = _high_contrast_mouth()
        plain = enhance_generated_mouth(
            source, (320, 320), interpolation="lanczos", sharpen=0.0
        )
        also_plain = enhance_generated_mouth(
            source, (320, 320), interpolation="lanczos", sharpen=0.0
        )
        np.testing.assert_array_equal(plain, also_plain)

    def test_enhance_from_config_reads_live_model_fields(self):
        source = _high_contrast_mouth()
        config = Config()
        config.model.paste_interpolation = "linear"
        config.model.mouth_sharpen = 0.0
        dull = enhance_from_config(source, (400, 400), config)
        config.model.paste_interpolation = "lanczos"
        config.model.mouth_sharpen = 0.8
        sharp = enhance_from_config(source, (400, 400), config)
        self.assertGreater(_detail_score(sharp), _detail_score(dull))


class QualityNormalizeTests(unittest.TestCase):
    def test_defaults_match_product_values(self):
        quality = normalize_quality({})
        self.assertEqual(quality["paste_interpolation"], "lanczos")
        self.assertEqual(quality["mouth_sharpen"], 0.5)
        self.assertEqual(quality["musetalk"]["bbox_shift"], 0)
        self.assertEqual(quality["musetalk"]["extra_margin"], 10)
        self.assertEqual(quality["musetalk"]["parsing_mode"], "jaw")
        self.assertEqual(quality["musetalk"]["mask_blur_ratio"], 0.05)
        self.assertTrue(quality["musetalk"]["mouth_continuity_idle_alignment"])
        self.assertTrue(quality["musetalk"]["settling_enabled"])
        self.assertEqual(quality["musetalk"]["settling_frames"], 12)
        self.assertEqual(quality["wav2lip"]["pad_bottom"], 10)

    def test_accepts_flat_or_nested_build_fields(self):
        nested = normalize_quality({"musetalk": {"bbox_shift": 7}})
        flat = normalize_quality({"bbox_shift": 7})
        self.assertEqual(nested["musetalk"]["bbox_shift"], 7)
        self.assertEqual(flat["musetalk"]["bbox_shift"], 7)

    def test_rejects_out_of_range_and_unknown_interpolation(self):
        with self.assertRaisesRegex(QualityError, "bbox_shift"):
            normalize_quality({"bbox_shift": 99})
        with self.assertRaisesRegex(QualityError, "插值"):
            normalize_quality({"paste_interpolation": "nearest"})


class QualitySettingsTests(unittest.TestCase):
    def test_snapshot_exposes_mouth_quality(self):
        config = Config()
        config.model.mouth_sharpen = 0.7
        config.model.musetalk.bbox_shift = 5
        with patch(
            "src.server.runtime_settings.list_avatar_characters", return_value=[]
        ), patch("src.server.runtime_settings.list_engines", return_value=[]):
            snapshot = current_snapshot(config)
        self.assertEqual(snapshot["avatar_quality"]["mouth_sharpen"], 0.7)
        self.assertEqual(snapshot["avatar_quality"]["musetalk"]["bbox_shift"], 5)
        self.assertEqual(snapshot["avatar_quality"]["paste_interpolation"], "lanczos")

    def test_apply_mouth_quality_persists_without_disconnect(self):
        config = Config()
        with patch("src.server.runtime_settings.persist_runtime_overrides") as persist:
            result = apply_mouth_quality(
                config,
                {
                    "mouth_sharpen": 0.8,
                    "paste_interpolation": "cubic",
                    "bbox_shift": -4,
                    "extra_margin": 16,
                    "pad_bottom": 14,
                },
            )
        persist.assert_called_once()
        self.assertEqual(config.model.mouth_sharpen, 0.8)
        self.assertEqual(config.model.paste_interpolation, "cubic")
        self.assertEqual(config.model.musetalk.bbox_shift, -4)
        self.assertEqual(config.model.musetalk.extra_margin, 16)
        self.assertEqual(config.model.wav2lip.pad_bottom, 14)
        self.assertEqual(result["mouth_sharpen"], 0.8)

    def test_apply_mouth_quality_rejects_invalid_values(self):
        config = Config()
        with self.assertRaises(SettingsError):
            apply_mouth_quality(config, {"mouth_sharpen": 9})


class BuildQualityForwardingTests(unittest.TestCase):
    def test_build_character_forwards_musetalk_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "face.mp4"
            video.write_bytes(b"not-a-real-video")
            captured = {}

            def fake_build(work_dir, avatar_id, video_path, report, options):
                captured["options"] = options
                captured["avatar_id"] = avatar_id
                captured["video_path"] = video_path
                report(80, "ok")

            with patch("src.avatars.builder.avatars_root", return_value=root / "avatars"), \
                 patch("src.avatars.builder.extract_frames", return_value=4), \
                 patch("src.avatars.builder._build_musetalk", side_effect=fake_build):
                result = build_character(
                    "musetalk",
                    video,
                    "musetalk_sharp",
                    quality={"bbox_shift": 6, "extra_margin": 18},
                    green_screen=True,
                )

            self.assertEqual(result["avatar_id"], "musetalk_sharp")
            self.assertEqual(captured["options"]["musetalk"]["bbox_shift"], 6)
            self.assertEqual(captured["options"]["musetalk"]["extra_margin"], 18)
            self.assertTrue(captured["options"]["green_screen"])
            self.assertEqual(captured["video_path"], "source.mp4")
            self.assertEqual((root / "avatars" / "musetalk_sharp" / "source.mp4").read_bytes(), video.read_bytes())

    def test_import_job_forwards_quality_into_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            video.write_bytes(b"clip")
            seen = {}

            def fake_build(engine, video_path, avatar_id, overwrite=False, progress=None, quality=None, green_screen=False):
                seen["quality"] = quality
                seen["avatar_id"] = avatar_id
                seen["green_screen"] = green_screen
                if progress:
                    progress(100, "done")
                return {"type": engine, "avatar_id": avatar_id, "frames": 1}

            with patch("src.server.import_jobs.build_character", side_effect=fake_build), \
                 patch("src.server.import_jobs._WORKER_LOCK") as lock:
                lock.locked.return_value = False
                lock.acquire.return_value = True
                job = start_import_job(
                    engine="musetalk",
                    video_path=video,
                    original_name="clip.mp4",
                    avatar_id="musetalk_from_ui",
                    quality={"bbox_shift": 3, "mouth_sharpen": 0.6},
                )
                job_thread_done = False
                for _ in range(50):
                    if job.status in {"done", "failed"}:
                        job_thread_done = True
                        break
                    import time
                    time.sleep(0.02)
            self.assertTrue(job_thread_done)
            self.assertEqual(job.status, "done", job.error)
            self.assertEqual(seen["avatar_id"], "musetalk_from_ui")
            self.assertEqual(seen["quality"]["bbox_shift"], 3)
            self.assertFalse(seen["green_screen"])


class QualityFromModelTests(unittest.TestCase):
    def test_missing_nested_fields_use_defaults(self):
        quality = quality_from_model(SimpleNamespace(type="musetalk"))
        self.assertEqual(quality["musetalk"]["parsing_mode"], "jaw")
        self.assertEqual(quality["paste_interpolation"], "lanczos")
