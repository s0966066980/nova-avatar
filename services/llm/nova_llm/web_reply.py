# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Bound web speech at playable boundaries before preview, TTS and history."""
from threading import RLock


class WebSpeechGuard:
    def __init__(self, max_chars):
        self.max_chars = max_chars
        self._seen = set()
        self._length = 0
        self._stopped = False
        self._lock = RLock()

    @classmethod
    def resumed(cls, max_chars, accepted, *, stopped=False):
        """The guard after it accepted ``accepted``, in order."""
        guard = cls(max_chars)
        for text in accepted:
            guard._seen.add(guard._key(text))
            guard._length += len(text)
        guard._stopped = bool(stopped)
        return guard

    @staticmethod
    def _key(text):
        return ''.join(c for c in text.casefold() if c.isalnum())

    @property
    def stopped(self):
        with self._lock:
            return self._stopped

    def accept(self, text):
        key = self._key(text)
        with self._lock:
            if self._stopped:
                return False
            if (len(key) >= 6 and key in self._seen
                    or self._length and self._length + len(text) > self.max_chars):
                self._stopped = True
                return False
            # Preserve the first complete fragment even if a single sentence
            # exceeds the target; never slice a date, number or spoken clause.
            self._seen.add(key)
            self._length += len(text)
            return True
