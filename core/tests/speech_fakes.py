# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Answer the way the core does: the LLM's spoken deltas go through ReplySpeech."""

from nova_core.server.reply_streaming.speech import ReplySpeech

_CALLBACK_KEYS = ("on_board", "on_mode", "rules_snapshot", "incremental_board")


def spoken_answer(llm, message, avatar=None, *, stream=True, datainfo=None,
                  chunk_guard=None, **kwargs):
    """Play the answer on ``avatar`` (when streaming) and return the spoken text.

    Mirrors ``VoiceTurnSession``: a sink exists when something is played or
    web speech must be bounded at fragment boundaries.
    """
    target = avatar if stream else None
    speech = None
    if target is not None or getattr(message, "web_evidence", False):
        envelope = {
            key: value for key, value in dict(datainfo or {}).items()
            if key not in _CALLBACK_KEYS
        }
        speech = ReplySpeech(
            target, envelope,
            settings=getattr(llm.config, "reply_streaming", None),
            chunk_guard=chunk_guard,
        )
    return llm.generate_response(
        message, speech=speech, datainfo=datainfo, chunk_guard=chunk_guard, **kwargs,
    )
