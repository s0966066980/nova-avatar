# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Usage label of a trained voice model: the strictest of base model and corpus source."""

from __future__ import annotations

import pytest

from nova_tts.training.usage import (
    BASE_MODEL_USAGE,
    SOURCE_KINDS,
    corpus_usage_label,
    strictest_label,
)
from nova_tts.voice_models import USAGE_LABELS

pytestmark = pytest.mark.speech

DEVELOPMENT = "Development only"
RESEARCH = "Research / Non-commercial"


def test_labels_are_exactly_the_strings_the_voice_model_catalog_accepts():
    assert DEVELOPMENT in USAGE_LABELS
    assert RESEARCH in USAGE_LABELS
    assert BASE_MODEL_USAGE == RESEARCH


def test_source_kinds_are_the_four_declarations():
    assert set(SOURCE_KINDS) == {
        "edge-test-teacher",
        "self-recorded",
        "written-authorization",
        "development-unlicensed",
    }


@pytest.mark.parametrize("source", ["edge-test-teacher", "development-unlicensed"])
def test_edge_and_development_corpora_are_development_only(source):
    assert corpus_usage_label(source) == DEVELOPMENT


@pytest.mark.parametrize("source", ["self-recorded", "written-authorization"])
def test_own_and_authorised_corpora_still_carry_the_base_model_label(source):
    assert corpus_usage_label(source) == RESEARCH


def test_every_source_maps_to_a_catalog_label():
    assert all(corpus_usage_label(kind) in USAGE_LABELS for kind in SOURCE_KINDS)


def test_an_undeclared_source_gets_the_strictest_label():
    assert corpus_usage_label(None) == DEVELOPMENT


def test_a_stricter_base_model_wins_over_a_lenient_source():
    assert corpus_usage_label("self-recorded", base_usage=DEVELOPMENT) == DEVELOPMENT


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError):
        corpus_usage_label("commercial-license")


def test_unknown_base_label_is_rejected():
    with pytest.raises(ValueError):
        corpus_usage_label("self-recorded", base_usage="Commercial")


def test_strictest_label_is_order_independent_and_never_lowers():
    assert strictest_label(RESEARCH, DEVELOPMENT) == DEVELOPMENT
    assert strictest_label(DEVELOPMENT, RESEARCH) == DEVELOPMENT
    assert strictest_label(RESEARCH, RESEARCH) == RESEARCH
    with pytest.raises(ValueError):
        strictest_label()
    with pytest.raises(ValueError):
        strictest_label(RESEARCH, "Commercial")
