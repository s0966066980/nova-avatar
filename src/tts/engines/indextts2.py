# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

from __future__ import annotations

import os
import time

import numpy as np
import resampy
import soundfile as sf

from src.tts.base import BaseTTS, State
from src.utils.logging import logger


class IndexTTS2(BaseTTS):
    def __init__(self, config, parent):
        super().__init__(config, parent)
        # IndexTTS2 配置引數
        self.server_url = config.tts.tts_server  # Gradio伺服器地址
        self.ref_audio_path = config.tts.ref_file  # 參考音訊檔案路徑
        self.max_tokens = getattr(config.tts, "max_tokens", 120)  # 最大token數

        # 初始化Gradio客戶端
        try:
            from gradio_client import Client, handle_file

            self.client = Client(self.server_url)
            self.handle_file = handle_file
            logger.info(f"IndexTTS2 Gradio客戶端初始化成功: {self.server_url}")
        except ImportError:
            logger.error("IndexTTS2 需要安裝 gradio_client: pip install gradio_client")
            raise
        except Exception as e:
            logger.error(f"IndexTTS2 Gradio客戶端初始化失敗: {e}")
            raise

    def txt_to_audio(self, msg):
        text, textevent = msg
        try:
            # 先進行文本分割
            segments = self.split_text(text)
            if not segments:
                logger.error("IndexTTS2 文本分割失敗")
                return

            logger.info(f"IndexTTS2 文本分割為 {len(segments)} 個片段")

            # 迴圈生成每個片段的音訊
            for i, segment_text in enumerate(segments):
                if self.state != State.RUNNING:
                    break

                logger.info(f"IndexTTS2 正在生成第 {i+1}/{len(segments)} 段音訊...")
                audio_file = self.indextts2_generate(segment_text)

                if audio_file:
                    segment_msg = (segment_text, textevent)
                    self.file_to_stream(
                        audio_file,
                        segment_msg,
                        is_first=(i == 0),
                        is_last=(i == len(segments) - 1),
                    )
                else:
                    logger.error(f"IndexTTS2 第 {i+1} 段音訊生成失敗")

        except Exception as e:
            logger.exception(f"IndexTTS2 txt_to_audio 錯誤: {e}")

    def split_text(self, text):
        """使用 IndexTTS2 API 分割文本"""
        try:
            logger.info(f"IndexTTS2 開始分割文本，長度: {len(text)}")

            result = self.client.predict(
                text=text,
                max_text_tokens_per_segment=self.max_tokens,
                api_name="/on_input_text_change",
            )

            if "value" in result and "data" in result["value"]:
                data = result["value"]["data"]
                logger.info(f"IndexTTS2 共分割為 {len(data)} 個片段")

                segments = []
                for i, item in enumerate(data):
                    序號 = item[0] + 1
                    分句內容 = item[1]
                    token數 = item[2]
                    logger.info(f"片段 {序號}: {len(分句內容)} 字元, {token數} tokens")
                    segments.append(分句內容)

                return segments
            else:
                logger.error(f"IndexTTS2 文本分割結果格式異常: {result}")
                return [text]

        except Exception as e:
            logger.exception(f"IndexTTS2 文本分割失敗: {e}")
            return [text]

    def indextts2_generate(self, text):
        """呼叫 IndexTTS2 Gradio API 生成語音"""
        start = time.perf_counter()

        try:
            result = self.client.predict(
                emo_control_method="Same as the voice reference",
                prompt=self.handle_file(self.ref_audio_path),
                text=text,
                emo_ref_path=self.handle_file(self.ref_audio_path),
                emo_weight=0.8,
                vec1=0.5,
                vec2=0,
                vec3=0,
                vec4=0,
                vec5=0,
                vec6=0,
                vec7=0,
                vec8=0,
                emo_text="",
                emo_random=False,
                max_text_tokens_per_segment=self.max_tokens,
                param_16=True,
                param_17=0.8,
                param_18=30,
                param_19=0.8,
                param_20=0,
                param_21=3,
                param_22=10,
                param_23=1500,
                api_name="/gen_single",
            )

            end = time.perf_counter()
            logger.info(f"IndexTTS2 片段生成完成，耗時: {end-start:.2f}s")

            if "value" in result:
                audio_file = result["value"]
                return audio_file
            else:
                logger.error(f"IndexTTS2 結果格式異常: {result}")
                return None

        except Exception as e:
            logger.exception(f"IndexTTS2 API呼叫失敗: {e}")
            return None

    def file_to_stream(self, audio_file, msg, is_first=False, is_last=False):
        """將音訊檔案轉換為音訊流"""
        text, textevent = msg

        try:
            stream, sample_rate = sf.read(audio_file)
            logger.info(f"IndexTTS2 音訊檔案 {sample_rate}Hz: {stream.shape}")

            stream = stream.astype(np.float32)

            if stream.ndim > 1:
                logger.info(f"IndexTTS2 音訊有 {stream.shape[1]} 個聲道，只使用第一個")
                stream = stream[:, 0]

            if sample_rate != self.sample_rate and stream.shape[0] > 0:
                logger.info(f"IndexTTS2 重取樣: {sample_rate}Hz -> {self.sample_rate}Hz")
                stream = resampy.resample(
                    x=stream, sr_orig=sample_rate, sr_new=self.sample_rate
                )

            streamlen = stream.shape[0]
            idx = 0
            first_chunk = True

            while streamlen >= self.chunk and self.state == State.RUNNING:
                eventpoint = None

                if is_first and first_chunk:
                    eventpoint = {"status": "start", "text": text, "msgevent": textevent}
                    first_chunk = False

                self.parent.put_audio_frame(stream[idx : idx + self.chunk], eventpoint)
                idx += self.chunk
                streamlen -= self.chunk

            if is_last:
                eventpoint = {"status": "end", "text": text, "msgevent": textevent}
                self.parent.put_audio_frame(np.zeros(self.chunk, np.float32), eventpoint)

            try:
                if os.path.exists(audio_file):
                    os.remove(audio_file)
                    logger.info(f"IndexTTS2 已刪除臨時檔案: {audio_file}")
            except Exception as e:
                logger.warning(f"IndexTTS2 刪除臨時檔案失敗: {e}")

        except Exception as e:
            logger.exception(f"IndexTTS2 音訊流處理失敗: {e}")
