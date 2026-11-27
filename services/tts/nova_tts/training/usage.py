# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Usage label (使用限制標示) of a voice model trained from a corpus.

The label is the strictest of the base model's label and the one implied by the
corpus source declaration (spec decision 3, ADR 0026):

- ``edge-test-teacher`` (Edge audio) and ``development-unlicensed`` ->
  ``Development only``;
- ``self-recorded`` and ``written-authorization`` -> the base model's label,
  ``Research / Non-commercial`` (the base model's training data is undocumented).

The label depends only on the declared source and the base model, never on what
was done to the corpus, so processing can not lower it. Label strings are those
of ``nova_tts.voice_models.USAGE_LABELS``; no source is ever commercially usable.
"""

from __future__ import annotations

from nova_tts.voice_models import USAGE_LABELS

SOURCE_EDGE_TEST_TEACHER = "edge-test-teacher"
SOURCE_SELF_RECORDED = "self-recorded"
SOURCE_WRITTEN_AUTHORIZATION = "written-authorization"
SOURCE_DEVELOPMENT_UNLICENSED = "development-unlicensed"
SOURCE_KINDS = (
    SOURCE_EDGE_TEST_TEACHER,
    SOURCE_SELF_RECORDED,
    SOURCE_WRITTEN_AUTHORIZATION,
    SOURCE_DEVELOPMENT_UNLICENSED,
)

DEVELOPMENT_ONLY = "Development only"
RESEARCH_NON_COMMERCIAL = "Research / Non-commercial"
# The base checkpoint's training data is undocumented, so it is never better
# than research use.
BASE_MODEL_USAGE = RESEARCH_NON_COMMERCIAL

# What each declared source allows by itself. Every source is at most research use.
_SOURCE_LABEL = {
    SOURCE_EDGE_TEST_TEACHER: DEVELOPMENT_ONLY,
    SOURCE_DEVELOPMENT_UNLICENSED: DEVELOPMENT_ONLY,
    SOURCE_SELF_RECORDED: RESEARCH_NON_COMMERCIAL,
    SOURCE_WRITTEN_AUTHORIZATION: RESEARCH_NON_COMMERCIAL,
}


def strictest_label(*labels: str) -> str:
    """The most restrictive of ``labels`` (``USAGE_LABELS`` is ordered strictest first)."""
    if not labels:
        raise ValueError("at least one usage label is required")
    for label in labels:
        if label not in USAGE_LABELS:
            raise ValueError(f"unknown usage label {label!r}")
    return min(labels, key=USAGE_LABELS.index)


def corpus_usage_label(source: str | None, base_usage: str = BASE_MODEL_USAGE) -> str:
    """The label of a model trained on a corpus of ``source`` from a base model of ``base_usage``.

    ``source`` is one of ``SOURCE_KINDS``; ``None`` (no declaration yet) gets the
    strictest label because the origin of the audio is unknown.
    """
    if source is None:
        source_label = DEVELOPMENT_ONLY
    elif source in _SOURCE_LABEL:
        source_label = _SOURCE_LABEL[source]
    else:
        raise ValueError(f"unknown corpus source {source!r}")
    return strictest_label(base_usage, source_label)
