# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Answer-model (LLM) layer contract.

Loopback shape (spec decision 7): the reply streams as server-sent events, one
tagged ``SpeechEvent`` (or other reply event) per message. The LLM emits
spoken-text deltas in model order; it does not cut playable fragments. The
core cuts complete semantic boundaries, applies the semantic wait and owns
back pressure, then has each fragment reviewed before it is played.

Ticket 07 step 2 adds ``LlmService``, its DTOs and ``HTTP_API`` here.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Protocol, Union

from pydantic import Field

from nova_contracts.common import ContractModel


class SpokenDelta(ContractModel):
    """A spoken-text increment from one model chunk; not a playable fragment."""

    type: Literal["spoken_delta"] = "spoken_delta"
    text: str
    llm_sequence: int


class SpeechEnd(ContractModel):
    """The spoken section is complete: a boundary even without punctuation."""

    type: Literal["speech_end"] = "speech_end"


SpeechEvent = Annotated[Union[SpokenDelta, SpeechEnd], Field(discriminator="type")]


class ReviewedFragment(ContractModel):
    """A playable fragment the LLM accepted, with its live-transcript increment."""

    text: str
    preview: str


class FragmentReview(Protocol):
    """The LLM's check on each complete playable fragment the core cut.

    The core may call ``review`` from its timer thread.
    """

    @property
    def bounded(self) -> bool:
        """Web speech is bounded at playable fragments even when none is played."""
        ...

    @property
    def previews_fragments(self) -> bool:
        """The live transcript shows reviewed fragments, never raw deltas."""
        ...

    def review(self, fragment: str) -> Optional[ReviewedFragment]:
        """Return the fragment to play, or ``None`` when it must stay silent."""
        ...


class SpeechSink(Protocol):
    """The core's consumer of one answer's speech."""

    def open(self, review: FragmentReview) -> None: ...

    def send(self, event: SpeechEvent) -> None: ...

    def close(self) -> None: ...


__all__ = [
    "FragmentReview",
    "ReviewedFragment",
    "SpeechEnd",
    "SpeechEvent",
    "SpeechSink",
    "SpokenDelta",
]
