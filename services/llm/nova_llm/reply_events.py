# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's review of the playable fragments the core cuts (ADR 0027).

``review_fragment`` keeps no state: the core sends the answer's
``ReviewState`` with every fragment and keeps the one returned.
``SpokenTextReview`` is the same review held in process, for
``BaseLLM.generate_response``.
"""
from __future__ import annotations

from threading import RLock
from typing import Callable, Optional

from nova_contracts.llm import (
    AssistantProfile,
    FragmentReviewContext,
    FragmentVerdict,
    ReviewState,
    ReviewedFragment,
)
from src.llm.identity_policy import IdentityPolicy
from src.llm.text_normalizer import (
    normalize_assistant_identity,
    normalize_output_text,
    strip_unsolicited_self_introduction,
)
from src.llm.web_reply import WebSpeechGuard
from src.utils.spoken_text import join_spoken_fragments


def visible_text_normalizer(profile, user_message: str) -> Callable[[str], str]:
    """Locale, identity and self-introduction cleanup of text a visitor will see."""
    output_locale = str(getattr(profile, "output_locale", "zh-TW") or "zh-TW")
    enforce_locale = bool(getattr(profile, "enforce_output_locale", True))
    assistant_name = str(getattr(profile, "assistant_name", "") or "")
    forbidden_names = list(getattr(profile, "forbidden_self_names", []) or [])

    def normalize(text: str) -> str:
        normalized = normalize_assistant_identity(
            normalize_output_text(text, locale=output_locale, enabled=enforce_locale),
            assistant_name=assistant_name,
            forbidden_names=forbidden_names,
        )
        return strip_unsolicited_self_introduction(
            normalized, user_message=user_message, assistant_name=assistant_name
        )

    return normalize


def review_context(profile, *, model: str, question: str,
                   web_max_chars: Optional[int]) -> FragmentReviewContext:
    """What the core echoes back to have this answer's fragments reviewed."""
    return FragmentReviewContext(
        profile=AssistantProfile(
            assistant_name=str(getattr(profile, "assistant_name", "") or ""),
            system_prompt=str(getattr(profile, "system_prompt", "") or ""),
            restriction_prompt=str(getattr(profile, "restriction_prompt", "") or ""),
            output_locale=str(getattr(profile, "output_locale", "zh-TW") or "zh-TW"),
            enforce_output_locale=bool(getattr(profile, "enforce_output_locale", True)),
            forbidden_self_names=tuple(getattr(profile, "forbidden_self_names", ()) or ()),
        ),
        model=str(model or ""),
        question=str(question),
        web_max_chars=web_max_chars,
    )


def review_for(context: FragmentReviewContext,
               state: ReviewState = ReviewState()) -> "SpokenTextReview":
    """The review of one answer, resumed after the fragments ``state`` accepted."""
    policy = IdentityPolicy(context.profile, model=context.model, user_message=context.question)
    web_guard = None
    if context.web_max_chars is not None:
        web_guard = WebSpeechGuard.resumed(context.web_max_chars, state.accepted,
                                           stopped=state.stopped)
    return SpokenTextReview(visible_text_normalizer(context.profile, context.question),
                            policy, web_guard, accepted=state.accepted)


def review_fragment(context: FragmentReviewContext, state: ReviewState,
                    fragment: str) -> FragmentVerdict:
    """Identity restrictions and the web-speech bound on one complete fragment."""
    review = review_for(context, state)
    reviewed = review.review(fragment)
    return FragmentVerdict(
        fragment=reviewed,
        state=ReviewState(accepted=review.accepted, stopped=review.stopped),
        answer=review.answer,
    )


class SpokenTextReview:
    """The LLM's checks on a complete playable fragment before anyone hears it.

    Identity restrictions and the web-speech bound need a complete clause, so
    they run on the fragments the core cut. Accepted fragments make up the
    spoken answer. ``review`` may be called from a timer thread.
    """

    def __init__(
        self,
        normalize: Callable[[str], str],
        identity_policy,
        web_guard=None,
        *,
        accepted: tuple[str, ...] = (),
    ) -> None:
        self._normalize = normalize
        self._identity_policy = identity_policy
        self._web_guard = web_guard
        self._accepted = tuple(accepted)
        self._spoken = join_spoken_fragments(self._accepted)
        self._lock = RLock()

    @property
    def bounded(self) -> bool:
        """Web speech is bounded at playable fragments even when none is played."""
        return self._web_guard is not None

    @property
    def previews_fragments(self) -> bool:
        """The live transcript shows reviewed fragments, never raw deltas."""
        return bool(self._identity_policy.enabled) or self._web_guard is not None

    @property
    def spoken(self) -> str:
        with self._lock:
            return self._spoken

    @property
    def accepted(self) -> tuple[str, ...]:
        with self._lock:
            return self._accepted

    @property
    def stopped(self) -> bool:
        """The web bound was reached; nothing more is accepted."""
        return self._web_guard is not None and self._web_guard.stopped

    @property
    def answer(self) -> str:
        """The cleaned spoken answer made of every accepted fragment."""
        spoken = self.spoken.strip()
        return self._identity_policy.sanitize(self._normalize(spoken)) if spoken else ""

    def review(self, fragment: str) -> Optional[ReviewedFragment]:
        """Return the fragment to play, or ``None`` when it must stay silent."""
        if not fragment:
            return None
        with self._lock:
            policy = self._identity_policy
            text = policy.sanitize(self._normalize(fragment), identity_already_visible=bool(
                policy.name and policy.name.casefold() in self._spoken.casefold()
            ))
            if not text:
                return None
            if self._web_guard is not None and not self._web_guard.accept(text):
                return None
            previous_length = len(self._spoken)
            self._accepted += (text,)
            self._spoken = join_spoken_fragments((self._spoken, text))
            return ReviewedFragment(text=text, preview=self._spoken[previous_length:])
