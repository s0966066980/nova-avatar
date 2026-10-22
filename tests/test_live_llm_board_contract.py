# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Opt-in startup and reply probes for the configured real LLM.

This is deliberately excluded from the default unit suite: it calls the local
configured model.  Run it with NOVA_AVATAR_LIVE_LLM_CONTRACT=1 after starting the
model endpoint.
"""

from __future__ import annotations

import os
import unittest

from src.config.loader import load_config
from src.llm.engines.openai import OpenAILLM
from src.llm.prewarm import prewarm_local_llm
from src.llm.rules import RulesSnapshot, default_rules


@unittest.skipUnless(
    os.getenv("NOVA_AVATAR_LIVE_LLM_CONTRACT") == "1",
    "set NOVA_AVATAR_LIVE_LLM_CONTRACT=1 to run the configured real-model contract",
)
class LiveLLMBoardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(
            os.getenv("NOVA_AVATAR_LIVE_LLM_CONFIG", "config/config.yaml")
        )
        llm_config = cls.config.llm
        if llm_config.provider == "llamacpp":
            from src.llm.llamacpp import ensure_server, shutdown_llama_server

            cls.addClassCleanup(shutdown_llama_server)
            llm_config.base_url = ensure_server(
                model=llm_config.model,
                extra_dir=llm_config.llamacpp_dir,
                host=llm_config.llamacpp_host,
                port=llm_config.llamacpp_port,
                ctx=llm_config.llamacpp_ctx,
                threads=llm_config.llamacpp_threads,
            )

    def setUp(self):
        llm_config = self.config.llm
        self.llm = OpenAILLM(
            config=self.config,
            api_key=llm_config.api_key or llm_config.provider,
            base_url=llm_config.base_url,
            model=llm_config.model,
        )
        self.llm._client = self.llm.client.with_options(timeout=30, max_retries=0)
        self.addCleanup(self.llm._client.close)

    def make_default_rules(self) -> RulesSnapshot:
        values = default_rules()
        return RulesSnapshot(revision=1, **values)

    def test_selected_model_completes_startup_prewarm(self):
        self.assertTrue(prewarm_local_llm(self.config))

    def test_simple_question_returns_spoken_text_without_a_board(self):
        modes: list[str] = []
        board_events: list[dict] = []
        spoken = self.llm.generate_response(
            "請用一句話告訴我如何保持專注，不要使用看板。",
            stream_to_avatar=False,
            datainfo={
                "turn_id": "live-simple-contract",
                "generation": 0,
                "on_mode": lambda mode: modes.append(mode.value),
                "on_board": board_events.append,
                "incremental_board": True,
            },
        )
        self.assertEqual(modes, ["simple"])
        self.assertTrue(spoken.strip())
        self.assertNotIn("[[", spoken)
        self.assertFalse(board_events)

    def test_explicit_board_request_emits_renderable_items(self):
        modes: list[str] = []
        board_events: list[dict] = []

        spoken = self.llm.generate_response(
            "請用看板列出三個部署前必須確認的步驟，每項附一句具體說明。",
            stream_to_avatar=False,
            datainfo={
                "turn_id": "live-board-contract",
                "generation": 0,
                "on_mode": lambda mode: modes.append(mode.value),
                "on_board": board_events.append,
                "incremental_board": True,
            },
        )

        payloads = [event for event in board_events if "items" in event]
        self.assertEqual(modes, ["board"])
        self.assertTrue(spoken.strip())
        self.assertEqual(len(payloads), 1)
        self.assertGreaterEqual(len(payloads[0]["items"]), 3)
        for item in payloads[0]["items"]:
            self.assertTrue(item["title"].strip())
            self.assertTrue(item["content"].strip())

    def test_history_analysis_uses_a_board_without_an_explicit_list_request(self):
        modes: list[str] = []
        board_events: list[dict] = []

        self.llm.generate_response(
            "請分析台灣的歷史。",
            stream_to_avatar=False,
            datainfo={
                "turn_id": "live-history-board-contract",
                "generation": 0,
                "rules_snapshot": self.make_default_rules(),
                "on_mode": lambda mode: modes.append(mode.value),
                "on_board": board_events.append,
                "incremental_board": True,
            },
        )

        payloads = [event for event in board_events if "items" in event]
        self.assertEqual(modes, ["board"])
        self.assertEqual(len(payloads), 1)
        self.assertGreaterEqual(len(payloads[0]["items"]), 2)
