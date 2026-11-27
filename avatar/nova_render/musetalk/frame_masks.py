# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Indexable full-frame masks with a fixed memory budget per controller."""
from collections import OrderedDict
from collections.abc import Sequence
from operator import index as integer_index
from threading import RLock
from weakref import WeakMethod


class BoundedFrameMasks(Sequence):
    def __init__(self, count, builder, *, max_bytes=16 * 1024 * 1024):
        self._count = count
        self._max_bytes = max_bytes
        self._cache = OrderedDict()
        self._bytes = 0
        self._lock = RLock()
        # A bound builder must not turn controller -> cache -> controller into
        # a cycle that keeps large frames alive until the next GC collection.
        try:
            self._builder = WeakMethod(builder)
        except TypeError:
            self._builder = lambda: builder

    def __len__(self):
        return self._count

    @property
    def retained_bytes(self):
        with self._lock:
            return self._bytes

    def __getitem__(self, key):
        if isinstance(key, slice):
            return tuple(self[i] for i in range(*key.indices(self._count)))
        key = integer_index(key)
        if key < 0:
            key += self._count
        if not 0 <= key < self._count:
            raise IndexError(key)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            builder = self._builder()
            if builder is None:
                raise RuntimeError('mask controller is no longer available')
            mask = builder(key)
            mask.setflags(write=False)
            while self._cache and self._bytes + mask.nbytes > self._max_bytes:
                _, previous = self._cache.popitem(last=False)
                self._bytes -= previous.nbytes
            if mask.nbytes <= self._max_bytes:
                self._cache[key] = mask
                self._bytes += mask.nbytes
            return mask
