# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""Whole-sentence fragmenting for replies that are not turn-aware."""

# 只在完整句尾切給 TTS。逗號與冒號屬於句內停頓，拆開合成會重置韻律，
# 也會讓 Avatar 在相鄰 TTS 請求之間提前填入靜音幀。
SENTENCE_DELIMITERS = ".!?;。！？；"
MIN_SENTENCE_LENGTH = 24


class TextStreamProcessor:
    """文本流處理器，負責分句和緩衝"""

    def __init__(self, delimiters: str = SENTENCE_DELIMITERS, min_length: int = MIN_SENTENCE_LENGTH):
        self.delimiters = delimiters
        self.min_length = min_length
        self.buffer = ""

    def process_chunk(self, text: str, callback) -> None:
        if not text:
            return

        # 以標點為分隔符，儘量保持語義完整再發給 TTS
        last_pos = 0
        for i, char in enumerate(text):
            if char in self.delimiters:
                sentence = self.buffer + text[last_pos:i + 1]
                last_pos = i + 1

                if len(sentence) >= self.min_length:
                    callback(sentence)
                    self.buffer = ""
                else:
                    self.buffer = sentence

        self.buffer += text[last_pos:]

    def flush(self, callback) -> None:
        if self.buffer:
            callback(self.buffer)
            self.buffer = ""
