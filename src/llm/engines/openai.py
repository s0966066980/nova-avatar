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
from src.llm.llamacpp_protocol import is_lfm25_reasoning
from src.llm.reply_contract import auto_reply_grammar
from src.llm.context_usage import (
    ContextCapacityError, cached_capacity, measure_request, with_input_tokens,
)


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
        conversation = getattr(config, "conversation", None)
        self._history.set_limit(int(getattr(conversation, "history_max_messages", max_history * 2)))
        self.context_usage = None
        self.observe_context = True
        
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
        self.max_tokens = response_token_budget(self.response_max_chars)

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
        self.context_usage = None
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
        
        completion = None
        try:
            extra_body = dict(self.extra_body)
            temperature = 0.6
            llm_cfg = getattr(self.config, "llm", None)
            if getattr(llm_cfg, "provider", "") == "llamacpp":
                thinking = is_lfm25_reasoning(self.model)
                board_cfg = getattr(llm_cfg, "board", None)
                grammar = auto_reply_grammar(
                    system_prompt, max_items=getattr(board_cfg, "max_items", 8),
                    thinking=thinking,
                )
                if grammar:
                    # The protocol is system-owned; stale custom grammars must
                    # not replace it when the console switches models.
                    extra_body["grammar"] = grammar
                    temperature = 0.0
                if thinking:
                    extra_body.setdefault("repeat_penalty", 1.1)
                    if not grammar:
                        temperature = 0.1
            # 構建完整的訊息列表：system + 歷史對話
            messages = [{'role': 'system', 'content': system_prompt}]
            if history_transaction is None:
                messages.extend(self._history.preview_messages(message))
            else:
                messages.extend(self._history.request_messages(history_transaction))
            request_message = history_transaction.user_text if history_transaction is not None else message
            if hasattr(request_message, 'parts'):
                messages[-1] = {**messages[-1], 'content': list(request_message.parts)}
            profile = getattr(llm_cfg, 'assistant_profile', None)
            if getattr(profile, 'output_locale', 'zh-TW') == 'en-US':
                # Reinforce the session policy beside the current question. This
                # is a request-only copy; never rewrite retained user messages.
                content = messages[-1]['content']
                hint = '\n\n[Session language: English. Answer in English.]'
                messages[-1] = {**messages[-1], 'content': (
                    [*content, {'type': 'text', 'text': hint}] if isinstance(content, list) else content + hint)}
            
            logger.info(f"Sending {len(messages)} messages to LLM (including system prompt and history)")
            local = getattr(llm_cfg, 'provider', '') == 'llamacpp'
            if self.observe_context:
                # Never ask the model server before the answer: the size is
                # cached per model load and provider usage arrives with the
                # reply. An overflow is the provider's error, handled below.
                self.context_usage = measure_request(
                    messages, self.max_tokens, model=self.model,
                    capacity=cached_capacity(self.base_url) if local else None,
                )
            
            # 採用 OpenAI 相容流式介面，逐塊返回內容
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_tokens=self.max_tokens,
                temperature=temperature,
                extra_body=extra_body or None,
                **({'stream_options': {'include_usage': True}}
                   if getattr(llm_cfg, 'provider', '') == 'llamacpp' else {}),
            )
            
            init_time = time.perf_counter()
            logger.info(f"LLM initialization time: {init_time - start_time:.3f}s")
            
            for chunk in completion:
                usage = getattr(chunk, 'usage', None)
                if self.context_usage is not None and usage is not None and isinstance(getattr(usage, 'prompt_tokens', None), int):
                    self.context_usage.update(estimated=False, source='provider usage',
                                              visual_tokens_unknown=False)
                    if local and self.context_usage['capacity'] is None:
                        # A background refresh may have finished during the reply.
                        self.context_usage['capacity'] = cached_capacity(self.base_url)
                    with_input_tokens(self.context_usage, usage.prompt_tokens)
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
            code = str(getattr(e, 'code', '') or '')
            # llama.cpp names the overflow in the error type, with code 400.
            if (code in {'context_length_exceeded', 'context_window_exceeded'}
                    or getattr(e, 'type', None) == 'exceed_context_size_error'):
                if history_transaction is not None:
                    self._history.abort(history_transaction)
                raise ContextCapacityError('context_capacity') from e
            logger.error("LLM API failed: %s", type(e).__name__)
            raise
        except Exception as e:
            logger.error("Unexpected LLM failure: %s", type(e).__name__)
            raise
        finally:
            # Cancellation and prewarm must release the HTTP stream too.
            close = getattr(completion, "close", None)
            if callable(close):
                close()
