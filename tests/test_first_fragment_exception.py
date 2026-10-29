# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""The first playable fragment of a turn may end at a clause mark (issue 08)."""

import time
import unittest

from src.config.schema import Config
from src.llm.base import BaseLLM
from src.server.reply_streaming.fragmenter import SemanticFragmenter, speech_units


def stream(text: str, fragmenter: SemanticFragmenter | None = None) -> list[str]:
    """Feed ``text`` one character at a time, as a model streams it."""
    fragmenter = fragmenter or SemanticFragmenter()
    fragments: list[str] = []
    for character in text:
        fragments.extend(fragmenter.feed(character))
    return fragments + fragmenter.flush()


class FirstFragmentBoundaryTests(unittest.TestCase):
    def test_opening_clause_of_eight_characters_is_released_at_its_comma(self):
        fragmenter = SemanticFragmenter()
        released = []
        for character in "明天台北多雲時陰短暫雨，降":
            released.extend(fragmenter.feed(character))

        self.assertEqual(released, ["明天台北多雲時陰短暫雨，"])

    def test_later_clauses_keep_the_complete_semantic_boundary(self):
        text = "明天台北多雲時陰短暫雨，降雨機率為六成以上，出門記得帶傘。下午轉晴，晚上偏涼。"

        self.assertEqual(stream(text), [
            "明天台北多雲時陰短暫雨，",
            "降雨機率為六成以上，出門記得帶傘。",
            "下午轉晴，晚上偏涼。",
        ])

    def test_a_turn_that_opens_with_a_sentence_has_used_its_exception(self):
        self.assertEqual(stream("好的。明天台北多雲時陰短暫雨，出門記得帶傘。"),
                         ["好的。", "明天台北多雲時陰短暫雨，出門記得帶傘。"])

    def test_short_opening_clause_waits_for_the_sentence(self):
        text = "不客氣，Nova Avatar 隨時都在這裡幫您。"

        self.assertEqual(stream(text), [text])

    def test_list_comma_and_quoted_text_never_end_the_first_fragment(self):
        self.assertEqual(stream("準確清楚而且有幫助、快速、簡潔。"),
                         ["準確清楚而且有幫助、快速、簡潔。"])
        self.assertEqual(stream("他說「明天台北會下大雨，記得帶傘」。"),
                         ["他說「明天台北會下大雨，記得帶傘」。"])

    def test_numbers_times_and_urls_keep_their_inline_marks(self):
        self.assertEqual(stream("這個方案的總價格是新台幣 1,250,000 元，請確認。"),
                         ["這個方案的總價格是新台幣 1,250,000 元，", "請確認。"])
        self.assertEqual(stream("明天的會議時間訂在下午 3:30，地點在三樓。"),
                         ["明天的會議時間訂在下午 3:30，", "地點在三樓。"])
        self.assertEqual(
            stream("Please open the settings page at https://example.com/a, then sign in."),
            ["Please open the settings page at https://example.com/a,", "then sign in."],
        )

    def test_english_counts_words_not_letters(self):
        short = "Tomorrow looks cloudy, with light rain later."
        self.assertEqual(stream(short), [short])
        self.assertEqual(
            stream("In Taipei tomorrow the sky will stay cloudy, with light rain later."),
            ["In Taipei tomorrow the sky will stay cloudy,", "with light rain later."],
        )

    def test_result_does_not_depend_on_token_boundaries(self):
        text = "明天台北多雲時陰短暫雨，降雨機率為六成。"
        whole = SemanticFragmenter()

        self.assertEqual(whole.feed(text) + whole.flush(), stream(text))

    def test_fragments_rejoin_to_the_reply_without_repeated_text(self):
        text = "週末臺北多雲時陰短暫雨，降雨機率較低，建議您留意一下。我們會持續更新。"

        self.assertEqual("".join(stream(text)), text)

    def test_exception_can_be_turned_off(self):
        text = "明天台北多雲時陰短暫雨，降雨機率為六成。"

        self.assertEqual(stream(text, SemanticFragmenter(first_fragment_min_units=None)), [text])

    def test_speech_units_count_cjk_characters_and_latin_words(self):
        self.assertEqual(speech_units("Nova Avatar 隨時"), 4)
        self.assertEqual(speech_units("here's a well-known fact,"), 4)
        self.assertEqual(speech_units("降雨機率為 60%"), 6)


class FirstFragmentStreamingTests(unittest.TestCase):
    class Avatar:
        def __init__(self):
            self.events = []

        def put_msg_txt(self, text, datainfo=None):
            self.events.append((time.perf_counter(), text, dict(datainfo or {})))

    def test_opening_clause_is_spoken_once_before_the_sentence_ends(self):
        later_token_at = []

        class LLM(BaseLLM):
            def chat_stream(self, message, system_prompt=None, **kwargs):
                yield "明天台北多雲時陰短暫雨，"
                time.sleep(0.2)
                later_token_at.append(time.perf_counter())
                yield "降雨機率為六成。"

        avatar = self.Avatar()
        response = LLM(Config()).generate_response(
            "fixture", avatar, datainfo={"turn_id": "turn-1", "generation": 1})

        self.assertEqual([text for _, text, _ in avatar.events],
                         ["明天台北多雲時陰短暫雨，", "降雨機率為六成。"])
        self.assertLess(avatar.events[0][0], later_token_at[0])
        self.assertEqual([info["fragment_sequence"] for _, _, info in avatar.events], [0, 1])
        self.assertEqual(response, "明天台北多雲時陰短暫雨，降雨機率為六成。")

    def test_fenced_turn_after_the_opening_clause_speaks_nothing_more(self):
        class LLM(BaseLLM):
            def chat_stream(self, message, system_prompt=None, **kwargs):
                yield "明天台北多雲時陰短暫雨，降雨"
                yield "機率為六成，記得帶傘。"

        avatar = self.Avatar()
        LLM(Config()).generate_response(
            "fixture", avatar, datainfo={"turn_id": "turn-1", "generation": 1},
            chunk_guard=lambda sequence: sequence == 0)
        time.sleep(0.7)

        self.assertEqual([text for _, text, _ in avatar.events], ["明天台北多雲時陰短暫雨，"])


if __name__ == "__main__":
    unittest.main()
