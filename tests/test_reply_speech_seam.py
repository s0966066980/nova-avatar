# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM emits spoken-text deltas; the core cuts playable fragments (ADR 0027)."""

import unittest

from src.config.schema import Config
from src.llm.base import BaseLLM
from src.llm.reply_events import ReviewedFragment, SpeechEnd, SpokenDelta
from src.server.reply_streaming.speech import ReplySpeech


class RecordingSink:
    """Stands in for the core: records what the LLM layer hands over."""

    def __init__(self):
        self.events = []
        self.review = None
        self.closed = False

    def open(self, review):
        self.review = review

    def send(self, event):
        self.events.append(event)

    def close(self):
        self.closed = True


class ChunkedLLM(BaseLLM):
    def __init__(self, config, chunks):
        super().__init__(config)
        self._chunks = chunks

    def chat_stream(self, message, system_prompt=None):
        del message, system_prompt
        yield from self._chunks


class LLMEmitsSpokenDeltasTests(unittest.TestCase):
    def test_model_chunks_reach_the_core_uncut_and_in_order(self):
        # A sentence boundary inside a chunk is the core's to cut, not the LLM's.
        sink = RecordingSink()
        ChunkedLLM(Config(), ["第一句。第二", "句還沒說完", "。"]).generate_response(
            "fixture", speech=sink,
        )

        deltas = [event for event in sink.events if isinstance(event, SpokenDelta)]
        self.assertEqual([delta.text for delta in deltas], ["第一句。第二", "句還沒說完", "。"])
        self.assertEqual([delta.llm_sequence for delta in deltas], [0, 1, 2])
        self.assertIsInstance(sink.events[-1], SpeechEnd)
        self.assertTrue(sink.closed)

    def test_spoken_text_is_what_the_core_played_through_the_review(self):
        sink = RecordingSink()
        llm = ChunkedLLM(Config(), ["好的。", "稍後補充。"])

        def core(event):
            # The core cuts these two fragments and asks the LLM to review each.
            if isinstance(event, SpokenDelta):
                sink.review.review(event.text)

        sink.send = core
        self.assertEqual(llm.generate_response("fixture", speech=sink), "好的。稍後補充。")

    def test_without_a_sink_the_spoken_answer_is_returned_whole(self):
        response = ChunkedLLM(Config(), ["第一句。", "第二句。"]).generate_response("fixture")
        self.assertEqual(response, "第一句。第二句。")


class FragmentAvatar:
    def __init__(self):
        self.fragments = []
        self.previews = []
        self.stages = []

    def put_msg_txt(self, text, data):
        self.fragments.append((text, data))

    def notify_llm_chunk(self, text, data):
        self.previews.append((text, data))

    def mark_stage_end(self, stage):
        self.stages.append(stage)


class CoreCutsPlayableFragmentsTests(unittest.TestCase):
    def test_core_cuts_complete_sentences_and_delivers_them_in_order(self):
        avatar = FragmentAvatar()
        speech = ReplySpeech(avatar, {"turn_id": "turn-1", "generation": 3})
        response = ChunkedLLM(Config(), ["好的。稍後", "補充。"]).generate_response(
            "fixture", speech=speech, datainfo={"turn_id": "turn-1", "generation": 3},
        )

        self.assertEqual(response, "好的。稍後補充。")
        self.assertEqual(avatar.fragments, [
            ("好的。", {"turn_id": "turn-1", "generation": 3, "fragment_sequence": 0}),
            ("稍後補充。", {"turn_id": "turn-1", "generation": 3, "fragment_sequence": 1}),
        ])
        # The live transcript shows model deltas as they arrive.
        self.assertEqual([text for text, _ in avatar.previews], ["好的。稍後", "補充。"])
        self.assertEqual([data["llm_sequence"] for _, data in avatar.previews], [0, 1])
        self.assertIn("llm_first_speech", avatar.stages)

    def test_a_fragment_the_llm_review_rejects_is_never_played(self):
        class RejectingReview:
            bounded = False
            previews_fragments = True

            def review(self, fragment):
                if "秘密" in fragment:
                    return None
                return ReviewedFragment(text=fragment, preview=fragment)

        avatar = FragmentAvatar()
        speech = ReplySpeech(avatar, {"turn_id": "turn-1", "generation": 1})
        speech.open(RejectingReview())
        speech.send(SpokenDelta("這是秘密。公開的", 0))
        speech.send(SpokenDelta("內容。", 1))
        speech.send(SpeechEnd())
        speech.close()

        self.assertEqual([text for text, _ in avatar.fragments], ["公開的內容。"])
        self.assertEqual(avatar.fragments[0][1]["fragment_sequence"], 0)
        self.assertEqual([text for text, _ in avatar.previews], ["公開的內容。"])

    def test_without_a_turn_the_core_releases_whole_sentences_for_legacy_callers(self):
        avatar = FragmentAvatar()
        speech = ReplySpeech(avatar, {})
        ChunkedLLM(Config(), ["短句。", "這一句要夠長才會被單獨送出去給語音合成使用。", "尾巴"]).generate_response(
            "fixture", speech=speech,
        )

        self.assertEqual([text for text, _ in avatar.fragments], [
            "短句。這一句要夠長才會被單獨送出去給語音合成使用。", "尾巴",
        ])
        self.assertEqual([data for _, data in avatar.fragments], [{}, {}])
        self.assertEqual(avatar.previews, [])


if __name__ == "__main__":
    unittest.main()
