# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""One cancellable idle deadline per stage; no missed-cycle queue."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict
import time

from src.greetings.content import GreetingError, prepare_greeting


class IdleGreetingController:
    def __init__(self, host, *, clock=time.monotonic, prepare=prepare_greeting):
        self.host = host
        self.clock = clock
        self.prepare = prepare
        self.deadline = None
        self.signature = None
        self.task = None
        self.preparation = None
        self.previous = ""
        self.status = "paused"
        self.error = ""
        self._closed = False

    def report(self, status, error=""):
        if (status, error) != (self.status, self.error):
            self.status, self.error = status, error
            self.host._emit("idle_greeting", status=status, error=error)

    def reset(self, *, stop_playing=False):
        self.deadline = None
        self.host.cancel_greeting_trial()
        if self.preparation:
            self.preparation.cancel()
            self.preparation = None
        self.host.cancel_greeting(stop_playing=stop_playing)

    def refresh(self):
        if self._closed or self.host._presenter != "stage":
            return
        self.tick()
        if self.task is None and self.host._presenter == "stage":
            try:
                self.task = asyncio.get_running_loop().create_task(self._watch())
            except RuntimeError:
                pass

    async def _watch(self):
        try:
            while not self._closed:
                await asyncio.sleep(.1)
                self.tick()
        finally:
            self.task = None

    def tick(self):
        host = self.host
        if not getattr(getattr(host.config, "stage", None), "idle_greeting_enabled", False):
            self.reset(stop_playing=True)
            self.report("paused", self.error)
            return
        active, idle, clear = host.greeting_conditions()
        roles = host._role_coordinator
        content = (roles.profiles[roles.library["pair"]["main"]] if roles is not None
                   else (asdict(host.config.greeting), asdict(host.config.llm)))
        settings = (content, host.config.stage.idle_greeting_enabled,
                    host.config.stage.idle_greeting_seconds)
        if settings != self.signature:
            self.signature = deepcopy(settings)
            self.reset(stop_playing=not host.config.stage.idle_greeting_enabled)
            active, idle, clear = host.greeting_conditions()
        if not active:
            self.reset(stop_playing=True)
            self.report("paused", self.error)
            return
        if host.is_greeting:
            self.report("playing" if host._greeting_started else "preparing")
            return
        if not idle:
            self.reset()
            self.report("paused", self.error)
            return
        if self.deadline is None:
            self.deadline = self.clock() + host.config.stage.idle_greeting_seconds
        if self.preparation is not None:
            return
        if self.clock() < self.deadline:
            self.report("waiting", self.error)
            return
        if not clear:
            self.report("waiting_clear", self.error)
            return
        self.report("preparing")
        self.preparation = asyncio.create_task(self._prepare(deepcopy(host.config)))

    async def _prepare(self, config):
        task = asyncio.current_task()
        try:
            result = await self.prepare(config, previous=self.previous)
            active, idle, clear = self.host.greeting_conditions()
            if self.preparation is not task or not active or not idle or not clear:
                return
            self.host.start_greeting(result["text"])
            self.error = ""
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, GreetingError) else "招呼準備失敗，已略過本次"
            self.report("failed", self.error)
        finally:
            if self.preparation is task:
                self.preparation = None
                self.deadline = self.clock() + self.host.config.stage.idle_greeting_seconds

    def finished(self, *, error=""):
        self.error = error
        self.deadline = self.clock() + self.host.config.stage.idle_greeting_seconds
        self.report("failed" if error else "waiting", error)

    def close(self):
        self._closed = True
        self.reset(stop_playing=True)
        if self.task:
            self.task.cancel()
