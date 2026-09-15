import unittest

from src.config.schema import Config
from src.llm.base import BaseLLM
from src.llm.router import ReplyMode
from src.llm.text_normalizer import (
    normalize_assistant_identity,
    normalize_output_text,
    strip_unsolicited_self_introduction,
)


class TextNormalizerTests(unittest.TestCase):
    def test_zh_tw_conversion_preserves_english_and_code(self):
        result = normalize_output_text("这个软件支持视频和用户数据。OpenAI API 使用 Python FastAPI。")
        self.assertEqual(result, "這個軟體支援視訊和使用者資料。OpenAI API 使用 Python FastAPI。")

    def test_disabled_or_other_locale_is_unchanged(self):
        self.assertEqual(normalize_output_text("软件", enabled=False), "软件")
        self.assertEqual(normalize_output_text("软件", locale="en-US"), "软件")

    def test_identity_guard_only_handles_self_identification(self):
        self.assertEqual(
            normalize_assistant_identity("我是 Linly 數位人助手。", assistant_name="ITRI 助手", forbidden_names=["Linly"]),
            "我是 ITRI 助手。",
        )
        self.assertEqual(
            normalize_assistant_identity("Nova Avatar 是一個數位人專案。", assistant_name="ITRI 助手", forbidden_names=["Nova Avatar"]),
            "Nova Avatar 是一個數位人專案。",
        )

    def test_unsolicited_identity_is_removed_but_identity_answer_is_preserved(self):
        reply = "我是 ITRI 助手，很高興為您服務。今天氣溫適中。"
        self.assertEqual(
            strip_unsolicited_self_introduction(
                reply, user_message="今天天氣如何？", assistant_name="ITRI 助手"
            ),
            "今天氣溫適中。",
        )
        self.assertEqual(
            strip_unsolicited_self_introduction(
                reply, user_message="你是誰？", assistant_name="ITRI 助手"
            ),
            reply,
        )

    def test_response_pipeline_normalizes_speech_board_and_history(self):
        class FakeLLM(BaseLLM):
            def __init__(self, config):
                super().__init__(config)
                self.committed = []

            def chat_stream(self, message, system_prompt=None, **kwargs):
                yield '[[SPEECH]]这个软件支持视频。[[BOARD_JSON]]{"title":"软件功能","items":[{"title":"视频","content":"支持用户数据"}]}[[END]]'

            def begin_history_turn(self, message, *, turn_id):
                return turn_id

            def commit_history_turn(self, transaction, *, assistant_text, terminal_reason):
                self.committed.append(assistant_text)

        config = Config()
        config.llm.assistant_profile.system_prompt = "請回答。"
        config.llm.assistant_profile.output_locale = "zh-TW"
        config.llm.assistant_profile.enforce_output_locale = True
        boards = []
        llm = FakeLLM(config)
        spoken = llm.generate_response(
            "測試", stream_to_avatar=False, reply_mode=ReplyMode.BOARD,
            datainfo={"on_board": boards.append},
        )
        self.assertEqual(spoken, "這個軟體支援視訊。")
        self.assertEqual(llm.committed, ["這個軟體支援視訊。"])
        self.assertEqual(boards[0]["title"], "軟體功能")
        self.assertEqual(boards[0]["items"][0]["title"], "視訊")
        self.assertEqual(boards[0]["items"][0]["content"], "支援使用者資料")
