"""Opt-in contract probe for the configured real LLM board protocol.

This is deliberately excluded from the default unit suite: it calls the local
configured model.  Run it with NOVA_AVATAR_LIVE_LLM_CONTRACT=1 after starting the
model endpoint.
"""

from __future__ import annotations

import os
import unittest

from src.config.loader import load_config
from src.llm.engines.openai import OpenAILLM
from src.llm.rules import RulesSnapshot, default_rules


@unittest.skipUnless(
    os.getenv("NOVA_AVATAR_LIVE_LLM_CONTRACT") == "1",
    "set NOVA_AVATAR_LIVE_LLM_CONTRACT=1 to run the configured real-model contract",
)
class LiveLLMBoardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = load_config("config/config.yaml")
        if "127.0.0.1:8080" in config.llm.base_url or "localhost:8080" in config.llm.base_url:
            from src.llm.llamacpp import ensure_server
            ensure_server(model=config.llm.model, extra_dir="/home/oliver/llama")

    def make_default_rules(self) -> RulesSnapshot:
        values = default_rules()
        return RulesSnapshot(revision=1, **values)

    def test_explicit_board_request_emits_renderable_items(self):
        config = load_config("config/config.yaml")
        llm_config = config.llm
        modes: list[str] = []
        board_events: list[dict] = []
        llm = OpenAILLM(
            config=config,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            model=llm_config.model,
        )

        spoken = llm.generate_response(
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
        config = load_config("config/config.yaml")
        llm_config = config.llm
        modes: list[str] = []
        board_events: list[dict] = []
        llm = OpenAILLM(
            config=config,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            model=llm_config.model,
        )

        llm.generate_response(
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
