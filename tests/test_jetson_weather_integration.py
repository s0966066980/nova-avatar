# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for Jetson Orin single-role weather tool and console API."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config.loader import dict_to_config
from src.config.overrides import persist_runtime_overrides
from src.config.schema import Config, WeatherConfig
from src.ragflow import settings as ragflow_settings
from src.server.routes.weather import (
    get_weather_settings,
    put_weather_settings,
    test_weather_query as handle_test_weather_query,
)
from src.server.voice_session import VoiceTurnSession
from src.weather import ANSWER_CONTEXT

DATASET_A = "a" * 32


class _FakeAvatar:
    def __init__(self, sessionid: int = 101):
        self.sessionid = sessionid
        self.messages = []

    def put_msg_txt(self, text, data=None):
        self.messages.append((text, data))

    def flush_talk(self):
        pass

    def configure_media_fence(self, **_kwargs):
        pass


def _mock_forecast_result(county: str = "臺北市", town: str = "") -> dict:
    return {
        "status": "available",
        "source": "中央氣象署氣象資料開放平臺",
        "source_url": "https://opendata.cwa.gov.tw",
        "county": county,
        "town": town,
        "kind": "forecast",
        "start_date": "2026-10-30",
        "end_date": "2026-10-30",
        "fetched_at": "2026-10-30T10:00:00+08:00",
        "issued_at": "2026-10-30T08:00:00+08:00",
        "timezone": "Asia/Taipei",
        "cached": False,
        "query_seconds": 0.12,
        "series": {
            "temperature_c": [
                {"start": "2026-10-30T12:00:00+08:00", "end": "2026-10-30T15:00:00+08:00", "value": 26}
            ],
            "precipitation_probability_3h": [
                {"start": "2026-10-30T12:00:00+08:00", "end": "2026-10-30T15:00:00+08:00", "value": 40}
            ],
            "weather": [
                {"start": "2026-10-30T12:00:00+08:00", "end": "2026-10-30T15:00:00+08:00", "value": "多雲時晴"}
            ],
        },
        "probability_note": "",
    }


class JetsonWeatherTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.rag_patch = patch.object(
            ragflow_settings,
            "SETTINGS_FILE",
            Path(self.directory.name) / "ragflow.yaml",
        )
        self.rag_patch.start()
        ragflow_settings.save_avatar_settings("alpha", enabled=True, dataset_ids=[DATASET_A])
        self.avatar = _FakeAvatar(sessionid=101)
        self.config = Config()
        self.config.model.avatar_id = "alpha"
        self.config.reply_streaming.enabled = False
        self.config.weather = WeatherConfig(enabled=True, county="", town="")
        self.session = VoiceTurnSession(101, self.config, self.avatar)
        self.session._segmenter = SimpleNamespace(reset=lambda: None, is_speaking=False)
        self.events = []
        self.session.attach_event_sink(lambda raw: self.events.append(json.loads(raw)))

    async def asyncTearDown(self):
        await self.session.close()
        self.rag_patch.stop()
        self.directory.cleanup()

    async def test_pure_weather_turn_skips_ragflow_and_injects_weather_prompt(self):
        llm_calls = []
        rag_calls = []
        queries = []

        def fake_llm(_text, _avatar, **kwargs):
            llm_calls.append(kwargs)
            return "臺北市今天多雲時晴，氣溫約 26 度。"

        async def fake_retrieve(_client, question, dataset_ids):
            rag_calls.append((question, dataset_ids))
            return {"status": "matched", "sources": [{"document_name": "手冊", "content": "產品內容"}]}

        async def fake_weather_query(query_obj):
            queries.append(query_obj)
            return _mock_forecast_result(county=query_obj.county, town=query_obj.town)

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm), patch(
            "src.server.voice_session.RagFlowClient.retrieve", fake_retrieve
        ), patch("src.server.voice_session.weather_service.query", side_effect=fake_weather_query):
            await self.session.start_text_turn("今天臺北天氣如何？", interrupt=False)
            await self.session._turn_task

        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0].county, "臺北市")
        self.assertEqual(rag_calls, [])
        self.assertEqual(len(llm_calls), 1)
        self.assertIn("中央氣象署氣象資料開放平臺", llm_calls[0]["rag_context"])
        self.assertEqual(self.session._weather_confirmed["county"], "臺北市")
        lookup_events = [e for e in self.events if e["type"] == "weather_lookup"]
        self.assertEqual(len(lookup_events), 1)
        self.assertEqual(lookup_events[0]["status"], "available")
        self.assertEqual(lookup_events[0]["county"], "臺北市")

    async def test_followup_and_county_switch_and_reset_conversation(self):
        queries = []

        async def fake_weather_query(query_obj):
            queries.append(query_obj)
            return _mock_forecast_result(county=query_obj.county, town=query_obj.town)

        self.session._weather_confirmed = {
            "county": "臺北市",
            "town": "信義區",
            "kind": "forecast",
            "start_date": "2026-10-30",
            "end_date": "2026-10-30",
        }

        with patch("src.server.voice_session.llm_response", return_value="回答"), patch(
            "src.server.voice_session.weather_service.query", side_effect=fake_weather_query
        ):
            # Follow-up keeps confirmed county and town
            await self.session.start_text_turn("那明天會下雨嗎？", interrupt=False)
            await self.session._turn_task
            self.assertEqual(queries[-1].county, "臺北市")
            self.assertEqual(queries[-1].town, "信義區")
            self.session._turn_id = None

            # Switching county clears previous county's town
            await self.session.start_text_turn("那高雄市明天會下雨嗎？", interrupt=False)
            await self.session._turn_task
            self.assertEqual(queries[-1].county, "高雄市")
            self.assertEqual(queries[-1].town, "")
            self.session._turn_id = None

            # Reset conversation clears confirmed location so missing county asks for clarification
            self.session.reset_conversation()
            self.assertEqual(self.session._weather_confirmed, {})
            self.avatar.messages.clear()
            await self.session.start_text_turn("明天會下雨嗎？", interrupt=False)
            if self.session._turn_task:
                await self.session._turn_task
            self.assertEqual(len(queries), 2)
            self.assertIn("哪個縣市", self.avatar.messages[-1][0])

    async def test_clarification_respects_english_locale_without_calling_llm_or_cwa(self):
        llm_calls = []
        queries = []
        self.session._conversation["locale"] = "en-US"

        with patch("src.server.voice_session.llm_response", side_effect=lambda *a, **kw: llm_calls.append(1)), patch(
            "src.server.voice_session.weather_service.query", side_effect=lambda q: queries.append(q)
        ):
            await self.session.start_text_turn("What's the weather in Hsinchu tomorrow?", interrupt=False)
            if self.session._turn_task:
                await self.session._turn_task

        self.assertEqual(llm_calls, [])
        self.assertEqual(queries, [])
        self.assertEqual(
            self.avatar.messages[-1][0],
            "Which city or county and district would you like the weather for?",
        )

    async def test_mixed_topic_runs_ragflow_and_merges_with_weather_context(self):
        llm_calls = []
        rag_calls = []

        def fake_llm(_text, _avatar, **kwargs):
            llm_calls.append(kwargs)
            return "綜合回答"

        async def fake_retrieve(_client, question, dataset_ids):
            rag_calls.append((question, dataset_ids))
            return {
                "status": "matched",
                "sources": [{"document_name": "展覽手冊", "content": "展覽開放時間為 09:00-17:00"}],
            }

        def fake_plan(_config, _text, _history, _confirmed, **_kwargs):
            return {
                "route": "specialist",
                "pure_weather": False,
                "county": "臺北市",
                "town": "",
                "kind": "forecast",
                "start_date": "2026-10-30",
                "end_date": "2026-10-30",
                "clarification": "",
                "context": "",
            }

        with patch("src.server.voice_session.resolve_weather_plan", side_effect=fake_plan), patch(
            "src.server.voice_session.RagFlowClient.retrieve", fake_retrieve
        ), patch(
            "src.server.voice_session.weather_service.query",
            return_value=_mock_forecast_result(county="臺北市"),
        ), patch("src.server.voice_session.llm_response", side_effect=fake_llm):
            await self.session.start_text_turn("今天臺北天氣如何？順便介紹一下展覽開放時間", interrupt=False)
            await self.session._turn_task

        self.assertEqual(len(rag_calls), 1)
        self.assertEqual(len(llm_calls), 1)
        self.assertIn("展覽開放時間為 09:00-17:00", llm_calls[0]["rag_context"])
        self.assertIn("中央氣象署氣象資料開放平臺", llm_calls[0]["rag_context"])

    async def test_disabled_weather_injects_anti_hallucination_context(self):
        self.config.weather.enabled = False
        ragflow_settings.save_avatar_settings("alpha", enabled=False, dataset_ids=[])
        llm_calls = []

        def fake_llm(_text, _avatar, **kwargs):
            llm_calls.append(kwargs)
            return "目前未啟用即時氣象查詢。"

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm):
            await self.session.start_text_turn("今天臺北天氣如何？", interrupt=False)
            await self.session._turn_task

        self.assertEqual(len(llm_calls), 1)
        self.assertEqual(llm_calls[0].get("rag_context"), ANSWER_CONTEXT)


class WeatherRoutesAndPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_weather_settings_routes_and_override_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            override_path = Path(tmpdir) / "runtime_overrides.yaml"
            cfg = Config()
            with patch("src.server.routes.weather.state", SimpleNamespace(config=cfg)):
                with patch.dict("os.environ", {"NOVA_CWA_API_KEY": "secret-cwa-key"}):
                    resp_get = await get_weather_settings(SimpleNamespace())
                    body_get = json.loads(resp_get.text)
                    self.assertEqual(body_get["code"], 0)
                    self.assertTrue(body_get["data"]["configured"])
                    self.assertNotIn("secret-cwa-key", resp_get.text)

                class PutReq:
                    async def json(self):
                        return {"enabled": True, "county": "台北市", "town": "信義區"}

                with patch("src.server.routes.weather.persist_runtime_overrides") as mock_persist:
                    resp_put = await put_weather_settings(PutReq())
                    body_put = json.loads(resp_put.text)
                    self.assertEqual(body_put["code"], 0)
                    self.assertEqual(body_put["data"]["county"], "臺北市")
                    self.assertEqual(body_put["data"]["town"], "信義區")
                    mock_persist.assert_called_once_with(cfg)

                with patch("src.config.overrides.RUNTIME_OVERRIDES_FILE", override_path):
                    persist_runtime_overrides(cfg)
                raw = override_path.read_text(encoding="utf-8")
                import yaml
                loaded = dict_to_config(yaml.safe_load(raw))
                self.assertTrue(loaded.weather.enabled)
                self.assertEqual(loaded.weather.county, "臺北市")
                self.assertEqual(loaded.weather.town, "信義區")

                class TestReq:
                    async def json(self):
                        return {"question": "今天天氣如何？"}

                with patch(
                    "src.server.routes.weather.weather_service.query",
                    return_value=_mock_forecast_result(county="臺北市", town="信義區"),
                ):
                    resp_test = await handle_test_weather_query(TestReq())
                    body_test = json.loads(resp_test.text)
                    self.assertEqual(body_test["code"], 0)
                    self.assertEqual(body_test["data"]["route"], "specialist")
                    self.assertEqual(body_test["data"]["plan"]["county"], "臺北市")
                    self.assertEqual(body_test["data"]["plan"]["town"], "信義區")
                    self.assertIn("中央氣象署", body_test["data"]["summary"])
