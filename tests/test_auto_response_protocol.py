import unittest

from src.llm.prompts import compose_system_prompt
from src.llm.response_protocol import ResponseProtocolParser
from src.llm.router import ReplyMode


class AutoResponseProtocolTests(unittest.TestCase):
    def test_auto_prompt_declares_the_complete_board_schema(self):
        prompt = compose_system_prompt(
            "You are a helpful assistant.",
            reply_mode=ReplyMode.AUTO,
        )

        self.assertIn("[[MODE:BOARD]]", prompt)
        self.assertIn("[[SPEECH]]", prompt)
        self.assertIn("[[BOARD_JSON]]", prompt)
        self.assertIn("title (string)", prompt)
        self.assertIn("items (array)", prompt)
        self.assertIn("content (string)", prompt)
        self.assertIn("Do not use JSON keys named steps, step, description", prompt)
        self.assertIn("看板資料格式不是回答內容", prompt)
        self.assertIn("不是工具呼叫", prompt)
        self.assertIn("【口語與看板分工】", prompt)
        self.assertIn("一個流程裡的多個步驟", prompt)
        self.assertNotIn("台灣歷史", prompt)

    def test_auto_prompt_states_the_effective_board_item_limit(self):
        prompt = compose_system_prompt(
            "You are a helpful assistant.",
            reply_mode=ReplyMode.AUTO,
            board_max_items=6,
        )

        self.assertIn("看板最多 6 項", prompt)

    def test_auto_prompt_scopes_list_ban_to_speech(self):
        prompt = compose_system_prompt(
            "避免使用列表、序號等不適合語音播報的格式。不要展開太多細節。",
            reply_mode=ReplyMode.AUTO,
            rules={
                "activation": "兩個重點用看板。",
                "speech": "口語簡短。",
                "board": "條列清楚。",
            },
        )

        self.assertIn("那些要求只約束 [[SPEECH]] 口語", prompt)
        self.assertIn("不得因此改成簡答而省略看板", prompt)
        self.assertNotIn("這些規則是呈現偏好", prompt)

    def test_auto_simple_then_board_json_is_recovered(self):
        modes = []
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO, on_mode=modes.append)
        spoken = []
        for chunk in (
            "[[MODE:SIMPLE]]\n[[SPEECH]]流程有幾個階段，請看下方看板。\n",
            '[[BOARD_JSON]]{"title":"專案流程","items":['
            '{"title":"開案","content":"確認需求。"},'
            '{"title":"結案","content":"驗收交付。"}]}[[END]]',
        ):
            spoken.extend(parser.feed(chunk))
        tail, board = parser.flush()
        spoken.extend(tail)

        self.assertEqual(modes[-1], ReplyMode.BOARD)
        self.assertIn("流程有幾個階段", "".join(spoken))
        self.assertNotIn("BOARD_JSON", "".join(spoken))
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "專案流程")
        self.assertEqual(len(board.items), 2)

    def test_auto_simple_mode_marker_is_confirmed_once(self):
        modes = []
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO, on_mode=modes.append)
        spoken = []
        for chunk in ("[[MODE:SIMP", "LE]][[SPEECH]]你好。[[END]]"):
            spoken.extend(parser.feed(chunk))
        spoken.extend(parser.flush()[0])
        self.assertEqual(modes, [ReplyMode.SIMPLE])
        self.assertIn("你好。", "".join(spoken))
        self.assertNotIn("MODE", "".join(spoken))

    def test_auto_simple_ignores_whitespace_chunk_before_speech_marker(self):
        """llama.cpp may emit the newline and speech marker as separate chunks."""
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO)
        spoken = []
        for chunk in (
            "[[MODE:SIMPLE]]",
            "\n",
            "[[",
            "S",
            "PE",
            "ECH",
            "]]",
            "\n你好。",
            "[[END]]",
        ):
            spoken.extend(parser.feed(chunk))
        tail, board = parser.flush()
        spoken.extend(tail)

        self.assertEqual("".join(spoken).strip(), "你好。")
        self.assertIsNone(board)

    def test_auto_board_mode_marker_parses_board_without_speaking_json(self):
        modes = []
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO, on_mode=modes.append)
        chunks = [
            "[[MODE:BOARD]][[SPEECH]]先說結論。[[BOARD_JSON]]",
            '{"title":"步驟","items":[{"title":"第一步","content":"執行它"}]}[[END]]',
        ]
        spoken = []
        for chunk in chunks:
            spoken.extend(parser.feed(chunk))
        _, board = parser.flush()
        self.assertEqual(modes, [ReplyMode.BOARD])
        self.assertEqual("".join(spoken), "先說結論。")
        self.assertIsNotNone(board)
        self.assertEqual(board.items[0].title, "第一步")

    def test_auto_chinese_board_mode_is_selected_only_from_model_output(self):
        modes = []
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO, on_mode=modes.append)
        spoken = []
        for chunk in (
            "模式：看板\n口語：台灣歷史可分為數個重要階段。\n資料：",
            '{"title":"台灣歷史","items":[{"title":"原住民社會","content":"多元族群長期生活於此。"}]}',
        ):
            spoken.extend(parser.feed(chunk))
        _, board = parser.flush()

        self.assertEqual(modes, [ReplyMode.BOARD])
        self.assertEqual("".join(spoken), "台灣歷史可分為數個重要階段。\n")
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "台灣歷史")

    def test_auto_board_marker_after_a_short_model_preamble_stays_a_board(self):
        """A small model may state intent before emitting its required marker."""
        modes = []
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO, on_mode=modes.append)
        spoken = []
        for chunk in (
            "我會按時期整理：",
            "[[MODE:BOARD]][[SPEECH]]台灣歷史可分為數個重要階段。"
            '[[BOARD_JSON]]{"title":"台灣歷史","items":['
            '{"title":"原住民社會","content":"多元族群長期生活於此。"}'
            "]}[[END]]",
        ):
            spoken.extend(parser.feed(chunk))
        _, board = parser.flush()

        self.assertEqual(modes, [ReplyMode.BOARD])
        self.assertEqual("".join(spoken), "台灣歷史可分為數個重要階段。")
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "台灣歷史")

    def test_auto_board_marker_after_a_long_model_preamble_stays_a_board(self):
        modes = []
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO, on_mode=modes.append)
        spoken = []
        preamble = "我會先整理需求再提供條理分明的看板內容。" * 12
        for chunk in (
            preamble,
            '[[MODE:BOARD]][[SPEECH]]摘要。[[BOARD_JSON]]'
            '{"title":"T","items":[{"title":"A","content":"B"}]}[[END]]',
        ):
            spoken.extend(parser.feed(chunk))
        tail, board = parser.flush()
        spoken.extend(tail)

        self.assertEqual(modes, [ReplyMode.BOARD])
        self.assertEqual("".join(spoken), "摘要。")
        self.assertIsNotNone(board)
        self.assertEqual(board.title, "T")

    def test_auto_inline_board_json_without_marker_never_becomes_speech(self):
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO)
        spoken = parser.feed(
            '一般摘要。 {"title":"T","items":[{"title":"A","content":"B"}]}'
        )
        tail, board = parser.flush()
        spoken.extend(tail)

        self.assertEqual("".join(spoken), "一般摘要。")
        self.assertIsNone(board)

    def test_auto_unmarked_text_falls_back_to_simple_when_flushed(self):
        parser = ResponseProtocolParser(mode=ReplyMode.AUTO)
        self.assertEqual(parser.feed("沒有模式標記的短答。"), [])
        spoken, board = parser.flush()
        self.assertEqual("".join(spoken), "沒有模式標記的短答。")
        self.assertIsNone(board)

    def test_board_items_are_emitted_after_each_complete_json_object(self):
        items = []
        parser = ResponseProtocolParser(
            mode=ReplyMode.BOARD,
            on_board_item=lambda index, item: items.append((index, item.title)),
        )
        parser.feed('[[SPEECH]]摘要[[BOARD_JSON]]{"title":"T","items":[')
        parser.feed('{"title":"一","content":"A"},')
        self.assertEqual(items, [(0, "一")])
        parser.feed('{"title":"二","content":"B"}] }[[END]]')
        parser.flush()
        self.assertEqual(items, [(0, "一"), (1, "二")])


if __name__ == "__main__":
    unittest.main()
