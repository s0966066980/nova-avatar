# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The recorded MSA §14(s)(iv) acknowledgement that gates the Edge test teacher."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nova_tts.training.corpus import CorpusError, CorpusStore
from nova_tts.training.edge_acknowledgement import (
    ACKNOWLEDGEMENT_FILE,
    MSA_CLAUSE,
    read_acknowledgement,
    record_acknowledgement,
    require_acknowledgement,
)

NOW = datetime(2026, 11, 24, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path: Path) -> CorpusStore:
    return CorpusStore(tmp_path / "training")


@pytest.fixture
def edge_corpus(store: CorpusStore) -> str:
    store.create("edge-test", source="edge-test-teacher")
    return "edge-test"


def _ack_path(store: CorpusStore, slug: str) -> Path:
    return store.root / slug / ACKNOWLEDGEMENT_FILE


# ------------------------------------------------------------------ the clause


def test_the_clause_text_is_the_one_quoted_in_the_notices():
    notices = (Path(__file__).resolve().parents[3] / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert MSA_CLAUSE.reference == "Microsoft Services Agreement §14(s)(iv)"
    assert MSA_CLAUSE.effective == "2026-09-30"
    assert " ".join(MSA_CLAUSE.text.split()) in " ".join(notices.split())


# ------------------------------------------------------------------ the gate


def test_without_a_record_the_gate_refuses(store, edge_corpus):
    assert read_acknowledgement(store, edge_corpus) is None

    with pytest.raises(CorpusError) as caught:
        require_acknowledgement(store, edge_corpus)

    assert caught.value.status == 403
    assert "§14(s)(iv)" in caught.value.message


def test_nothing_creates_a_record_on_its_own(store, edge_corpus):
    read_acknowledgement(store, edge_corpus)
    with pytest.raises(CorpusError):
        require_acknowledgement(store, edge_corpus)

    assert not _ack_path(store, edge_corpus).exists()


def test_recording_the_acknowledgement_opens_the_gate(store, edge_corpus):
    record = record_acknowledgement(store, edge_corpus, MSA_CLAUSE.text, now=NOW)

    assert require_acknowledgement(store, edge_corpus) == record
    assert read_acknowledgement(store, edge_corpus) == record


def test_the_record_keeps_the_timestamp_the_exact_clause_text_and_the_source(store, edge_corpus):
    record_acknowledgement(store, edge_corpus, MSA_CLAUSE.text, now=NOW)

    data = json.loads(_ack_path(store, edge_corpus).read_text(encoding="utf-8"))

    assert data["acknowledged_at"] == "2026-11-24T10:30:00+00:00"
    assert data["clause_text"] == MSA_CLAUSE.text
    assert data["clause_reference"] == MSA_CLAUSE.reference
    assert data["clause_effective"] == MSA_CLAUSE.effective
    assert data["source"] == "edge-test-teacher"
    assert _ack_path(store, edge_corpus).parent == store.root / edge_corpus  # next to corpus.json


def test_the_record_sits_beside_the_source_declaration(store, edge_corpus):
    record_acknowledgement(store, edge_corpus, MSA_CLAUSE.text, now=NOW)

    assert (store.root / edge_corpus / "corpus.json").is_file()
    assert _ack_path(store, edge_corpus).is_file()


def test_the_text_the_administrator_was_shown_must_be_the_exact_clause(store, edge_corpus):
    with pytest.raises(CorpusError):
        record_acknowledgement(store, edge_corpus, MSA_CLAUSE.text + " (shortened)", now=NOW)
    with pytest.raises(CorpusError):
        record_acknowledgement(store, edge_corpus, "", now=NOW)

    assert not _ack_path(store, edge_corpus).exists()


def test_a_second_acknowledgement_keeps_the_first_timestamp(store, edge_corpus):
    first = record_acknowledgement(store, edge_corpus, MSA_CLAUSE.text, now=NOW)
    later = datetime(2026, 12, 1, tzinfo=timezone.utc)

    again = record_acknowledgement(store, edge_corpus, MSA_CLAUSE.text, now=later)

    assert again == first


def test_only_an_edge_corpus_can_carry_the_acknowledgement(store):
    store.create("mine", source="self-recorded")
    store.create("undeclared")

    for slug in ("mine", "undeclared"):
        with pytest.raises(CorpusError):
            record_acknowledgement(store, slug, MSA_CLAUSE.text, now=NOW)


def test_the_gate_refuses_a_corpus_whose_source_is_not_the_edge_teacher(store):
    store.create("mine", source="self-recorded")

    with pytest.raises(CorpusError):
        require_acknowledgement(store, "mine")


def test_a_record_for_other_clause_wording_no_longer_opens_the_gate(store, edge_corpus):
    record_acknowledgement(store, edge_corpus, MSA_CLAUSE.text, now=NOW)
    path = _ack_path(store, edge_corpus)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["clause_text"] = "You may do anything."
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CorpusError) as caught:
        require_acknowledgement(store, edge_corpus)

    assert caught.value.status == 403


@pytest.mark.parametrize("content", ["not json", "[]", '{"version": 1}', '{"version": 2}'])
def test_a_damaged_record_is_never_trusted(store, edge_corpus, content):
    _ack_path(store, edge_corpus).write_text(content, encoding="utf-8")

    with pytest.raises(CorpusError):
        require_acknowledgement(store, edge_corpus)


def test_a_record_that_is_a_symlink_is_never_trusted(store, edge_corpus, tmp_path):
    record_acknowledgement(store, edge_corpus, MSA_CLAUSE.text, now=NOW)
    real = tmp_path / "elsewhere.json"
    real.write_bytes(_ack_path(store, edge_corpus).read_bytes())
    _ack_path(store, edge_corpus).unlink()
    _ack_path(store, edge_corpus).symlink_to(real)

    with pytest.raises(CorpusError):
        require_acknowledgement(store, edge_corpus)


def test_an_unknown_corpus_is_not_found(store):
    with pytest.raises(CorpusError) as caught:
        require_acknowledgement(store, "missing")

    assert caught.value.status == 404
