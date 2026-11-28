# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Issue 08: simple replies open with one short complete sentence; board speech is exempt."""
from __future__ import annotations


import pytest

from nova_llm.prompts import compose_system_prompt
from nova_llm.reply_contract import (
    FIRST_SENTENCE_MAX_CHARS, FIRST_SENTENCE_PROMPT, first_sentence_prompt,
)
from nova_llm.router import ReplyMode

pytestmark = pytest.mark.llm

SAVED_RULES = {
    "activation": "依本輪問題選擇簡答或看板回覆。",
    "speech": "簡答直接回答問題，語氣自然、清楚。\n搭配看板時，先用 50~200字以內說明主要結論。",
    "board": "使用容易閱讀的條列。",
}


def test_the_rule_asks_for_a_complete_sentence_of_at_most_fifteen_characters():
    assert FIRST_SENTENCE_MAX_CHARS == 15
    assert f"{FIRST_SENTENCE_MAX_CHARS} 字" in FIRST_SENTENCE_PROMPT
    assert "完整" in FIRST_SENTENCE_PROMPT
    assert all(mark in FIRST_SENTENCE_PROMPT for mark in "。！？")


@pytest.mark.parametrize("mode", [ReplyMode.AUTO, ReplyMode.SIMPLE, None])
def test_simple_and_auto_replies_carry_the_rule(mode):
    assert FIRST_SENTENCE_PROMPT in compose_system_prompt("角色", reply_mode=mode)


@pytest.mark.parametrize("locale", ["zh-TW", "en-US"])
def test_board_speech_is_exempt_from_the_rule(locale):
    # User decision (2026-10-30): the board summary follows the saved speech
    # Rule (e.g. 50~200 字), not the 15-character first sentence.
    board = compose_system_prompt("角色", reply_mode=ReplyMode.BOARD, output_locale=locale)
    assert "【口語第一句】" not in board and "[First spoken sentence]" not in board
    # AUTO picks the mode per turn, so the rule itself names the exemption.
    assert "看板模式的口語摘要不受這條限制" in FIRST_SENTENCE_PROMPT
    assert "也遵守" not in FIRST_SENTENCE_PROMPT
    english = first_sentence_prompt("en-US")
    assert "board mode is not bound by this rule" in english
    assert "follows this rule too" not in english


def test_saved_custom_rules_cannot_drop_it_and_it_follows_them():
    prompt = compose_system_prompt("角色", reply_mode=ReplyMode.AUTO, rules=SAVED_RULES,
                                   response_max_chars=120)

    assert prompt.count(FIRST_SENTENCE_PROMPT) == 1
    assert prompt.index(FIRST_SENTENCE_PROMPT) > prompt.index(SAVED_RULES["speech"])
    assert prompt.index(FIRST_SENTENCE_PROMPT) > prompt.index("【口語長度】")


def test_english_sessions_get_the_limit_in_words():
    # English counts words, as the first-fragment exception does (issue 08b).
    prompt = compose_system_prompt("role", reply_mode=ReplyMode.AUTO, output_locale="en-US")

    assert "12 words" in prompt
    assert f"{FIRST_SENTENCE_MAX_CHARS} 字" not in prompt
    assert FIRST_SENTENCE_PROMPT in compose_system_prompt("角色", reply_mode=ReplyMode.AUTO,
                                                          output_locale="zh-TW")
