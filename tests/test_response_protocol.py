import time
import unittest

from src.config.schema import Config
from src.llm.base import BaseLLM
from src.llm.response_protocol import (
    BoardItem,
    BoardPayload,
    FORMAT_RECOVERY_MESSAGE,
    ResponseProtocolParser,
    ThinkFilter,
)
from src.llm.router import ReplyMode


class ThinkFilterTests(unittest.TestCase):
    def test_single_chunk_think(self):
        filter_ = ThinkFilter()
        out = filter_.feed("<think>internal reasoning</think>實際回覆")
        tail = filter_.flush()
        self.assertEqual("".join(out + tail), "實際回覆")

    def test_split_think_tags(self):
        filter_ = ThinkFilter()
        chunks = [
            "前言",
            "<th",
            "ink>",
            "思考過程一",
            "思考過程二",
            "</thi",
            "nk>",
            "正式回答",
        ]
        out = []
        for c in chunks:
            out.extend(filter_.feed(c))
        out.extend(filter_.flush())
        self.assertEqual("".join(out), "前言正式回答")

    def test_multiple_think_blocks(self):
        filter_ = ThinkFilter()
        out = filter_.feed("<think>think1</think>speech1<think>think2</think>speech2")
        out.extend(filter_.flush())
        self.assertEqual("".join(out), "speech1speech2")

    def test_unclosed_think_block(self):
        filter_ = ThinkFilter()
        out = filter_.feed("<think>never closed reasoning...")
        out.extend(filter_.flush())
        self.assertEqual("".join(out), "")


