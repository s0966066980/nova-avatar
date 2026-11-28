# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's ``fake`` engine, driven through the in-process adapter (ticket 08).

The engine answers with fixed spoken text and a board, offline, so these tests
hold the layer's contract (its models, event order, cancellation and turn
commit or discard) on a machine with no model server.
"""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from nova_contracts.llm import (
    Board,
    BoardItemShown,
    BoardStart,
    ModelChunk,
    PrewarmRequest,
    Question,
    ReplyDone,
    ReplyEvent,
    ReplyModeChosen,
    ReplyRequest,
    ReplyRules,
    ReplyStarted,
    SessionRef,
    SpeechEnd,
    SpokenDelta,
    TurnCommit,
    TurnRef,
)
from nova_core.config.schema import Config
from nova_llm.adapter import InProcessLlmService
from nova_llm.config_section import llm_session, reply_rules
from nova_llm.engines import ENGINES, FakeLLM, OpenAILLM
from nova_llm.engines.fake import answer_chunks

pytestmark = pytest.mark.llm

EVENTS = TypeAdapter(ReplyEvent)


def _config(engine: str = "fake") -> Config:
    config = Config()
    config.llm.engine = engine
    config.llm.provider = "ollama"
    config.llm.model = "fake-model"
    return config


def _request(config: Config | None = None, *, turn_id: str = "t1", session_id: int = 7,
             **fields) -> ReplyRequest:
    config = config or _config()
    return ReplyRequest(session=llm_session(config, session_id), question=Question(text="嗨"),
                        rules=reply_rules(config), turn_id=turn_id, **fields)


FULL = dict(reply_mode="auto", report_mode=True, report_board=True, incremental_board=True,
            stream_speech=True)


def test_the_fake_engine_answers_offline_with_spoken_text_and_a_board():
    service = InProcessLlmService()

    events = list(service.reply(_request(**FULL)))

    kinds = [type(event) for event in events]
    assert kinds[0] is ReplyStarted and kinds[-1] is ReplyDone
    assert {ReplyModeChosen, SpokenDelta, SpeechEnd, BoardStart, BoardItemShown, Board} <= set(kinds)
    spoken = "".join(event.text for event in events if isinstance(event, SpokenDelta))
    assert spoken.strip() and events[-1].spoken == spoken.strip()
    board = next(event for event in events if isinstance(event, Board))
    assert board.title and len(board.items) >= 2


def test_every_event_round_trips_through_the_contract_models_in_the_documented_order():
    service = InProcessLlmService()

    events = list(service.reply(_request(**FULL)))

    wire = [EVENTS.validate_json(EVENTS.dump_json(event)) for event in events]
    assert wire == events
    order = [type(event).__name__ for event in events]
    assert order == ["ReplyStarted", "ModelChunk", "ReplyModeChosen", "ModelChunk", "BoardStart",
                     "BoardItemShown", "BoardItemShown", "SpokenDelta", "SpeechEnd", "SpeechEnd",
                     "Board", "ReplyDone"]
    assert all(event.turn_id == "t1" for event in events if hasattr(event, "turn_id"))
    # A spoken delta names the model chunk that carried it, after that chunk's checkpoint.
    chunk = next(e for e in events if isinstance(e, ModelChunk) and e.llm_sequence == 1)
    delta = next(e for e in events if isinstance(e, SpokenDelta))
    assert delta.llm_sequence == chunk.llm_sequence
    assert events.index(chunk) < events.index(delta)


def test_without_the_reporting_flags_the_reply_is_only_text_in_reply_done():
    events = list(InProcessLlmService().reply(_request()))

    assert [type(e) for e in events if not isinstance(e, ModelChunk)] == [ReplyStarted, ReplyDone]
    assert events[-1].spoken == "這是固定的測試回覆。"


class _Script:
    """Model chunks that record how many were pulled and whether the stream was released."""

    def __init__(self, *chunks: str) -> None:
        self.chunks = chunks
        self.pulled = 0
        self.closed = False

    def __call__(self, _message: str):
        try:
            for chunk in self.chunks:
                self.pulled += 1
                yield chunk
        finally:
            self.closed = True


def _service(script: _Script) -> InProcessLlmService:
    return InProcessLlmService(create_engine=lambda **options: FakeLLM(chunks=script, **options))


THREE = ("[[MODE:SIMPLE]]\n[[SPEECH]]\n第一句。", "第二句。", "第三句。\n[[END]]")


def test_cancelling_a_reply_stops_the_model_and_ends_the_events():
    script = _Script(*THREE)
    service = _service(script)
    stream = service.reply(_request(stream_speech=True))

    seen = []
    for event in stream:
        seen.append(event)
        if isinstance(event, ModelChunk) and event.llm_sequence == 1:
            break
    stream.close()

    assert next(stream, None) is None  # no further event after the cancellation
    assert not any(isinstance(event, (SpeechEnd, ReplyDone)) for event in seen)
    assert (script.pulled, script.closed) == (2, True)  # the third chunk was never requested


def test_a_cancelled_turn_that_is_discarded_leaves_no_history():
    service = _service(_Script(*THREE))
    stream = service.reply(_request(stream_speech=True))
    next(stream)
    stream.close()

    assert service.discard_turn(TurnRef(session_id=7, turn_id="t1")).done
    assert service.session_history(SessionRef(session_id=7)).messages == ()
    assert not service.has_session_records(SessionRef(session_id=7)).present


def _history(service) -> list[tuple[str, str]]:
    return [(m.role, m.content) for m in service.session_history(SessionRef(session_id=7)).messages]


def test_a_committed_turn_enters_the_history_once_and_cannot_be_discarded_afterwards():
    service = InProcessLlmService()
    events = list(service.reply(_request(stream_speech=True)))
    assert _history(service) == []  # nothing is remembered before the core commits
    commit = TurnCommit(session_id=7, turn_id="t1", assistant_text=events[-1].spoken,
                        terminal_reason="completed")

    assert service.commit_turn(commit).done
    assert _history(service) == [("user", "嗨"), ("assistant", "這是固定的測試回覆。")]
    assert not service.commit_turn(commit).done
    assert not service.discard_turn(TurnRef(session_id=7, turn_id="t1")).done
    assert _history(service) == [("user", "嗨"), ("assistant", "這是固定的測試回覆。")]


def test_a_discarded_turn_cannot_be_committed_and_the_next_turn_starts_clean():
    service = InProcessLlmService()
    list(service.reply(_request(turn_id="t1")))

    assert service.discard_turn(TurnRef(session_id=7, turn_id="t1")).done
    assert not service.commit_turn(TurnCommit(session_id=7, turn_id="t1", assistant_text="x",
                                              terminal_reason="completed")).done
    list(service.reply(_request(turn_id="t2")))
    assert service.commit_turn(TurnCommit(session_id=7, turn_id="t2", assistant_text="好。",
                                          terminal_reason="completed")).done
    assert _history(service) == [("user", "嗨"), ("assistant", "好。")]


# ---------------------------------------------------------------- selection through config


def test_the_engine_is_chosen_by_the_llm_section_and_is_no_console_endpoint():
    from nova_core.config.loader import dict_to_config
    from nova_core.server.runtime_settings import endpoint_choices

    config = dict_to_config({"llm": {"engine": "fake", "provider": "ollama",
                                     "base_url": "http://127.0.0.1:11434/v1", "model": "m"}})

    assert llm_session(config, 7).settings.engine == "fake"
    listed = endpoint_choices(config)
    assert [item["provider"] for item in listed] == ["ollama"]
    assert "fake" not in str(listed)


def test_an_engine_name_nobody_provides_is_refused_when_the_configuration_loads():
    from nova_core.config.loader import dict_to_config

    with pytest.raises(ValueError, match="未知的 LLM 引擎"):
        dict_to_config({"llm": {"engine": "fkae"}})


def test_a_configuration_without_an_engine_keeps_the_openai_compatible_client():
    settings = llm_session(_config(engine=""), 7).settings

    assert ENGINES[settings.engine] is OpenAILLM


def test_a_fake_engine_needs_no_model_server_to_prewarm_or_to_answer_for_a_llamacpp_endpoint():
    config = _config()
    config.llm.provider = "llamacpp"
    session = llm_session(config, 7)
    service = InProcessLlmService()

    assert session.settings.local_server is not None
    assert service.prewarm(PrewarmRequest(settings=session.settings,
                                          rules=reply_rules(config))).ready
    assert list(service.reply(_request(config)))[-1].spoken == "這是固定的測試回覆。"


def test_an_empty_scripted_answer_is_a_model_that_says_nothing():
    service = InProcessLlmService(
        create_engine=lambda **options: FakeLLM(chunks=answer_chunks(""), **options))

    events = list(service.reply(_request(stream_speech=True)))

    assert events[-1] == ReplyDone(spoken="", visible="")
