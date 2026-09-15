# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""OpenAI 相容的 LLM 引擎"""

from __future__ import annotations

import time
from typing import Generator, Optional

from openai import OpenAI, OpenAIError

from src.llm.base import (
    BaseLLM,
    DEFAULT_RESPONSE_MAX_CHARS,
    response_token_budget,
    validate_response_max_chars,
    with_response_length_instruction,
)
from src.utils.logging import logger
from src.llm.history import HistoryTransaction, TransactionalHistory


class OpenAILLM(BaseLLM):
    """OpenAI 相容的 LLM 引擎，支援 OpenAI/DashScope/vLLM/Ollama 等"""
    
    def __init__(
        self, 
        config=None, 
        parent=None,
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen-plus",
        max_history: int = 10  # 最大儲存的對話輪次
    ):
        super().__init__(config, parent)
        
        if not api_key:
            raise ValueError("api_key is required")
        
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.max_history = max_history
        self._history = TransactionalHistory(max_turns=max_history)
        
        # 從配置讀取額外請求體引數（如 Ollama 的 reasoning_effort）
        llm_cfg = getattr(config, "llm", None) if config is not None else None
        extra = dict(getattr(llm_cfg, "extra_body", None) or {})
        if getattr(llm_cfg, "provider", "") == "llamacpp":
            extra.pop("reasoning_effort", None)
            extra.pop("think", None)
            extra.pop("keep_alive", None)
            extra.pop("options", None)
        self.extra_body = extra
        self.response_max_chars = validate_response_max_chars(
            getattr(llm_cfg, "response_max_chars", DEFAULT_RESPONSE_MAX_CHARS)
        )
        # The configurable character limit applies to speech only. A board
        # response needs room for its JSON items and fixed protocol markers.
        self.max_tokens = max(1024, response_token_budget(self.response_max_chars))

        logger.info(
            f"LLM initialized: model={self.model}, base_url={self.base_url}"
            + (f", extra_body={self.extra_body}" if self.extra_body else "")
        )
        self._client: Optional[OpenAI] = None
    
    @property
    def client(self) -> OpenAI:
        if self._client is None:
            # 延遲建立客戶端，避免無效配置時提前報錯
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client
    
    def add_to_history(self, role: str, content: str):
        """新增訊息到對話歷史"""
        self._history.append_message(role, content)
        
        logger.debug(f"Added to history: {role}, history length: {len(self.conversation_history)}")

    @property
    def conversation_history(self) -> list[dict[str, str]]:
        return self._history.snapshot()

    def begin_history_turn(self, message: str, *, turn_id: str) -> HistoryTransaction:
        return self._history.begin(message, turn_id=turn_id)

    def commit_history_turn(
        self,
        transaction: HistoryTransaction,
        *,
        assistant_text: str,
        terminal_reason: str,
    ) -> None:
        self._history.commit(
            transaction,
            assistant_text=assistant_text,
            terminal_reason=terminal_reason,
        )

    def commit_pending_history_turn(
        self,
        turn_id: str,
        *,
        assistant_text: str,
        terminal_reason: str,
    ) -> bool:
        return self._history.commit_pending(
            turn_id,
            assistant_text=assistant_text,
            terminal_reason=terminal_reason,
        )
    
    def clear_history(self):
        """清空對話歷史"""
        self._history.clear()
        logger.info("Conversation history cleared")
    
    def chat_stream(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        *,
        history_transaction: Optional[HistoryTransaction] = None,
    ) -> Generator[str, None, None]:
        start_time = time.perf_counter()
        if system_prompt is None:
            system_prompt = with_response_length_instruction(
                self.system_prompt,
                self.response_max_chars,
            )
        
        try:
            # 構建完整的訊息列表：system + 歷史對話
            messages = [{'role': 'system', 'content': system_prompt}]
            if history_transaction is None:
                messages.extend(self._history.preview_messages(message))
            else:
                messages.extend(self._history.request_messages(history_transaction))
            
            logger.info(f"Sending {len(messages)} messages to LLM (including system prompt and history)")
            
            # 採用 OpenAI 相容流式介面，逐塊返回內容
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_tokens=self.max_tokens,
                temperature=0.6,
                extra_body=self.extra_body or None,
            )
            
            init_time = time.perf_counter()
            logger.info(f"LLM initialization time: {init_time - start_time:.3f}s")
            
            for chunk in completion:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None) if delta is not None else None
                if content:
                    yield content
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason:
                    logger.info(
                        "LLM finish_reason=%s max_tokens=%s target_chars=%s",
                        finish_reason,
                        self.max_tokens,
                        self.response_max_chars,
                    )
            
        except OpenAIError as e:
            logger.error("LLM API failed: %s", type(e).__name__)
            raise
        except Exception as e:
            logger.error("Unexpected LLM failure: %s", type(e).__name__)
            raise