class ResponseProtocolParserTests(unittest.TestCase):
    def test_simple_mode_stream(self):
        parser = ResponseProtocolParser(mode=ReplyMode.SIMPLE)
        out = []
        for c in ["你好", "，這是一般", "回覆。"]:
            out.extend(parser.feed(c))
        out.extend(parser.flush()[0])
        self.assertEqual("".join(out), "你好，這是一般回覆。")
        self.assertIsNone(parser.board_payload)

    def test_simple_mode_with_think(self):
        parser = ResponseProtocolParser(mode=ReplyMode.SIMPLE)
        out = []
        for c in ["<th", "ink>思考</think>", "簡單回答"]:
            out.extend(parser.feed(c))
        out.extend(parser.flush()[0])
        self.assertEqual("".join(out), "簡單回答")

    def test_simple_mode_suppresses_split_raw_json_and_returns_recovery(self):
        parser = ResponseProtocolParser(mode=ReplyMode.SIMPLE)
        speech = []
        for chunk in ('{"tit', 'le":"建議","items":[]}'):
            speech.extend(parser.feed(chunk))
        tail, board = parser.flush()

        self.assertEqual("".join(speech + tail), FORMAT_RECOVERY_MESSAGE)
        self.assertIsNone(board)
        self.assertTrue(parser.structured_payload_suppressed)

    def test_board_mode_full_chunk(self):
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        raw = (
            "[[SPEECH]]\n"
            "這是一段整體結論與語音摘要。\n"
            "[[BOARD_JSON]]\n"
            '{\n  "title": "建議架構",\n  "summary": "三層設計",\n  "items": [\n'
            '    {"title": "Router", "content": "規則優先"},\n'
            '    {"title": "LLM", "content": "單一模型"}\n'
            "  ]\n}\n"
            "[[END]]"
        )
        speech = parser.feed(raw)
        flush_speech, board = parser.flush()
        all_speech = "".join(speech + flush_speech).strip()
        self.assertEqual(all_speech, "這是一段整體結論與語音摘要。")
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "建議架構")
        self.assertEqual(board.summary, "三層設計")
        self.assertEqual(len(board.items), 2)
        self.assertEqual(board.items[0].title, "Router")
        self.assertEqual(board.items[0].content, "規則優先")

    def test_board_mode_split_chunks(self):
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        chunks = [
            "[[SPE",
            "ECH]]\n",
            "第一句語音。",
            "第二句語音。",
            "\n[[BO",
            "ARD_JSON]]\n",
            '{"title": "專案清單", "items": [',
            '{"title": "項目一", "content": "內容一"},',
            '{"title": "項目二", "content": "內容二"}',
            "]}\n",
            "[[E",
            "ND]]",
        ]
        speech = []
        for c in chunks:
            speech.extend(parser.feed(c))
        flush_speech, board = parser.flush()
        all_speech = "".join(speech + flush_speech).strip()

        self.assertEqual(all_speech, "第一句語音。第二句語音。")
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "專案清單")
        self.assertEqual(len(board.items), 2)

    def test_first_speech_chunk_latency_guarantee(self):
        """Speech chunks must be yielded immediately without waiting for BOARD_JSON."""
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        first_feed = parser.feed("[[SPEECH]]\n首句即時輸出。")
        self.assertTrue(len(first_feed) > 0)
        self.assertIn("首句即時輸出。", "".join(first_feed))
        # Board JSON has not arrived yet
        self.assertIsNone(parser.board_payload)

    def test_board_markdown_fenced_json(self):
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        raw = (
            "[[SPEECH]]\n摘要回答\n"
            "[[BOARD_JSON]]\n"
            "```json\n"
            '{"title": "Fenced", "items": [{"title": "T", "content": "C"}]}\n'
            "```\n"
            "[[END]]"
        )
        speech = parser.feed(raw)
        flush_speech, board = parser.flush()
        self.assertEqual("".join(speech + flush_speech).strip(), "摘要回答")
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "Fenced")
        self.assertEqual(len(board.items), 1)

    def test_malformed_json_fallback_does_not_crash(self):
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        raw = (
            "[[SPEECH]]\n語音摘要正常生成。\n"
            "[[BOARD_JSON]]\n"
            "{malformed json, invalid\n"
            "[[END]]"
        )
        speech = parser.feed(raw)
        flush_speech, board = parser.flush()
        self.assertEqual("".join(speech + flush_speech).strip(), "語音摘要正常生成。")
        # Board parse failed safely, returns None, does not crash
        self.assertIsNone(board)

    def test_max_items_truncation(self):
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD, max_items=3)
        items_json = ", ".join(
            [f'{{"title": "Item {i}", "content": "Content {i}"}}' for i in range(10)]
        )
        raw = f'[[SPEECH]]\n短答\n[[BOARD_JSON]]\n{{"title": "10 items", "items": [{items_json}]}}\n[[END]]'
        parser.feed(raw)
        _, board = parser.flush()
        self.assertIsNotNone(board)
        self.assertEqual(len(board.items), 3)

    def test_model_omits_speech_tag(self):
        """Tolerate models that start directly with speech text."""
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        chunks = [
            "這是直接說出的語音內容，沒有 SPEECH 標記。\n",
            "[[BOARD_JSON]]\n",
            '{"title": "無標記看板", "items": [{"title": "A", "content": "B"}]}\n',
            "[[END]]",
        ]
        speech = []
        for c in chunks:
            speech.extend(parser.feed(c))
        flush_speech, board = parser.flush()
        all_speech = "".join(speech + flush_speech).strip()
        self.assertEqual(all_speech, "這是直接說出的語音內容，沒有 SPEECH 標記。")
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "無標記看板")

    def test_model_outputs_only_speech(self):
        """If model outputs only text without board markup, return all as speech."""
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        speech = parser.feed("模型只產出了純文字回答，沒有任何看板標記。")
        flush_speech, board = parser.flush()
        all_speech = "".join(speech + flush_speech).strip()
        self.assertEqual(all_speech, "模型只產出了純文字回答，沒有任何看板標記。")
        self.assertIsNone(board)


