# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Present the current input owner's played media and conversation on both pages."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction

from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame, VideoFrame

from src.utils.logging import logger


DISPLAY_EVENTS = {
    "user_transcript", "assistant_fragment", "assistant_response_mode",
    "assistant_board", "board_begin", "board_item", "board_end", "board_clear",
    "speaking_start", "speaking_end", "state", "turn_cancelled", "turn_committed",
    "conversation_reset", "role_clear", "role_handoff",
}
RESET_EVENTS = {"conversation_reset", "role_clear"}


@dataclass
class _Source:
    voice: object
    player: object
    events: deque = field(default_factory=lambda: deque(maxlen=128))
    fragments: deque = field(default_factory=deque)
    fragment_chars: int = 0
    turn_id: str | None = None
    tasks: list = field(default_factory=list)


class PresentationTrack(MediaStreamTrack):
    def __init__(self, hub, voice, kind):
        super().__init__()
        self.hub, self.voice, self.kind = hub, voice, kind
        self.queue = asyncio.Queue(maxsize=3 if kind == "video" else 2)

    def clear(self):
        while not self.queue.empty():
            self.queue.get_nowait()

    async def recv(self):
        self.hub.start()
        while self.readyState == "live":
            item = await self.queue.get()
            if item is None:
                break
            source, generation, epoch, eventpoint, frame, pts, time_base = item
            if (epoch != self.hub.epoch or source is not self.hub.current
                    or source.voice._closed or source.voice._generation != generation):
                continue
            if isinstance(eventpoint, dict):
                if eventpoint.get("generation", generation) != generation:
                    continue
                if ("avatar_epoch" in eventpoint and eventpoint["avatar_epoch"]
                        != getattr(source.voice.avatar, "_asset_epoch", 0)):
                    continue
            # Each sender owns its frame: PTS and encoder changes cannot mutate
            # another peer's copy or the inference player's cached idle frame.
            if isinstance(frame, AudioFrame):
                copy = AudioFrame.from_ndarray(frame.to_ndarray(), format=frame.format.name,
                                              layout=frame.layout.name)
                copy.sample_rate = frame.sample_rate
            else:
                copy = VideoFrame.from_ndarray(frame.to_ndarray(format="yuv420p"), format="yuv420p")
            copy.pts, copy.time_base = pts, time_base
            return copy
        raise MediaStreamError

    def stop(self):
        super().stop()
        self.clear()
        self.queue.put_nowait(None)
        self.hub.tracks.discard(self)


