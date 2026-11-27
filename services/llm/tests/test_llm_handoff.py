# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer decides a handoff from plain member data, without the core."""
import json
from types import SimpleNamespace

import pytest

from nova_llm.handoff import CLARIFY, RoutingError, route

MEMBERS = [
    {"id": "role_main", "name": "導覽員", "main": True, "description": "館內導覽",
     "rules": "", "weather": None},
    {"id": "role_cafe", "name": "咖啡師", "main": False, "description": "飲品與餐點",
     "rules": "", "weather": None},
]
CONFIG = SimpleNamespace(
    conversation=SimpleNamespace(locale="zh-TW"),
    llm=SimpleNamespace(provider="openai", api_key="k", base_url="http://127.0.0.1:1/v1",
                        model="m", extra_body=None),
)


def factory(reply: str):
    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])))

        def close(self):
            return None

    return lambda **_kwargs: Client()


def decide(reply: str, text: str = "有什麼咖啡？"):
    return route(CONFIG, MEMBERS, "role_main", text, [], {}, client_factory=factory(reply))


def test_a_member_id_is_the_target():
    result = decide(json.dumps({"target": "role_cafe", "clarification": "", "context": ""}))

    assert result["target"] == "role_cafe"
    assert result["decided_by"] == "model"


def test_clarify_means_no_target():
    result = decide(json.dumps({"target": CLARIFY, "clarification": "請問想問哪個主題？", "context": ""}))

    assert result["target"] is None
    assert result["clarification"] == "請問想問哪個主題？"


@pytest.mark.parametrize("reply", ["not json", json.dumps({"target": "someone_else", "clarification": "", "context": ""})])
def test_an_unusable_reply_is_a_routing_error(reply):
    with pytest.raises(RoutingError):
        decide(reply)
