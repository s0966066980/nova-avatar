# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Unit & route tests for console-guided Matcha-TTS voice training workbench."""

from __future__ import annotations

import json
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.server import tts_training_jobs as ttj
from src.server.routes import tts_training as tts_routes
from src.server.runtime_settings import SettingsError
from src.server.state import state


class TtsTrainingJobsTests(unittest.TestCase):
    def setUp(self) -> None:
        ttj._CURRENT_JOB = None
        ttj._ACTIVE_PROC = None
        ttj._CANCEL_EVENT.clear()

    def tearDown(self) -> None:
        ttj._CURRENT_JOB = None
        ttj._ACTIVE_PROC = None
        ttj._CANCEL_EVENT.clear()

    def test_slug_validation_and_traversal_blocked(self) -> None:
        with self.assertRaises(SettingsError):
            ttj.parse_training_config({"slug": "../escape"})
        with self.assertRaises(SettingsError):
            ttj.parse_training_config({"slug": "bad slug!"})
        cfg = ttj.parse_training_config({"slug": "zh-tw-hsiaochen", "teacher": "edgetts"})
        self.assertEqual(cfg.slug, "zh-tw-hsiaochen")

    def test_build_step_commands_for_all_stages(self) -> None:
        tmp = Path("/tmp/nova_test_tts_cmd")
        cfg_edge = ttj.TtsTrainingConfig(
            slug="zh-tw-hsiaochen",
            teacher="edgetts",
            corpus_hours=0.5,
            edge_voice="zh-TW-HsiaoChenNeural",
            epochs=20,
            pad_silence_ms=120,
            encoder_anchor=0.05,
            num_ode_steps=4,
        )
        cmd_corpus = ttj.build_step_command("corpus", cfg_edge, repo_root=tmp)
        self.assertIn("build_corpus.py", cmd_corpus[1])
        self.assertIn("--preserve-existing", cmd_corpus)
        self.assertIn("0.5", cmd_corpus)

        cmd_distill_edge = ttj.build_step_command("distill", cfg_edge, repo_root=tmp)
        self.assertIn("distill_edge_teacher.py", cmd_distill_edge[1])
        self.assertIn("zh-TW-HsiaoChenNeural", cmd_distill_edge)
        self.assertIn("--resume", cmd_distill_edge)

        cfg_cosy = ttj.TtsTrainingConfig(
            slug="zh-tw-yunjhe",
            teacher="cosyvoice",
            prompt_wav="data/tts/prompts/a.wav",
            prompt_txt="data/tts/prompts/a.txt",
        )
        cmd_distill_cosy = ttj.build_step_command("distill", cfg_cosy, repo_root=tmp)
        self.assertIn("distill_teacher.py", cmd_distill_cosy[1])
        self.assertIn(str((tmp / "data/tts/prompts/a.wav").resolve()), cmd_distill_cosy)

        cmd_train = ttj.build_step_command("train", cfg_edge, repo_root=tmp)
        self.assertIn("train_matcha.py", cmd_train[1])
        self.assertIn("--freeze-emb", cmd_train)
        self.assertIn("--full-seq", cmd_train)
        self.assertIn("120", cmd_train)

        cmd_export = ttj.build_step_command("export", cfg_edge, repo_root=tmp)
        self.assertIn("export_matcha_onnx.py", cmd_export[1])
        self.assertIn("--num-ode-steps", cmd_export)

    def test_prompt_path_traversal_rejected(self) -> None:
        tmp = Path("/tmp/nova_test_tts_sec")
        cfg = ttj.TtsTrainingConfig(
            slug="zh-tw-bad",
            teacher="cosyvoice",
            prompt_wav="/etc/passwd",
            prompt_txt="data/tts/prompts/a.txt",
        )
        with self.assertRaises(SettingsError):
            ttj.build_step_command("distill", cfg, repo_root=tmp)

    def test_append_custom_sentences_deduplicates_and_tags_language(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            corpus = Path(td) / "corpus.jsonl"
            corpus.write_text(
                json.dumps({"id": "utt_00000", "language": "zh", "text": "你好歡迎光臨", "est_seconds": 2.0}) + "\n",
                encoding="utf-8",
            )
            added = ttj.append_custom_sentences(
                corpus,
                "你好歡迎光臨\n歡迎來到智慧展廳。\nHello, how may I help you today?\n",
            )
            self.assertEqual(added, 2)
            rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[1]["language"], "zh")
            self.assertEqual(rows[2]["language"], "en")

    def test_write_export_notices_enforces_edge_non_commercial(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            root = Path(td)
            export_dir = root / "models/tts/zh-tw-demo"
            (export_dir).mkdir(parents=True, exist_ok=True)
            (export_dir / "model.onnx").write_bytes(b"onnx")
            (export_dir / "tokens.txt").write_text("sil 0\n", encoding="utf-8")

            edge_cfg = ttj.TtsTrainingConfig(slug="zh-tw-demo", teacher="edgetts", edge_voice="zh-TW-HsiaoChenNeural")
            ttj.write_export_notices(export_dir, edge_cfg)

            notice = export_dir / "NOTICE-NON-COMMERCIAL.txt"
            self.assertTrue(notice.is_file())
            self.assertIn("Research / Non-commercial", notice.read_text(encoding="utf-8"))

            snap = ttj.get_training_snapshot("zh-tw-demo", repo_root=root)
            self.assertEqual(len(snap["trained_models"]), 1)
            self.assertTrue(snap["trained_models"][0]["non_commercial"])
            self.assertEqual(snap["trained_models"][0]["license_tag"], "Research / Non-commercial")

            cosy_cfg = ttj.TtsTrainingConfig(slug="zh-tw-demo", teacher="cosyvoice")
            ttj.write_export_notices(export_dir, cosy_cfg)
            self.assertFalse(notice.is_file())

    def test_active_session_blocks_gpu_steps_with_409(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            root = Path(td)
            cfg = ttj.TtsTrainingConfig(slug="zh-tw-demo", teacher="edgetts")
            with self.assertRaises(SettingsError) as ctx:
                ttj.start_training_step(step="train", cfg=cfg, session_count=1, repo_root=root)
            self.assertEqual(ctx.exception.status, 409)
            self.assertTrue(ctx.exception.extra.get("need_disconnect"))

    def test_start_training_step_runs_corpus_and_finishes(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            root = Path(td)
            cfg = ttj.TtsTrainingConfig(
                slug="zh-tw-demo",
                teacher="edgetts",
                extra_sentences="自訂測試語句一號。",
            )

            def _fake_subproc(cmd, *, cwd, job, step_label):
                del cmd, cwd, step_label
                paths = ttj.workspace_paths(root, cfg.slug)
                paths["corpus"].parent.mkdir(parents=True, exist_ok=True)
                paths["corpus"].write_text(
                    json.dumps({"id": "utt_00000", "language": "zh", "text": "預置語料。", "est_seconds": 1.5}) + "\n",
                    encoding="utf-8",
                )
                job.logs.append("simulated ok")
                return 0

            with patch.object(ttj, "_run_subprocess", side_effect=_fake_subproc):
                job = ttj.start_training_step(step="corpus", cfg=cfg, session_count=0, repo_root=root)
                deadline = time.time() + 3.0
                while job.status in {"queued", "running"} and time.time() < deadline:
                    time.sleep(0.02)

            self.assertEqual(job.status, "done")
            self.assertEqual(job.progress, 100)
            self.assertEqual(job.step_states["corpus"], "done")
            corpus_path = ttj.workspace_paths(root, cfg.slug)["corpus"]
            lines = [ln for ln in corpus_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertEqual(len(lines), 2)


class TtsTrainingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_status_validation_and_cancel(self) -> None:
        previous_streams = state.avatar_streams
        state.avatar_streams = {}
        app = web.Application()
        app.router.add_get("/api/tts/training", tts_routes.get_tts_training_status)
        app.router.add_post("/api/tts/training/step", tts_routes.run_tts_training_step)
        app.router.add_post("/api/tts/training/cancel", tts_routes.cancel_tts_training)
        app.router.add_post("/api/tts/training/preview", tts_routes.preview_tts_teacher_voice)

        server = TestServer(app)
        client = TestClient(server)
        try:
            await client.start_server()

            res_get = await client.get("/api/tts/training?slug=zh-tw-custom")
            self.assertEqual(res_get.status, 200)
            body = await res_get.json()
            self.assertEqual(body["code"], 0)
            self.assertIn("prerequisites", body["data"])
            self.assertIn("workspace", body["data"])

            res_bad = await client.post("/api/tts/training/step", json={"step": "unknown"})
            self.assertEqual(res_bad.status, 400)

            res_bad_voice = await client.post("/api/tts/training/preview", json={"voice": "../bad"})
            self.assertEqual(res_bad_voice.status, 400)

            class _FakePool:
                def __init__(self, **_kwargs):
                    self.closed = False

                async def stream(self, text: str, voice: str):
                    self.text = text
                    self.voice = voice
                    yield {"type": "audio", "data": b"ID3fakemp3"}

                async def close(self):
                    self.closed = True

            with patch("src.tts.edge_connection.EdgeConnectionPool", _FakePool):
                res_prev = await client.post(
                    "/api/tts/training/preview",
                    json={"voice": "zh-TW-HsiaoChenNeural"},
                )
            self.assertEqual(res_prev.status, 200)
            prev_body = await res_prev.json()
            self.assertEqual(prev_body["code"], 0)
            self.assertTrue(prev_body["data"]["preview_audio"].startswith("data:audio/mpeg;base64,"))

            res_cancel = await client.post("/api/tts/training/cancel")
            self.assertEqual(res_cancel.status, 200)
            self.assertEqual((await res_cancel.json())["code"], 0)
        finally:
            state.avatar_streams = previous_streams
            await client.close()
