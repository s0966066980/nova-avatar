# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Gemma 4 E2B compatibility: thinking off, reply contract and routing JSON."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from src.config.schema import Config
from src.llm.engines.openai import OpenAILLM
from src.llm.prompts import compose_system_prompt
from src.llm.router import ReplyMode
from src.profiles.routing import route_question
from src.profiles.store import ProfileStore

E2B = "gemma-4-E2B_q4_0-it"


class _Completion:
    def __iter__(self):
        yield SimpleNamespace(usage=None, choices=[SimpleNamespace(
            delta=SimpleNamespace(content="[[MODE:SIMPLE]]\n[[SPEECH]]\n好的。\n[[END]]"),
            finish_reason="stop")])

    def close(self):
        pass


def _local_engine(model):
    config = Config()
    config.llm.provider = "llamacpp"
    config.llm.model = model
    engine = OpenAILLM(config, api_key="test", model=model)
    engine._client = MagicMock()
    engine._client.chat.completions.create.return_value = _Completion()
    return engine


def _answer_request(model):
    engine = _local_engine(model)
    prompt = compose_system_prompt("你是助手。", reply_mode=ReplyMode.AUTO, board_max_items=8)
    list(engine.chat_stream("你好", system_prompt=prompt))
    return engine._client.chat.completions.create.call_args.kwargs


def test_e2b_answer_turns_thinking_off_and_uses_the_plain_reply_grammar():
    request = _answer_request(E2B)
    extra = request["extra_body"]
    # The request itself disables thinking, so an externally started server
    # without --reasoning off cannot put a thought channel before the reply.
    assert extra["chat_template_kwargs"] == {"enable_thinking": False}
    assert extra["grammar"].startswith("root ::= (simple | board)")
    assert "</think>" not in extra["grammar"]
    assert request["temperature"] == 0.0


def test_lfm_keeps_its_bounded_thinking_envelope():
    extra = _answer_request("LFM2.5-2.6B-Q4_K_M")["extra_body"]
    assert "chat_template_kwargs" not in extra
    assert "</think>" in extra["grammar"]


def _library(config):
    return ProfileStore(Path(tempfile.mkdtemp()) / "profiles.yaml").initialize(config)


def _routing(raw, *, provider="llamacpp", model=E2B):
    config = Config()
    config.llm.provider = provider
    config.llm.model = model
    config.llm.base_url = "http://127.0.0.1:18080/v1"
    library = _library(config)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
    create = Mock(return_value=response)

    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        def close(self):
            pass

    routed = route_question(config, library, library["pair"]["main"], "介紹你們的服務", [], {},
                            client_factory=Client)
    return routed, create.call_args.kwargs


def test_local_routing_is_constrained_to_the_route_schema_without_thinking():
    _, request = _routing(json.dumps({"route": "answer"}))
    response_format = request["response_format"]
    assert response_format["type"] == "json_schema"
    schema = response_format["json_schema"]["schema"]
    assert schema["properties"]["route"]["enum"] == ["answer", "specialist", "clarify"]
    assert schema["required"][0] == "route"
    assert request["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_routing_reads_a_decision_wrapped_in_a_fence_or_thought_channel():
    decision = json.dumps({"route": "answer", "clarification": ""}, ensure_ascii=False)
    for raw in (f"```json\n{decision}\n```",
                f"<|channel>thought\n<channel|>{decision}",
                f"<think>\n</think>\n{decision}"):
        routed, _ = _routing(raw, provider="ollama", model="gemma4:e2b")
        assert routed["route"] == "answer"


def test_routing_treats_null_fields_as_empty():
    raw = json.dumps({"route": "answer", "clarification": None, "county": None, "town": None,
                      "kind": None, "start_date": None, "end_date": None, "context": None})
    routed, _ = _routing(raw)
    assert routed["route"] == "answer"
    assert routed["clarification"] == routed["context"] == ""


def test_routing_still_rejects_text_that_is_not_a_decision():
    import pytest
    from src.profiles.store import ProfileError

    for raw in ("我覺得應該交給主角色。", '{"route": "weather"}', "[]"):
        with pytest.raises(ProfileError):
            _routing(raw)


def test_other_providers_keep_plain_json_mode():
    _, request = _routing(json.dumps({"route": "answer"}), provider="ollama", model="qwen3.5:4b")
    assert request["response_format"] == {"type": "json_object"}
    assert "chat_template_kwargs" not in (request["extra_body"] or {})
