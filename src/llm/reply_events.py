# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's review of the playable fragments the core cuts (ADR 0027).

The speech events and the ``FragmentReview`` Protocol this implements are in
``nova_contracts.llm``.
"""
from __future__ import annotations

from threading import RLock
from typing import Callable, Optional

from nova_contracts.llm import ReviewedFragment
from src.llm.text_normalizer import join_spoken_fragments


class SpokenTextReview:
    """The LLM's checks on a complete playable fragment before anyone hears it.

    Identity restrictions and the web-speech bound need a complete clause, so
    they run on the fragments the core cut. Accepted fragments make up the
    spoken answer. The core may call ``review`` from its timer thread.
    """

    def __init__(
        self,
        normalize: Callable[[str], str],
        identity_policy,
        web_guard=None,
    ) -> None:
        self._normalize = normalize
        self._identity_policy = identity_policy
        self._web_guard = web_guard
        self._spoken = ""
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
            self._spoken = join_spoken_fragments((self._spoken, text))
            return ReviewedFragment(text=text, preview=self._spoken[previous_length:])