class EndToEndProtocolStreamingTests(unittest.TestCase):
    def test_generate_response_never_falls_back_to_suppressed_raw_json(self):
        class RawJsonLLM(BaseLLM):
            def chat_stream(self, message, system_prompt=None, **kwargs):
                del message, system_prompt, kwargs
                yield '{"tit'
                yield 'le":"建議","items":[]}'

        result = RawJsonLLM(Config()).generate_response(
            "請給我建議",
            stream_to_avatar=False,
            reply_mode=ReplyMode.SIMPLE,
        )

        self.assertEqual(result, FORMAT_RECOVERY_MESSAGE)
        self.assertNotIn('"title"', result)

    def test_board_mode_speech_streamed_to_avatar_board_sent_to_callback(self):
        class MockStreamingLLM(BaseLLM):
            def chat_stream(self, message, system_prompt=None, **kwargs):
                del message, system_prompt
                yield "<think>模型正在思考中</think>"
                yield "[[SPE"
                yield "ECH]]\n"
                yield "第一部分口語結論。"
                yield "第二部分口語補充。"
                yield "\n[[BOARD_JSON]]\n"
                yield '{"title": "建議架構", "summary": "說明", "items": ['
                yield '{"title": "第一點", "content": "詳細說明一"},'
                yield '{"title": "第二點", "content": "詳細說明二"}'
                yield "]}\n[[END]]"

        class RecordingAvatar:
            def __init__(self):
                self.fragments = []
                self.notified_chunks = []

            def put_msg_txt(self, text, datainfo=None):
                self.fragments.append(text)

            def notify_llm_chunk(self, text, eventpoint=None):
                self.notified_chunks.append(text)

        avatar = RecordingAvatar()
        board_events = []

        llm = MockStreamingLLM(Config())
        result = llm.generate_response(
            "請規劃架構",
            avatar,
            reply_mode=ReplyMode.BOARD,
            datainfo={
                "turn_id": "turn-test-1",
                "generation": 1,
                "on_board": board_events.append,
            },
        )

        # 1. Spoken result contains only the speech summary
        self.assertIn("第一部分口語結論", result)
        self.assertIn("第二部分口語補充", result)
        self.assertNotIn("[[SPEECH]]", result)
        self.assertNotIn("[[BOARD_JSON]]", result)
        self.assertNotIn("[[END]]", result)
        self.assertNotIn("<think>", result)
        self.assertNotIn("模型正在思考中", result)

        # 2. Avatar put_msg_txt never received board markup or think tags
        combined_avatar_text = "".join(avatar.fragments)
        self.assertNotIn("[[BOARD_JSON]]", combined_avatar_text)
        self.assertNotIn("[[SPEECH]]", combined_avatar_text)
        self.assertNotIn("模型正在思考中", combined_avatar_text)

        # 3. Board event was emitted with structured BoardPayload
        self.assertEqual(len(board_events), 1)
        board_data = board_events[0]
        self.assertEqual(board_data["title"], "建議架構")
        self.assertEqual(len(board_data["items"]), 2)
        self.assertEqual(board_data["items"][0]["title"], "第一點")
        self.assertEqual(board_data["items"][0]["content"], "詳細說明一")

        # 4. Generated board content is not follow-up context until rendered.
        last_board = llm.get_last_board()
        self.assertIsNone(last_board)
        self.assertTrue(
            llm.acknowledge_board_display(
                turn_id="turn-test-1",
                board_id="turn-test-1",
                item_index=0,
            )
        )
        last_board = llm.get_last_board()
        self.assertIsNotNone(last_board)
        self.assertEqual(last_board.title, "建議架構")

    def test_direct_json_without_board_tag_is_suppressed(self):
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        raw = (
            "[[SPEECH]]\n"
            "台灣歷史經歷了多個重要階段。\n\n"
            '{"title": "台灣歷史", "items": [{"title": "原住民時期", "content": "多元文化。"}]}\n'
            "[[END]]"
        )
        speech = parser.feed(raw)
        flush_speech, board = parser.flush()
        all_speech = "".join(speech + flush_speech).strip()
        self.assertEqual(all_speech, "台灣歷史經歷了多個重要階段。")
        self.assertIsNone(board)
        self.assertTrue(parser.structured_payload_suppressed)

    def test_tool_call_board_format_is_not_a_board_without_explicit_marker(self):
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO)
        raw = (
            "<|tool_call_start|>[BOARD(MODE='BOARD', SPEECH='部署步驟如下：', "
            "BOARD_JSON='{\"title\": \"部署步驟\", \"items\": [{\"title\": \"檢查網路\", \"content\": \"確認連通\"}]}')]<|tool_call_end|>"
        )
        speech = parser.feed(raw)
        flush_speech, board = parser.flush()
        all_speech = "".join(speech + flush_speech).strip()
        self.assertEqual(all_speech, "")
        self.assertIsNone(board)

    def test_json_double_bracket_repair(self):
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        raw = (
            "[[SPEECH]]\n"
            "簡要概述。\n"
            "[[BOARD_JSON]]\n"
            '{"title": "測試修復", "items": [{"title": "項目一", "content": "說明一"}]]}\n'
            "[[END]]"
        )
        speech = parser.feed(raw)
        _, board = parser.flush()
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "測試修復")
        self.assertEqual(len(board.items), 1)

    def test_markdown_bullets_are_not_promoted_to_a_board(self):
        parser = ResponseProtocolParser(mode=ReplyMode.BOARD)
        raw = (
            "[[SPEECH]]\n"
            "台灣歷史的整體結論。\n\n"
            "- 原住民時期：多元文化與傳統部落社會。\n"
            "- 清朝統治時期：設府開墾與行政發展。\n"
        )
        speech = parser.feed(raw)
        flush_speech, board = parser.flush()
        all_speech = "".join(speech + flush_speech).strip()
        self.assertEqual(all_speech, "台灣歷史的整體結論。")
        self.assertIsNone(board)
