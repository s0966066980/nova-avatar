# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer feeds spoken-text deltas; the core decides where fragments end."""
from nova_llm.fragments import passthrough_fragmenter


def test_passthrough_emits_each_delta_without_cutting_or_waiting():
    emitted: list[str] = []
    stream = passthrough_fragmenter(emitted.append, lambda: True)

    stream.feed("好，我來")
    stream.feed("")
    stream.feed("說明。")
    stream.flush()
    stream.close()

    assert emitted == ["好，我來", "說明。"]
