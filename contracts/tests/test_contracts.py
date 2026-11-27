# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The contracts package stands alone and the committed OpenAPI matches its models."""
import json
from pathlib import Path

import pytest
from nova_contracts import CONTRACT_VERSION, HandoffRequest, ReplyDone, SpokenTextDelta
from nova_contracts.llm import LlmEvent
from nova_contracts.openapi import documents, render
from nova_contracts.turn import PlayableFragment, TurnEnvelope
from pydantic import TypeAdapter, ValidationError

OPENAPI = Path(__file__).resolve().parents[1] / "openapi"


@pytest.mark.parametrize("name", ["stt.json", "llm.json", "tts.json"])
def test_committed_openapi_matches_the_models(name):
    assert (OPENAPI / name).read_text(encoding="utf-8") == render(documents()[name]), (
        "contracts/openapi is stale: run scripts/generate-openapi.py"
    )


def test_every_document_reports_the_contract_version():
    for document in documents().values():
        assert document["info"]["version"] == CONTRACT_VERSION
        assert "/health" in document["paths"]


def test_llm_events_are_told_apart_by_their_type_field():
    adapter = TypeAdapter(LlmEvent)

    assert adapter.validate_python({"type": "spoken_text", "text": "你好"}) == SpokenTextDelta(text="你好")
    assert adapter.validate_python({"type": "done", "text": "完"}) == ReplyDone(text="完")
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "unknown", "text": "x"})


def test_a_handoff_request_needs_members_and_the_current_role():
    request = HandoffRequest(
        members=[{"id": "a", "name": "A", "main": True}], current_id="a", text="嗨",
    )

    assert request.members[0].weather is None
    with pytest.raises(ValidationError):
        HandoffRequest(current_id="a", text="嗨")


def test_a_fragment_must_have_text_and_a_nonnegative_duration():
    envelope = TurnEnvelope(turn_id="t", generation=1, stage="speech", sequence=2)

    assert PlayableFragment(envelope, "好。", 0.5).fragment_id == "t:2"
    with pytest.raises(ValueError):
        PlayableFragment(envelope, "  ", 0.5)
    with pytest.raises(ValueError):
        PlayableFragment(envelope, "好。", -1)


def test_the_committed_documents_are_valid_json():
    for path in OPENAPI.glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["openapi"].startswith("3.")
