# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""An offline LLM engine that answers with fixed text (selected by ``llm.engine: fake``).

The engine replaces only the model: it streams a scripted answer in the reply
protocol, so the layer's parser, review, board events and conversation memory
run exactly as they do for a real model. It never opens a network connection
and is not an endpoint, so no console list offers it.
"""
from __future__ import annotations

from typing import Callable, Generator, Iterable, Optional, Union

from src.llm.engines.openai import OpenAILLM

# The default answer: a spoken sentence and a two-item board, in two chunks so
# a reply has a chunk boundary for the core to cancel at.
SPOKEN_ANSWER = "這是固定的測試回覆。"
BOARD_TITLE = "固定看板"
DEFAULT_CHUNKS = (
    "[[MODE:BOARD]]\n[[SPEECH]]\n" + SPOKEN_ANSWER[:5],
    SPOKEN_ANSWER[5:] + "\n[[BOARD_JSON]]\n"
    '{"title":"' + BOARD_TITLE + '","summary":"兩個項目",'
    '"items":[{"title":"項目一","content":"第一個項目。"},'
    '{"title":"項目二","content":"第二個項目。"}]}\n[[END]]',
)


def answer_chunks(text: str) -> tuple[str, ...]:
    """The reply protocol of a simple answer saying ``text``, as one model chunk.

    An empty answer is a model that streams nothing.
    """
    return (f"[[MODE:SIMPLE]]\n[[SPEECH]]\n{text}\n[[END]]",) if text else ()


Chunks = Union[Iterable[str], Callable[[str], Iterable[str]]]


class FakeLLM(OpenAILLM):
    """The model's chunks come from ``chunks``: reply-protocol text chunks, or a function of the message."""

    def __init__(self, *args, chunks: Optional[Chunks] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.chunks = DEFAULT_CHUNKS if chunks is None else chunks

    def chat_stream(self, message: str, system_prompt: Optional[str] = None, *,
                    history_transaction=None) -> Generator[str, None, None]:
        chunks = self.chunks(message) if callable(self.chunks) else self.chunks
        yield from chunks
