# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Model-independent wire format. Editable Rules own mode and content policy."""

import re


def guard_board_summary(text: str, *, locale: str = "zh-TW") -> str:
    """Reject spoken enumeration without classifying the user's question.

    This only runs after the model has chosen BOARD. One complete sentence is
    enough to check ordinal/step lists before they reach TTS or conversation
    history, without waiting for the board JSON.
    """
    sequence = re.search(
        r"(?:首先|先).*(?:其次|接著|然後|再).*(?:最後|最終)"
        r"|\bfirst\b.*\b(?:then|second)\b.*\b(?:finally|last)\b",
        text, re.IGNORECASE,
    )
    ordinal_count = len(re.findall(r"第[一二三四五六七八九十\d]+(?:個|項|點|步)", text))
    named_list = re.search(
        r"[二三四五六七八九十兩\d]+(?:個|大)?(?:關鍵|核心)?(?:步驟|階段|項目|重點)(?:是|為|包括|包含)"
        r"|\b(?:steps|stages|items)\s+(?:are|include)\b", text, re.IGNORECASE,
    )
    if sequence or named_list or ordinal_count >= 2:
        if locale == "en-US":
            return "The details are organized on the board; please refer to the displayed items."
        return "具體內容已整理在看板，請參考各項說明與必要的注意事項。"
    return text

# The first playable fragment waits for a complete sentence (ADR 0007), so a
# short opening sentence is what lets speech start early (issue 08). Board
# speech is exempt (user decision 2026-10-30): it follows the saved speech
# Rule, and BOARD-only prompts omit this block.
FIRST_SENTENCE_MAX_CHARS = 15
FIRST_SENTENCE_PROMPT = f"""【口語第一句】
[[SPEECH]] 必須以一句 {FIRST_SENTENCE_MAX_CHARS} 字以內、可單獨聽懂的完整短句開頭，直接說出結論，並以「。」「！」或「？」結束。
第一句不要用逗號接成長句；補充說明放在後面的句子。看板模式的口語摘要不受這條限制，依口語回答規則。
"""
# English counts words, as the first-fragment exception does (issue 08b).
FIRST_SENTENCE_MAX_WORDS = 12
FIRST_SENTENCE_PROMPT_EN = f"""[First spoken sentence]
[[SPEECH]] must open with one complete short sentence of at most {FIRST_SENTENCE_MAX_WORDS} words that makes sense on its own, states the conclusion directly, and ends with ".", "!" or "?".
Do not chain the first sentence into a long one with commas; put further detail in later sentences. The spoken summary in board mode is not bound by this rule; it follows the speech rules.
"""


def first_sentence_prompt(locale: str) -> str:
    """The first-sentence rule in the unit the session's language is counted in."""
    return FIRST_SENTENCE_PROMPT_EN if locale == "en-US" else FIRST_SENTENCE_PROMPT

AUTO_BOARD_SCHEMA_PROMPT = """For BOARD, BOARD_JSON has this required schema in words:
the top level has title (string) and items (array).
Each object in items has title (string) and content (string).
Only title and items are permitted at the top level.
Every displayed item must be inside items and must use title and content.
Do not use JSON keys named steps, step, description, spoken_summary, or board_json.
Do not use Markdown fences or any alternate JSON shape."""

CHANNEL_SPLIT_PROMPT = """【口語與看板分工】
前面若要求避免列表、序號、特殊符號、控制字數，或話題複雜時先簡短總結，那些要求只約束 [[SPEECH]] 口語。
角色與限制 Prompt 決定身份、能力與回答範圍；可編輯的看板啟用規則決定模式。
固定格式只決定傳輸結構，不覆蓋你設定的看板啟用條件。
搭配看板時，口語只說主要結論與必要前提，不逐項列舉、朗讀或複製看板細節。
BOARD 的口語只用一句整體結論，以完整句號結束；展開說明全部放看板。
看板模式的口語也不能把項目標題串成一句清單；不要念出每個步驟名稱或比較點。
正確口語範例：「先確保系統能安全穩定運作，具體檢查項目已整理在看板。」
錯誤口語範例：「三個步驟是檢查環境、設定服務、測試功能。」
看板項目的標題與具體說明只放在 [[BOARD_JSON]]；只有 [[SPEECH]] 會被朗讀。
口語不要用「首先、其次、最後」等方式把步驟念完，也不要逐一解說所有比較對象。
看板項目數嚴格依使用者要求與上限；要求三項就只產生三項，不另外增加提醒、總結或第四項。
"""

AUTO_MODE_PROMPT = """【固定回覆格式】
先依「看板啟用規則」判斷問題是否需要看板：符合啟用規則就選 BOARD，否則選 SIMPLE。
選擇一次模式後，整輪不得改變模式。
BOARD 的完整格式：
[[MODE:BOARD]]
[[SPEECH]]
一句有實質結論的口語摘要。
[[BOARD_JSON]]
{"title":"主題","items":[{"title":"項目標題","content":"具體內容"}]}
[[END]]

SIMPLE 的完整格式（結束後不可再輸出看板）：
[[MODE:SIMPLE]]
[[SPEECH]]
自然、簡短的回答。
[[END]]

以上是格式示例，請用本輪實際答案替換內容。
第一行只能是選定的模式標記；先口語，再看板，最後必須輸出 [[END]]。
不可先標 SIMPLE 再附加看板，不加前言、Markdown、其他函式或解說格式的文字。
看板資料格式不是回答內容；標記與 JSON 是傳輸資料，不是工具呼叫。
不可把思考、工具標記、JSON 或格式說明放入口語。
""" + AUTO_BOARD_SCHEMA_PROMPT


def auto_reply_grammar(system_prompt: str, *, max_items: int, thinking: bool = False) -> str | None:
    """Constrain AUTO syntax for llama.cpp, retaining a required thinking envelope.

    Providers without GBNF support still receive the identical system prompt.
    Grammar constrains structure, while the model follows Rules for meaning.
    """
    if AUTO_MODE_PROMPT not in system_prompt:
        return None
    count = max(1, min(12, int(max_items))) - 1
    root = '[^<]* "</think>" "\\n" (simple | board)' if thinking else '(simple | board)'
    return 'root ::= ' + root + '\n' + r'''simple ::= "[[MODE:SIMPLE]]\n[[SPEECH]]\n" speech "\n[[END]]"
board ::= "[[MODE:BOARD]]\n[[SPEECH]]\n" board-speech "\n[[BOARD_JSON]]\n" board-json "\n[[END]]"
speech ::= [^\n\r\[\]{}<>`#*|]+
board-speech ::= [^\n\r\[\]{}<>`#*|:：、。！？.!?]+ [。！？.!?]
board-json ::= "{" ws "\"title\":" ws json-string "," ws "\"items\":" ws "[" item ("," ws item){0,COUNT} "]" ws "}"
item ::= "{" ws "\"title\":" ws json-string "," ws "\"content\":" ws json-string ws "}"
json-string ::= "\"" json-char+ "\""
json-char ::= [^"\\\x00-\x1f] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})
ws ::= [ \t\n]{0,2}
'''.replace('COUNT', str(count))
