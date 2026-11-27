# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A conversation's recent web evidence, kept by the core (ADR 0027).

The LLM layer searches; reusing a role's last search within five minutes is
conversation state, so the cache lives with the voice session.
"""
import time
from copy import deepcopy


class EvidenceCache:
    """A small cache owned by one VoiceSession; entries never renew their TTL on reuse."""
    def __init__(self):
        self.entries = {}

    def clear(self):
        self.entries.clear()

    def previous(self, role, policy):
        entry = self.entries.get(role)
        if entry and time.monotonic() - entry[0] < 300 and entry[1] == policy:
            return deepcopy(entry[2])
        return None

    def put(self, role, policy, result):
        if result.get('sources'):
            self.entries[role] = (time.monotonic(), deepcopy(policy), deepcopy(result))
            if len(self.entries) > 30:
                del self.entries[next(iter(self.entries))]


def public_result(result):
    """A search result as the console shows it: page text stays on the server."""
    return {**result, 'sources': [{k: v for k, v in s.items() if k != 'text'}
                                for s in result['sources']]}
