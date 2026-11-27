# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Keep each peer's media and replay receipts within its own conversation."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

DISPLAY_EVENTS = {
    "user_transcript", "assistant_fragment", "assistant_response_mode",
    "assistant_board", "board_begin", "board_item", "board_end", "board_clear",
    "speaking_start", "speaking_end", "state", "turn_cancelled", "turn_committed",
    "conversation_reset", "role_clear", "role_handoff", "answer_clear",
}
RESET_EVENTS = {"conversation_reset", "role_clear"}


@dataclass
class _Source:
    voice: object
    events: deque = field(default_factory=lambda: deque(maxlen=128))
    fragments: deque = field(default_factory=deque)
    fragment_chars: int = 0
    turn_id: str | None = None


class SessionPresentation:
    """Replay only a peer's own events; its HumanPlayer owns both RTP tracks."""

    def __init__(self, state):
        self.sources = {}

    def register(self, voice, player):
        self.sources[voice.sessionid] = _Source(voice)
        voice._presentation = self
        return player.audio, player.video

    def replay(self, voice):
        source = self.sources.get(voice.sessionid)
        if source is None:
            return
        voice._send_event({"type": "presentation_reset", "turn_id": None})
        first = {"user_transcript", "assistant_response_mode"}
        events = [e for e in source.events if e["type"] in first]
        events.extend(source.fragments)
        events.extend(e for e in source.events if e["type"] not in first)
        for event in events:
            voice._send_event({**event, "replay": True})

    def publish(self, voice, event):
        source = self.sources.get(voice.sessionid)
        if source is not None and event["type"] in DISPLAY_EVENTS:
            self._remember(source, event)
        voice._send_event(event)

    @staticmethod
    def _remember(source, event):
        turn_id = event.get("turn_id")
        if event["type"] in RESET_EVENTS or (turn_id and turn_id != source.turn_id):
            source.events.clear()
            source.fragments.clear()
            source.fragment_chars = 0
            source.turn_id = turn_id
        kind = event["type"]
        if kind == 'answer_clear':
            source.fragments.clear()
            source.fragment_chars = 0
            source.events = deque((e for e in source.events if e['type'] not in {'user_transcript', 'assistant_response_start', 'assistant_response', 'turn_committed'}), maxlen=128)
        if kind == "assistant_fragment":
            source.fragments.append(event)
            source.fragment_chars += len(event.get("text", ""))
            while len(source.fragments) > 1 and (source.fragment_chars > 20000 or len(source.fragments) > 2048):
                source.fragment_chars -= len(source.fragments.popleft().get("text", ""))
            return
        if kind in {"board_clear", "board_begin", "assistant_board"}:
            source.events = deque((e for e in source.events if e["type"] not in
                {"assistant_board", "board_begin", "board_item", "board_end", "board_clear"}), maxlen=128)
        key = (kind, event.get("index") if kind == "board_item" else None)
        prior = next((e for e in source.events if
            (e["type"], e.get("index") if e["type"] == "board_item" else None) == key), None)
        if prior is not None:
            source.events.remove(prior)
        opposite = {"speaking_start": "speaking_end", "speaking_end": "speaking_start"}.get(kind)
        if opposite:
            source.events = deque((e for e in source.events if e["type"] != opposite), maxlen=128)
        source.events.append(event)

    def acknowledge_board(self, viewer, message):
        # VoiceTurnSession validates and commits its own receipts.
        return False

    async def unregister(self, sessionid):
        source = self.sources.pop(sessionid, None)
        if source is not None:
            source.voice._presentation = None
