# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Tests for single-origin :8010 serving and remote UI backend guards."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from src.server.routes.ragflow import get_ragflow_settings
from src.server.routes.settings import get_speech_settings, pick_speech_path
from src.server.server import create_app
from src.server.state import state


class SingleOriginStaticTests(unittest.IsolatedAsyncioTestCase):
    async def test_root_and_stage_serve_html_even_from_external_cwd(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.chdir(tmp_dir)
            try:
                app = create_app()
                client = TestClient(TestServer(app))
                await client.start_server()
                try:
                    root_resp = await client.get("/")
                    self.assertEqual(root_resp.status, 200)
                    self.assertIn("text/html", root_resp.content_type)
                    root_body = await root_resp.text()
                    self.assertIn("<html", root_body.lower())

                    stage_resp = await client.get("/stage.html")
                    self.assertEqual(stage_resp.status, 200)
                    self.assertIn("text/html", stage_resp.content_type)
                    stage_body = await stage_resp.text()
                    self.assertIn("stage", stage_body.lower())
                finally:
                    await client.close()
            finally:
                os.chdir(original_cwd)


class RemoteSpeechPathPickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_pick_speech_path_rejects_non_loopback_client_without_tkinter(self):
        async def _json():
            return {"kind": "file"}

        request = SimpleNamespace(
            remote="192.168.1.50",
            headers={"Host": "192.168.1.10:8010"},
            json=_json,
        )
        with patch.dict(sys.modules, {"tkinter": None}):
            response = await pick_speech_path(request)
        self.assertEqual(response.status, 403)
        payload = json.loads(response.text)
        self.assertEqual(payload["code"], -1)
        self.assertEqual(payload["reason"], "remote_client")
        self.assertIn("路徑", payload["msg"])

    async def test_pick_speech_path_rejects_forwarded_non_loopback_client(self):
        async def _json():
            return {"kind": "directory"}

        request = SimpleNamespace(
            remote="127.0.0.1",
            headers={"X-Forwarded-For": "100.64.0.12, 127.0.0.1"},
            json=_json,
        )
        with patch.dict(sys.modules, {"tkinter": None}):
            response = await pick_speech_path(request)
        self.assertEqual(response.status, 403)
        payload = json.loads(response.text)
        self.assertEqual(payload["reason"], "remote_client")

    async def test_pick_speech_path_rejects_headless_linux_without_display(self):
        async def _json():
            return {"kind": "directory"}

        request = SimpleNamespace(
            remote="127.0.0.1",
            headers={"Host": "127.0.0.1:8010"},
            json=_json,
        )
        with patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}, clear=False), patch.object(
            sys, "platform", "linux"
        ), patch.dict(sys.modules, {"tkinter": None}):
            response = await pick_speech_path(request)
        self.assertEqual(response.status, 400)
        payload = json.loads(response.text)
        self.assertEqual(payload["code"], -1)
        self.assertEqual(payload["reason"], "headless")
        self.assertIn("路徑", payload["msg"])

    async def test_get_speech_settings_reports_picker_availability(self):
        previous_config = state.config
        state.config = SimpleNamespace(
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh", output_script="traditional-tw", device="auto"),
            tts=SimpleNamespace(type="edgetts", mode="auto", ref_file="zh-TW-HsiaoChenNeural", ref_text="", tts_server="", model="", language="zh", speaker="Vivian", instruct="", device="auto", voice_zh_tw="zh-TW-HsiaoChenNeural", voice_en_us="en-US-JennyNeural"),
        )
        try:
            with patch("src.server.routes.settings.speech_snapshot", return_value={"stt": {}, "tts": {}}):
                remote_req = SimpleNamespace(remote="192.168.1.50", headers={})
                with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False):
                    remote_resp = await get_speech_settings(remote_req)
                self.assertFalse(json.loads(remote_resp.text)["data"]["local_path_picker_available"])

                local_req = SimpleNamespace(remote="127.0.0.1", headers={})
                with patch.dict(os.environ, {"DISPLAY": ""}, clear=False), patch.object(sys, "platform", "linux"):
                    headless_resp = await get_speech_settings(local_req)
                self.assertFalse(json.loads(headless_resp.text)["data"]["local_path_picker_available"])

                with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False), patch.object(sys, "platform", "linux"):
                    local_resp = await get_speech_settings(local_req)
                self.assertTrue(json.loads(local_resp.text)["data"]["local_path_picker_available"])
        finally:
            state.config = previous_config


class RemoteRagFlowSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_ragflow_settings_hides_loopback_management_url_from_remote_clients(self):
        with patch("src.server.routes.ragflow.avatar_settings", return_value={"enabled": False, "dataset_ids": []}):
            remote_req = SimpleNamespace(query={"avatar_id": "alpha"}, remote="192.168.1.50", headers={})
            remote_resp = await get_ragflow_settings(remote_req)
            remote_data = json.loads(remote_resp.text)["data"]
            self.assertFalse(remote_data["is_local_client"])
            self.assertIsNone(remote_data["management_url"])

            local_req = SimpleNamespace(query={"avatar_id": "alpha"}, remote="127.0.0.1", headers={})
            local_resp = await get_ragflow_settings(local_req)
            local_data = json.loads(local_resp.text)["data"]
            self.assertTrue(local_data["is_local_client"])
            self.assertEqual(local_data["management_url"], "http://127.0.0.1:8088")
