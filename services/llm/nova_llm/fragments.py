# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""How the LLM layer hands spoken-text deltas to whoever cuts them into fragments.

The core decides where a playable fragment ends and how long to wait for a
semantic boundary. This layer only produces spoken-text deltas and feeds them
to the fragmenter it was given.
"""
from __future__ import annotations

from typing import Callable, Protocol


class FragmentStream(Protocol):
    """Receives spoken-text deltas and emits finished fragments."""

    def feed(self, text: str) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


# ``(emit, active) -> FragmentStream``: ``emit`` receives each finished
# fragment; ``active`` tells a timed release whether the turn is still live.
FragmenterFactory = Callable[[Callable[[str], None], Callable[[], bool]], FragmentStream]


class _PassthroughFragments:
    """Emit every delta as it arrives; used when the caller supplies no fragmenter."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit

    def feed(self, text: str) -> None:
        if text:
            self._emit(text)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def passthrough_fragmenter(
    emit: Callable[[str], None], active: Callable[[], bool],
) -> FragmentStream:
    del active
    return _PassthroughFragments(emit)
