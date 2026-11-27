# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core's side of the LLM speech seam: cut, review and deliver fragments.

The LLM emits spoken-text deltas (``SpokenDelta``) and marks the end of its
spoken section (``SpeechEnd``). Here the core cuts playable reply fragments at
complete semantic boundaries, releases a waiting clause when the semantic wait
ends, asks the LLM to review each fragment, then hands it to the avatar with
its turn envelope (ADR 0007, ADR 0027).
"""
from __future__ import annotations

from typing import Callable, Optional

from nova_contracts.llm import FragmentReview, SpeechEnd, SpeechEvent
from src.server.reply_streaming.fragmenter import SemanticFragmenter, SemanticWaitTimer
from src.server.reply_streaming.sentence_fragmenter import TextStreamProcessor
from src.utils.logging import logger


class ReplySpeech:
    """Playable fragments of one answer, delivered to ``avatar``.

    With a turn envelope (``turn_id`` and ``generation``) fragments are cut
    semantically and carry a ``fragment_sequence``; without one, whole
    sentences are released for legacy callers. With no avatar nothing is
    played, but fragments still pass the review, which bounds web speech.
    """

    def __init__(
        self,
        avatar,
        envelope: dict,
        *,
        settings=None,
        chunk_guard: Optional[Callable[[int], bool]] = None,
    ) -> None:
        self._avatar = avatar
        self._envelope = dict(envelope)
        self._turn_aware = bool(
            self._envelope.get("turn_id") and self._envelope.get("generation") is not None
        )
        self._settings = settings
        self._chunk_guard = chunk_guard
        self._review: Optional[FragmentReview] = None
        self._semantic: Optional[SemanticWaitTimer] = None
        self._sentences: Optional[TextStreamProcessor] = None
        self._llm_sequence = -1
        self._fragment_sequence = 0
        self._closed = False

    def open(self, review: FragmentReview) -> None:
        self._review = review
        if self._turn_aware or review.bounded:
            # The semantic wait releases a long clause by timer even while the
            # model is silent; feeding, flushing and timed releases share one lock.
            self._semantic = SemanticWaitTimer(
                SemanticFragmenter(
                    weak_min_chars=self._setting("weak_min_chars", 24, int),
                    soft_limit_chars=self._setting("soft_limit_chars", 72, int),
                    hard_limit_chars=self._setting("hard_limit_chars", 120, int),
                    strong_min_chars=self._setting("strong_min_chars", 1, int),
                    semantic_wait_seconds=self._setting("semantic_wait_seconds", 0.5, float),
                ),
                self._deliver,
                active=self._live,
            )
        else:
            self._sentences = TextStreamProcessor()

    def send(self, event: SpeechEvent) -> None:
        if isinstance(event, SpeechEnd):
            # The end of SPEECH is a semantic boundary even if the model
            # omitted sentence punctuation.
            if self._semantic is not None:
                self._semantic.flush()
            elif self._sentences is not None:
                self._sentences.flush(self._deliver)
            return
        self._llm_sequence = event.llm_sequence
        avatar = self._avatar
        if avatar is not None:
            if event.text:
                _call(avatar, "mark_stage_end", "llm_first_speech")
            if self._turn_aware and self._review is not None and not self._review.previews_fragments:
                _call(avatar, "notify_llm_chunk", event.text, {
                    **self._envelope, "llm_sequence": event.llm_sequence,
                })
        if self._semantic is not None:
            self._semantic.feed(event.text)
        elif self._sentences is not None:
            self._sentences.process_chunk(event.text, self._deliver)

    def close(self) -> None:
        """Stop the semantic wait; nothing is delivered after this."""
        self._closed = True
        if self._semantic is not None:
            self._semantic.close()

    def _live(self) -> bool:
        """A timed release must see a fence without waiting for the next chunk."""
        return not self._closed and (
            self._chunk_guard is None or self._chunk_guard(max(self._llm_sequence, 0))
        )

    def _deliver(self, fragment: str) -> None:
        review = self._review
        reviewed = review.review(fragment) if review is not None else None
        avatar = self._avatar
        if reviewed is None or avatar is None:
            return
        if review is not None and review.previews_fragments:
            _call(avatar, "notify_llm_chunk", reviewed.preview, {
                **self._envelope, "llm_sequence": self._fragment_sequence,
            })
        info = dict(self._envelope)
        if self._turn_aware:
            info["fragment_sequence"] = self._fragment_sequence
            logger.info("Queueing turn-aware LLM fragment sequence=%d", self._fragment_sequence)
        else:
            logger.info("Queueing legacy LLM fragment")
        avatar.put_msg_txt(reviewed.text, info)
        self._fragment_sequence += 1

    def _setting(self, name: str, default, cast):
        return cast(getattr(self._settings, name, default) or default)


def _call(target, method: str, *args) -> None:
    function = getattr(target, method, None)
    if callable(function):
        function(*args)