class SessionPresentation:
    def __init__(self, state):
        self.state = state
        self.sources = {}
        self.tracks = set()
        self.current = None
        self.focus = None
        self.epoch = 0
        self.running = False
        self.timestamps = {"audio": 0, "video": 0}
        self.last_media = {}

    def register(self, voice, player):
        source = _Source(voice, player)
        self.sources[voice.sessionid] = source
        voice._presentation = self
        tracks = tuple(PresentationTrack(self, voice, kind) for kind in ("audio", "video"))
        self.tracks.update(tracks)
        self.refresh()
        if self.running:
            self._start_source(source)
        return tracks

    def start(self):
        if not self.running:
            self.running = True
            for source in self.sources.values():
                self._start_source(source)

    def _start_source(self, source):
        if source.tasks:
            return
        for kind in ("audio", "video"):
            track = getattr(source.player, kind)
            if callable(getattr(track, "recv", None)):
                source.tasks.append(asyncio.create_task(self._read(source, track, kind)))

    async def _read(self, source, track, kind):
        try:
            while True:
                frame = await track.recv()
                self.refresh()
                if source is not self.current:
                    continue
                generation, epoch = source.voice._generation, self.epoch
                eventpoint = getattr(track, "last_eventpoint", None)
                pts, time_base = self._timestamp(source, kind, frame)
                item = (source, generation, epoch, eventpoint, frame, pts, time_base)
                for target in list(self.tracks):
                    if target.kind != kind or target.readyState != "live":
                        continue
                    if target.voice is source.voice:
                        # Preserve the input owner's audio backpressure.
                        await target.queue.put(item)
                    else:
                        # A slow display must not delay the live conversation.
                        if target.queue.full():
                            target.queue.get_nowait()
                        target.queue.put_nowait(item)
        except asyncio.CancelledError:
            raise
        except MediaStreamError:
            pass
        except Exception as exc:
            logger.warning("Presentation %s source ended type=%s", kind, type(exc).__name__)

    def _timestamp(self, source, kind, frame):
        rate = frame.sample_rate if kind == "audio" else 90000
        step = frame.samples if kind == "audio" else 3600
        position = frame.pts * frame.time_base if frame.pts is not None and frame.time_base else None
        previous = self.last_media.get(kind)
        if previous is not None:
            old_source, old_position = previous
            if source is old_source and position is not None and old_position is not None:
                step = max(step, round((position - old_position) * rate))
            self.timestamps[kind] += step
        self.last_media[kind] = (source, position)
        return self.timestamps[kind], Fraction(1, rate)

    def refresh(self):
        roles = getattr(self.state, "roles", None)
        candidates = [s for s in self.sources.values() if not s.voice._closed]
        if roles is not None and getattr(roles, "input_mode_managed", False):
            role = "stage" if roles.mode == "visitor" else "console"
            selected = next((s for s in candidates if s.voice._presenter == role), None)
        else:
            selected = self.sources.get(self.focus)
        selected = selected or next(iter(candidates), None)
        if selected is self.current:
            return
        self.current = selected
        self.epoch += 1
        for track in self.tracks:
            track.clear()
        for source in self.sources.values():
            self.replay(source.voice)

    def replay(self, voice):
        voice._send_event({"type": "presentation_reset", "turn_id": None})
        if self.current is not None:
            first = {"user_transcript", "assistant_response_mode"}
            events = [e for e in self.current.events if e["type"] in first]
            events.extend(self.current.fragments)
            events.extend(e for e in self.current.events if e["type"] not in first)
            for event in events:
                self._send(voice, self.current.voice, event, replay=True)

    @staticmethod
    def _send(target, source, event, *, replay=False):
        target._send_event({**event, "source_sessionid": source.sessionid,
                            "source_presenter": source._presenter,
                            "mirrored": target is not source, "replay": replay})

    def publish(self, voice, event):
        source = self.sources.get(voice.sessionid)
        if source is None:
            voice._send_event(event)
            return
        roles = getattr(self.state, "roles", None)
        if event["type"] == "user_transcript" and not getattr(roles, "input_mode_managed", False):
            self.focus = voice.sessionid
        self.refresh()
        if event["type"] not in DISPLAY_EVENTS:
            voice._send_event(event)
            return
        self._remember(source, event)
        if source is not self.current:
            return
        if event["type"] in RESET_EVENTS | {"turn_cancelled", "user_transcript"}:
            for track in self.tracks:
                track.clear()
        for target in self.sources.values():
            self._send(target.voice, voice, event)

    @staticmethod
    def _remember(source, event):
        turn_id = event.get("turn_id")
        if event["type"] in RESET_EVENTS or (turn_id and turn_id != source.turn_id):
            source.events.clear()
            source.fragments.clear()
            source.fragment_chars = 0
            source.turn_id = turn_id
        kind = event["type"]
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
        source = self.current
        if source is None or source.voice is viewer:
            return False
        source.voice._acknowledge_board(message, presenter=viewer._presenter)
        return True

    async def unregister(self, sessionid):
        source = self.sources.pop(sessionid, None)
        if source is None:
            return
        source.voice._presentation = None
        for track in list(self.tracks):
            if track.voice is source.voice:
                track.stop()
        for task in source.tasks:
            task.cancel()
        await asyncio.gather(*source.tasks, return_exceptions=True)
        for kind, (previous, _) in list(self.last_media.items()):
            if previous is source:
                self.last_media[kind] = (None, None)
        self.refresh()
        if not self.sources:
            self.running = False
            self.focus = None
            self.last_media.clear()
            self.timestamps = {"audio": 0, "video": 0}
