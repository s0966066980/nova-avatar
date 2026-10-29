# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Optional retrieval stays bounded, per-avatar, and fail-open for turns."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web

from src.config.schema import Config
from src.llm.base import BaseLLM
from src.ragflow import settings
from src.ragflow.client import (
    RagFlowClient, RagFlowConnection, RagFlowError, close_shared_session, retrieval_prompt,
)
from src.server.routes.ragflow import get_ragflow_settings
from src.server.voice_session import VoiceTurnSession
from scripts.ragflow_validate import EXPECTED_SERVICES, RAGFLOW_IMAGE, validate

DATASET_A = "a" * 32
DATASET_B = "b" * 32


class RagFlowDeploymentTests(unittest.TestCase):
    def test_rejects_any_public_or_additional_service_port(self):
        services = {
            name: {"networks": {"ragflow": None}, "mem_limit": "1024", "cpus": 1}
            for name in EXPECTED_SERVICES
        }
        services["ragflow-cpu"]["image"] = RAGFLOW_IMAGE
        services["ragflow-cpu"]["ports"] = [
            {"host_ip": "127.0.0.1", "published": "8088", "target": 80},
            {"host_ip": "127.0.0.1", "published": "9380", "target": 9380},
        ]
        validate({"services": services})
        services["mysql"]["ports"] = [{"host_ip": "0.0.0.0", "published": "3306", "target": 3306}]
        with self.assertRaises(ValueError):
            validate({"services": services})


class RagFlowSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(settings, "SETTINGS_FILE", Path(self.directory.name) / "ragflow.yaml")
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.directory.cleanup()

    def test_avatar_choices_are_independent_and_default_off(self):
        self.assertEqual(settings.avatar_settings("alpha"), {"enabled": False, "dataset_ids": []})
        settings.save_avatar_settings("alpha", enabled=True, dataset_ids=[DATASET_A])
        settings.save_avatar_settings("beta", enabled=False, dataset_ids=[DATASET_B])
        self.assertEqual(settings.avatar_settings("alpha"), {"enabled": True, "dataset_ids": [DATASET_A]})
        self.assertEqual(settings.avatar_settings("beta"), {"enabled": False, "dataset_ids": [DATASET_B]})
        self.assertNotIn("api_key", settings.SETTINGS_FILE.read_text(encoding="utf-8"))

    def test_rejects_bad_dataset_and_enabled_without_selection(self):
        with self.assertRaises(ValueError):
            settings.save_avatar_settings("alpha", enabled=True, dataset_ids=[])
        with self.assertRaises(ValueError):
            settings.save_avatar_settings("alpha", enabled=False, dataset_ids=["not-an-id"])
        with self.assertRaises(ValueError):
            settings.save_avatar_settings("../alpha", enabled=False, dataset_ids=[])


class RagFlowPromptTests(unittest.TestCase):
    def test_retrieval_context_is_transient(self):
        class FakeLLM(BaseLLM):
            def __init__(self, config):
                super().__init__(config)
                self.prompts = []
                self.committed = []

            def chat_stream(self, message, system_prompt=None, **_kwargs):
                self.prompts.append(system_prompt)
                yield "這是一般回答。"

            def begin_history_turn(self, message, *, turn_id):
                return turn_id

            def commit_history_turn(self, transaction, *, assistant_text, terminal_reason):
                self.committed.append(assistant_text)

        llm = FakeLLM(Config())
        context = retrieval_prompt([{"document_name": "手冊", "content": "只限本輪的資料"}])
        llm.generate_response("問題", stream_to_avatar=False, rag_context=context)
        spoken = llm.generate_response("另一個問題", stream_to_avatar=False)
        self.assertIn("只限本輪的資料", llm.prompts[0])
        self.assertNotIn("只限本輪的資料", llm.prompts[1])
        self.assertNotIn("只限本輪的資料", " ".join(llm.committed))
        self.assertEqual(spoken, "這是一般回答。")
        self.assertEqual(llm.committed[-1], spoken)


class RagFlowClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.client_ports = []

        async def datasets(request):
            self.received.append((request.path, request.headers.get("Authorization"), None))
            return web.json_response({"code": 0, "data": [{
                "id": DATASET_A, "name": "知識庫", "document_count": 2,
                "embedding_model": "bge-m3",
            }], "total_datasets": 1})

        async def retrieve(request):
            body = await request.json()
            self.received.append((request.path, request.headers.get("Authorization"), body))
            self.client_ports.append(request.transport.get_extra_info("peername")[1])
            return web.json_response({"code": 0, "data": {"chunks": [{
                "content": "內容" * 500,
                "document_keyword": "手冊",
                "document_id": "doc-1",
                "dataset_id": DATASET_A,
            }] * 10}})

        app = web.Application()
        app.router.add_get("/api/v1/datasets", datasets)
        app.router.add_post("/api/v1/retrieval", retrieve)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.client = RagFlowClient(RagFlowConnection(f"http://127.0.0.1:{port}", "local-secret"))

    async def asyncTearDown(self):
        await close_shared_session()
        await self.runner.cleanup()

    async def test_turns_reuse_one_connection_and_shutdown_closes_it(self):
        for _ in range(3):
            self.assertEqual((await self.client.retrieve("問題", [DATASET_A]))["status"], "matched")
        # Each retrieval used to open a fresh session and TCP connection.
        self.assertEqual(len(set(self.client_ports)), 1)
        # Turns retrieving at the same time (ADR 0022) share the pool.
        results = await asyncio.gather(*(self.client.retrieve("問題", [DATASET_A]) for _ in range(3)))
        self.assertEqual([r["status"] for r in results], ["matched"] * 3)
        await close_shared_session()
        await self.client.retrieve("問題", [DATASET_A])
        self.assertNotIn(self.client_ports[-1], self.client_ports[:-1])

    async def test_server_shutdown_releases_pooled_connections(self):
        import src.server.server as server
        await self.client.retrieve("問題", [DATASET_A])
        with patch.object(server.state, "roles", None), patch.object(server.state, "pcs", set()), \
                patch.object(server.state, "voice_sessions", {}), \
                patch.object(server, "shutdown_llama_server"), \
                patch.object(server, "shutdown_cosyvoice_server"), \
                patch.object(server.scene_service, "close"), \
                patch("src.tts.engines.edge.shutdown_edge_tts"):
            await server.on_shutdown(None)
        await self.client.retrieve("問題", [DATASET_A])
        self.assertNotEqual(self.client_ports[0], self.client_ports[1])

    async def test_lists_and_bounds_retrieval_without_exposing_key(self):
        datasets = await self.client.list_datasets()
        result = await self.client.retrieve("問題", [DATASET_A])
        self.assertEqual(datasets[0]["name"], "知識庫")
        self.assertEqual(result["status"], "matched")
        self.assertEqual(len(result["sources"]), 4)
        self.assertTrue(all(len(source["content"]) <= 800 for source in result["sources"]))
        self.assertTrue(all(authorization == "Bearer local-secret" for _, authorization, _ in self.received))
        self.assertEqual(self.received[-1][2]["dataset_ids"], [DATASET_A])
        prompt = retrieval_prompt(result["sources"])
        self.assertIn("不受信任", prompt)
        self.assertLess(len(prompt), 4000)

    async def test_missing_key_fails_without_network(self):
        client = RagFlowClient(RagFlowConnection("http://127.0.0.1:1", ""))
        with self.assertRaises(RagFlowError):
            await client.list_datasets()

    async def test_key_is_never_sent_to_a_non_local_endpoint(self):
        client = RagFlowClient(RagFlowConnection("https://example.com", "local-secret"))
        with self.assertRaisesRegex(RagFlowError, "loopback"):
            await client.list_datasets()

    async def test_asyncio_timeout_fails_closed_for_retrieval(self):
        with patch("aiohttp.ClientSession.request", side_effect=asyncio.TimeoutError):
            with self.assertRaisesRegex(RagFlowError, "逾時"):
                await self.client.retrieve("問題", [DATASET_A])


class _Avatar:
    def __init__(self):
        self.messages = []

    def put_msg_txt(self, text, data=None):
        self.messages.append((text, data))

    def flush_talk(self):
        pass

    def configure_media_fence(self, **_kwargs):
        pass


class RagFlowTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(settings, "SETTINGS_FILE", Path(self.directory.name) / "ragflow.yaml")
        self.path_patch.start()
        settings.save_avatar_settings("alpha", enabled=True, dataset_ids=[DATASET_A])
        self.avatar = _Avatar()
        config = SimpleNamespace(
            model=SimpleNamespace(avatar_id="alpha"),
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
            vad=SimpleNamespace(),
            reply_streaming=SimpleNamespace(enabled=False),
        )
        self.session = VoiceTurnSession(93, config, self.avatar)
        self.session._segmenter = SimpleNamespace(reset=lambda: None, is_speaking=False)
        self.events = []
        self.session.attach_event_sink(lambda raw: self.events.append(json.loads(raw)))

    async def asyncTearDown(self):
        await self.session.close()
        self.path_patch.stop()
        self.directory.cleanup()

    async def _turn(self, result=None, failure=None):
        calls = []

        def fake_llm(_text, _avatar, **kwargs):
            calls.append(kwargs)
            return "一般回答"

        async def fake_retrieve(_client, question, dataset_ids):
            self.assertEqual(question, "問題")
            self.assertEqual(dataset_ids, [DATASET_A])
            if failure:
                raise failure
            return result

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm), patch(
            "src.server.voice_session.RagFlowClient.retrieve", fake_retrieve
        ):
            await self.session.start_text_turn("問題", interrupt=False)
            await self.session._turn_task
        return calls[0]

    async def test_matched_context_is_only_this_turns_prompt(self):
        call = await self._turn({"status": "matched", "sources": [{
            "document_name": "手冊", "content": "可查的事實", "document_id": "d", "dataset_id": DATASET_A,
        }]})
        self.assertIn("可查的事實", call["rag_context"])
        self.assertNotIn("spoken_prefix", call)
        self.assertEqual([e["status"] for e in self.events if e["type"] == "rag_retrieval"], ["matched"])

    async def test_no_hit_keeps_retrieval_status_out_of_the_answer(self):
        call = await self._turn({"status": "empty", "sources": []})
        self.assertNotIn("spoken_prefix", call)
        self.assertNotIn("rag_context", call)
        self.assertEqual(self.avatar.messages[0][0], "一般回答")
        self.assertEqual(
            [e["text"] for e in self.events if e["type"] == "assistant_response"],
            ["一般回答"],
        )
        self.assertEqual(
            [e["status"] for e in self.events if e["type"] == "rag_retrieval"],
            ["empty"],
        )

    async def test_failure_continues_existing_answer(self):
        call = await self._turn(failure=RagFlowError("off"))
        self.assertNotIn("rag_context", call)
        self.assertNotIn("spoken_prefix", call)
        self.assertEqual([e["status"] for e in self.events if e["type"] == "rag_retrieval"], ["unavailable"])

    async def test_interruption_during_retrieval_drops_old_result(self):
        started = asyncio.Event()
        llm_calls = []

        async def delayed_retrieve(_client, _question, _dataset_ids):
            started.set()
            await asyncio.sleep(3600)
            return {"status": "matched", "sources": []}

        with patch("src.server.voice_session.RagFlowClient.retrieve", delayed_retrieve), patch(
            "src.server.voice_session.llm_response", side_effect=lambda *_args, **_kwargs: llm_calls.append(1)
        ):
            old = await self.session.start_text_turn("問題", interrupt=False)
            await asyncio.wait_for(started.wait(), timeout=2)
            await self.session.interrupt()
            await asyncio.sleep(0)
        self.assertFalse(llm_calls)
        self.assertFalse([e for e in self.events if e["type"] == "rag_retrieval" and e["turn_id"] == old["turn_id"]])


class RagFlowRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_response_does_not_include_api_key(self):
        request = SimpleNamespace(query={"avatar_id": "alpha"})
        with patch.dict("os.environ", {"NOVA_RAGFLOW_API_KEY": "top-secret"}):
            response = await get_ragflow_settings(request)
        payload = json.loads(response.text)
        self.assertTrue(payload["data"]["configured"])
        self.assertNotIn("top-secret", response.text)


class ProfileRagScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_profile_and_draft_tests_use_role_scope_not_visual_id(self):
        from unittest.mock import AsyncMock
        from src.server.routes.ragflow import test_ragflow_retrieval
        from src.server.state import state
        saved_selection = {'enabled': True, 'dataset_ids': [DATASET_A],
                           'document_scope': 'selected', 'document_ids': ['c' * 32]}
        profile = {'id': 'main', 'avatar_id': 'shared_visual', 'rag': saved_selection}
        roles = SimpleNamespace(store=SimpleNamespace(load=lambda: {'profiles': [profile]}))
        retrieve = AsyncMock(return_value={'status': 'empty', 'sources': []})
        with patch.object(state, 'roles', roles), patch.object(RagFlowClient, 'retrieve', retrieve):
            request = SimpleNamespace(json=AsyncMock(return_value={'profile_id': 'main', 'question': '問題'}))
            response = await test_ragflow_retrieval(request)
            self.assertEqual(response.status, 200)
            retrieve.assert_awaited_with('問題', [DATASET_A], document_ids=['c' * 32])
            draft = {**saved_selection, 'dataset_ids': [DATASET_B], 'document_ids': ['d' * 32]}
            request.json.return_value = {'profile_id': 'new_unsaved_role', 'question': '草稿問題', 'selection': draft}
            response = await test_ragflow_retrieval(request)
            self.assertEqual(response.status, 200)
            retrieve.assert_awaited_with('草稿問題', [DATASET_B], document_ids=['d' * 32])
            self.assertEqual(profile['rag'], saved_selection)

    async def test_empty_explicit_document_scope_never_searches_entire_dataset(self):
        from unittest.mock import AsyncMock
        from src.server.routes.ragflow import test_ragflow_retrieval
        retrieve = AsyncMock()
        request = SimpleNamespace(json=AsyncMock(return_value={
            'profile_id': 'main', 'question': '問題', 'selection': {
                'enabled': False, 'dataset_ids': [DATASET_A],
                'document_scope': 'selected', 'document_ids': []}}))
        with patch.object(RagFlowClient, 'retrieve', retrieve):
            response = await test_ragflow_retrieval(request)
        self.assertEqual(response.status, 400)
        retrieve.assert_not_awaited()

    async def test_turn_uses_its_profiles_document_filter(self):
        from unittest.mock import AsyncMock
        config = Config()
        config.profile_id = 'main'
        config.profile_rag = {'enabled': True, 'dataset_ids': [DATASET_A],
                              'document_scope': 'selected', 'document_ids': ['c' * 32]}
        session = VoiceTurnSession(99, config, _Avatar())
        retrieve = AsyncMock(return_value={'status': 'matched', 'sources': [{
            'document_name': '角色專屬文本', 'content': '僅此角色的事實'}]})
        calls = []
        try:
            with patch.object(RagFlowClient, 'retrieve', retrieve), patch(
                'src.server.voice_session.llm_response',
                side_effect=lambda _text, _avatar, **kwargs: calls.append(kwargs) or '回答'
            ):
                await session.start_text_turn('文件問題')
                await session._turn_task
            retrieve.assert_awaited_once_with('文件問題', [DATASET_A], document_ids=['c' * 32])
            self.assertIn('僅此角色的事實', calls[0]['rag_context'])
        finally:
            await session.close()

    async def test_document_listing_is_paginated_and_retrieval_discards_other_documents(self):
        from unittest.mock import AsyncMock
        client = RagFlowClient()
        client._request = AsyncMock(return_value={'code': 0, 'data': {
            'docs': [{'id': 'c' * 32, 'name': '服務說明.txt', 'run': 'DONE', 'chunk_count': 4}],
            'total': 101}})
        page = await client.list_documents(DATASET_A)
        self.assertEqual(page['documents'][0]['name'], '服務說明.txt')
        self.assertTrue(page['has_more'])
        self.assertEqual(client._request.call_args.kwargs['params'], {'page': 1, 'page_size': 100})
        client._request.return_value = {'code': 0, 'data': {'chunks': [
            {'document_id': 'd' * 32, 'dataset_id': DATASET_A, 'content': '其他角色的文本'},
            {'document_id': 'c' * 32, 'kb_id': DATASET_A, 'content': '正確文本', 'document_keyword': '服務說明.txt'},
            {'document_id': 'c' * 32, 'kb_id': DATASET_B, 'content': '其他知識庫'},
        ]}}
        result = await client.retrieve('問題', [DATASET_A], document_ids=['c' * 32])
        self.assertEqual([s['content'] for s in result['sources']], ['正確文本'])
        self.assertEqual(result['sources'][0]['dataset_id'], DATASET_A)
        self.assertEqual(client._request.call_args.kwargs['body']['document_ids'], ['c' * 32])
