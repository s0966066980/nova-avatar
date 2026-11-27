# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Training corpus on disk: lines, review state, source declaration, path safety."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from nova_tts.training import corpus as corpus_module
from nova_tts.training.corpus import (
    CorpusError,
    CorpusStore,
    REVIEW_CONFIRMED,
    REVIEW_EXCLUDED,
    REVIEW_PENDING,
)

WAV = b"RIFF fixture wav bytes"


@pytest.fixture
def store(tmp_path: Path) -> CorpusStore:
    return CorpusStore(tmp_path / "training")


def _add(store: CorpusStore, slug: str, text: str = "你好", **kwargs):
    return store.add_line(slug, WAV, ".wav", text=text, **kwargs)


# ------------------------------------------------------------------ creation and slugs


def test_a_new_corpus_has_no_source_and_no_lines(store):
    created = store.create("my-voice")

    assert created.slug == "my-voice"
    assert created.source is None
    assert created.lines == ()
    assert (store.root / "my-voice").is_dir()
    assert store.get("my-voice") == created


def test_create_can_declare_the_source_at_once(store):
    created = store.create("edge-test", source="edge-test-teacher")

    assert created.source == "edge-test-teacher"
    assert created.declared_at


def test_creating_the_same_slug_twice_conflicts(store):
    store.create("my-voice")
    with pytest.raises(CorpusError) as excinfo:
        store.create("my-voice")
    assert excinfo.value.status == 409


@pytest.mark.parametrize(
    "slug",
    [
        "",
        ".",
        "..",
        "../escape",
        "a/b",
        "a\\b",
        "/etc",
        ".hidden",
        "has space",
        "中文",
        "x" * 81,
        "a\x00b",
        "trailing\n",
    ],
)
def test_bad_slugs_are_rejected_everywhere(store, slug):
    with pytest.raises(CorpusError):
        store.create(slug)
    with pytest.raises(CorpusError):
        store.get(slug)
    with pytest.raises(CorpusError):
        store.add_line(slug, WAV, ".wav")
    with pytest.raises(CorpusError):
        store.audio_path(slug, "000001")


def test_non_string_slug_is_rejected(store):
    with pytest.raises(CorpusError):
        store.get(None)  # type: ignore[arg-type]


def test_nothing_is_created_outside_the_root_for_bad_slugs(store, tmp_path):
    with pytest.raises(CorpusError):
        store.create("../escape")
    assert not (tmp_path / "escape").exists()


def test_unknown_corpus_is_404(store):
    with pytest.raises(CorpusError) as excinfo:
        store.get("missing")
    assert excinfo.value.status == 404


def test_a_symlinked_corpus_directory_is_refused(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    store.root.mkdir(parents=True)
    (store.root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CorpusError):
        store.get("linked")
    with pytest.raises(CorpusError):
        store.add_line("linked", WAV, ".wav")
    assert list(outside.iterdir()) == []


def test_list_returns_valid_corpora_by_slug_and_skips_the_rest(store, caplog):
    store.create("beta")
    store.create("alpha")
    (store.root / "stray-file.txt").write_text("x", encoding="utf-8")
    (store.root / ".deleted").mkdir()
    (store.root / "no-manifest").mkdir()

    assert [c.slug for c in store.list()] == ["alpha", "beta"]


def test_list_of_a_missing_root_is_empty(tmp_path):
    assert CorpusStore(tmp_path / "nowhere").list() == []


# ------------------------------------------------------------------ lines and audio


def test_added_lines_get_server_generated_ids_and_start_pending(store):
    store.create("v")
    first = _add(store, "v", "第一句")
    second = _add(store, "v", "第二句")

    assert (first.id, second.id) == ("000001", "000002")
    assert first.review == REVIEW_PENDING
    assert first.text == "第一句"
    assert first.audio_name == "000001.wav"
    audio = store.audio_path("v", first.id)
    assert audio == store.root / "v" / "audio" / "000001.wav"
    assert audio.read_bytes() == WAV


def test_lines_survive_reopening_the_store(store):
    store.create("v")
    line = _add(store, "v", "持久化")
    store.set_review("v", line.id, REVIEW_CONFIRMED)

    reopened = CorpusStore(store.root).get("v")

    assert [(ln.id, ln.text, ln.review) for ln in reopened.lines] == [("000001", "持久化", "confirmed")]


def test_manifest_is_readable_utf8_json_and_no_temp_files_remain(store):
    store.create("v")
    _add(store, "v", "你好")

    manifest = json.loads((store.root / "v" / "corpus.json").read_text(encoding="utf-8"))
    assert manifest["lines"][0]["text"] == "你好"
    leftovers = [p.name for p in (store.root / "v").rglob("*") if p.name.startswith(".")]
    assert leftovers == []


def test_a_failed_write_keeps_the_previous_manifest(store, monkeypatch):
    store.create("v")
    _add(store, "v", "保留")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        _add(store, "v", "失敗")
    monkeypatch.undo()

    assert [ln.text for ln in store.get("v").lines] == ["保留"]
    assert [p.name for p in (store.root / "v").rglob(".*")] == []


@pytest.mark.parametrize("extension", [".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"])
def test_allowed_audio_formats(store, extension):
    store.create("v")
    line = store.add_line("v", WAV, extension)
    assert line.audio_name == f"000001{extension}"


@pytest.mark.parametrize("extension", ["", "wav", ".exe", ".wav/../x", "/.wav", ".WAV ", ".py", ".json"])
def test_other_extensions_are_rejected(store, extension):
    store.create("v")
    with pytest.raises(CorpusError):
        store.add_line("v", WAV, extension)
    assert store.get("v").lines == ()


def test_uppercase_extension_is_normalised(store):
    store.create("v")
    assert store.add_line("v", WAV, ".WAV").audio_name == "000001.wav"


def test_empty_and_oversized_audio_is_rejected(store, monkeypatch):
    store.create("v")
    with pytest.raises(CorpusError):
        store.add_line("v", b"", ".wav")
    monkeypatch.setattr(corpus_module, "MAX_AUDIO_BYTES", 10)
    with pytest.raises(CorpusError) as excinfo:
        store.add_line("v", b"x" * 11, ".wav")
    assert excinfo.value.status == 413
    assert store.get("v").lines == ()


def test_line_limit(store, monkeypatch):
    store.create("v")
    monkeypatch.setattr(corpus_module, "MAX_LINES", 2)
    _add(store, "v")
    _add(store, "v")
    with pytest.raises(CorpusError):
        _add(store, "v")


def test_original_name_is_display_only_and_never_a_path(store, tmp_path):
    store.create("v")
    line = _add(store, "v", original_name="../../etc/passwd\x00.wav")

    assert line.original_name == "passwd.wav"
    assert line.audio_name == "000001.wav"
    assert not (tmp_path / "etc").exists()
    assert [p.name for p in (store.root / "v" / "audio").iterdir()] == ["000001.wav"]


def test_text_is_stripped_and_whitespace_collapsed(store):
    store.create("v")
    assert _add(store, "v", "  你好 \n  世界\t").text == "你好 世界"


def test_overlong_text_and_non_text_are_rejected(store):
    store.create("v")
    with pytest.raises(CorpusError):
        _add(store, "v", "字" * 501)
    with pytest.raises(CorpusError):
        _add(store, "v", 5)  # type: ignore[arg-type]


@pytest.mark.parametrize("line_id", ["", "1", "../000001", "000001/..", "abcdef", "0000001", None])
def test_audio_path_accepts_only_known_line_ids(store, line_id):
    store.create("v")
    _add(store, "v")
    with pytest.raises(CorpusError):
        store.audio_path("v", line_id)


def test_audio_path_of_an_unknown_line_is_404(store):
    store.create("v")
    with pytest.raises(CorpusError) as excinfo:
        store.audio_path("v", "000009")
    assert excinfo.value.status == 404


def test_a_symlinked_audio_file_is_refused(store, tmp_path):
    store.create("v")
    line = _add(store, "v")
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"secret")
    audio = store.audio_path("v", line.id)
    audio.unlink()
    audio.symlink_to(secret)

    with pytest.raises(CorpusError):
        store.audio_path("v", line.id)


def test_concurrent_adds_get_unique_ids(store):
    store.create("v")
    errors: list[BaseException] = []

    def work():
        try:
            for _ in range(5):
                _add(store, "v")
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    ids = [line.id for line in store.get("v").lines]
    assert len(ids) == 40 == len(set(ids))
    assert len(list((store.root / "v" / "audio").iterdir())) == 40


# ------------------------------------------------------------------ tampered manifests


def _write_manifest(store: CorpusStore, slug: str, manifest: dict) -> None:
    (store.root / slug / "corpus.json").write_text(json.dumps(manifest), encoding="utf-8")


def _good_line(**overrides):
    line = {"id": "000001", "ext": ".wav", "original_name": "", "text": "x", "review": "pending"}
    return {**line, **overrides}


@pytest.mark.parametrize(
    "line",
    [
        _good_line(id="../x"),
        _good_line(ext=".py"),
        _good_line(ext="/../x.wav"),
        _good_line(review="approved"),
        _good_line(text=5),
    ],
)
def test_a_tampered_manifest_is_refused_and_not_listed(store, line):
    store.create("v")
    _write_manifest(store, "v", {"version": 1, "source": None, "declared_at": None, "lines": [line]})

    with pytest.raises(CorpusError):
        store.get("v")
    assert store.list() == []


@pytest.mark.parametrize("raw", ["not json", "[]", '{"version": 2, "lines": []}'])
def test_an_unreadable_manifest_is_refused(store, raw):
    store.create("v")
    (store.root / "v" / "corpus.json").write_text(raw, encoding="utf-8")
    with pytest.raises(CorpusError):
        store.get("v")


def test_a_manifest_with_an_unknown_source_is_refused(store):
    store.create("v")
    _write_manifest(store, "v", {"version": 1, "source": "commercial", "declared_at": None, "lines": []})
    with pytest.raises(CorpusError):
        store.get("v")


# ------------------------------------------------------------------ review state and text


def test_review_states_can_be_changed_freely_between_the_three(store):
    store.create("v")
    line = _add(store, "v")

    assert store.set_review("v", line.id, REVIEW_CONFIRMED).review == REVIEW_CONFIRMED
    assert store.set_review("v", line.id, REVIEW_EXCLUDED).review == REVIEW_EXCLUDED
    assert store.set_review("v", line.id, REVIEW_PENDING).review == REVIEW_PENDING


def test_unknown_review_state_and_unknown_line_are_rejected(store):
    store.create("v")
    line = _add(store, "v")
    with pytest.raises(CorpusError):
        store.set_review("v", line.id, "approved")
    with pytest.raises(CorpusError) as excinfo:
        store.set_review("v", "000009", REVIEW_CONFIRMED)
    assert excinfo.value.status == 404


def test_a_line_without_text_can_not_be_confirmed_but_can_be_excluded(store):
    store.create("v")
    line = _add(store, "v", "")

    with pytest.raises(CorpusError):
        store.set_review("v", line.id, REVIEW_CONFIRMED)
    assert store.set_review("v", line.id, REVIEW_EXCLUDED).review == REVIEW_EXCLUDED


def test_editing_a_confirmed_line_sends_it_back_to_review(store):
    store.create("v")
    line = _add(store, "v", "舊")
    store.set_review("v", line.id, REVIEW_CONFIRMED)

    edited = store.set_text("v", line.id, "新")

    assert (edited.text, edited.review) == ("新", REVIEW_PENDING)


def test_editing_keeps_pending_and_excluded_states(store):
    store.create("v")
    pending = _add(store, "v", "a")
    excluded = _add(store, "v", "b")
    store.set_review("v", excluded.id, REVIEW_EXCLUDED)

    assert store.set_text("v", pending.id, "c").review == REVIEW_PENDING
    assert store.set_text("v", excluded.id, "d").review == REVIEW_EXCLUDED


def test_review_table_shows_the_normalised_text_and_unresolved_tokens(store):
    store.create("v")
    _add(store, "v", "2026年有15人")
    _add(store, "v", "12:30開會")

    first, second = store.get("v").review_table()

    assert first.normalized.text == "二零二六年有十五人"
    assert first.normalized.resolved
    assert second.normalized.text == "12:30開會"
    assert [u.reason for u in second.normalized.unresolved] == ["time_or_ratio"]
    assert second.line.text == "12:30開會"


# ------------------------------------------------------------------ source declaration


@pytest.mark.parametrize(
    "kind", ["edge-test-teacher", "self-recorded", "written-authorization", "development-unlicensed"]
)
def test_declaring_each_source_kind(store, kind):
    store.create("v")
    declared = store.declare_source("v", kind)
    assert declared.source == kind
    assert declared.declared_at
    assert store.get("v").source == kind


@pytest.mark.parametrize("kind", ["", "commercial", "Self-Recorded", None, 3])
def test_unknown_source_kinds_are_rejected(store, kind):
    store.create("v")
    with pytest.raises(CorpusError):
        store.declare_source("v", kind)  # type: ignore[arg-type]
    assert store.get("v").source is None


def test_a_source_is_declared_once_and_never_changed(store):
    store.create("v", source="edge-test-teacher")

    assert store.declare_source("v", "edge-test-teacher").source == "edge-test-teacher"
    with pytest.raises(CorpusError) as excinfo:
        store.declare_source("v", "self-recorded")
    assert excinfo.value.status == 409
    assert store.get("v").source == "edge-test-teacher"


def test_the_usage_label_follows_the_source_and_never_drops_after_processing(store):
    store.create("edge", source="edge-test-teacher")
    store.create("own", source="self-recorded")
    store.create("undeclared")
    for slug in ("edge", "own"):
        line = _add(store, slug, "你好")
        store.set_review(slug, line.id, REVIEW_CONFIRMED)
        store.set_text(slug, line.id, "再見")
        store.set_review(slug, line.id, REVIEW_CONFIRMED)

    assert store.get("edge").usage_label() == "Development only"
    assert store.get("own").usage_label() == "Research / Non-commercial"
    assert store.get("undeclared").usage_label() == "Development only"
    assert store.get("own").usage_label(base_usage="Development only") == "Development only"


# ------------------------------------------------------------------ trainability


def _ready(store: CorpusStore, slug: str = "v", source: str | None = "self-recorded") -> str:
    store.create(slug, source=source)
    return slug


def test_all_confirmed_with_a_source_is_trainable(store):
    slug = _ready(store)
    line = _add(store, slug, "你好")
    store.set_review(slug, line.id, REVIEW_CONFIRMED)

    result = store.get(slug).trainability()

    assert result.trainable
    assert result.reasons == ()


def test_confirmed_and_excluded_lines_may_be_mixed(store):
    slug = _ready(store)
    keep = _add(store, slug, "你好")
    drop = _add(store, slug, "雜音")
    store.set_review(slug, keep.id, REVIEW_CONFIRMED)
    store.set_review(slug, drop.id, REVIEW_EXCLUDED)

    assert store.get(slug).trainability().trainable


def test_an_empty_corpus_is_not_trainable(store):
    slug = _ready(store)
    result = store.get(slug).trainability()
    assert not result.trainable
    assert result.reasons == ("no_confirmed_lines",)


def test_all_excluded_is_not_trainable(store):
    slug = _ready(store)
    line = _add(store, slug, "你好")
    store.set_review(slug, line.id, REVIEW_EXCLUDED)
    assert store.get(slug).trainability().reasons == ("no_confirmed_lines",)


def test_a_pending_line_blocks_training(store):
    slug = _ready(store)
    done = _add(store, slug, "你好")
    _add(store, slug, "還沒看")
    store.set_review(slug, done.id, REVIEW_CONFIRMED)

    result = store.get(slug).trainability()

    assert not result.trainable
    assert result.reasons == ("pending_lines",)


def test_a_missing_source_declaration_blocks_training(store):
    slug = _ready(store, source=None)
    line = _add(store, slug, "你好")
    store.set_review(slug, line.id, REVIEW_CONFIRMED)

    result = store.get(slug).trainability()

    assert not result.trainable
    assert result.reasons == ("source_missing",)


def test_a_confirmed_line_with_unresolved_digits_blocks_training(store):
    slug = _ready(store)
    ok = _add(store, slug, "你好")
    bad = _add(store, slug, "12:30開會")
    store.set_review(slug, ok.id, REVIEW_CONFIRMED)
    store.set_review(slug, bad.id, REVIEW_CONFIRMED)

    result = store.get(slug).trainability()

    assert not result.trainable
    assert result.reasons == ("unresolved_digits",)


def test_unresolved_digits_in_an_excluded_line_do_not_block(store):
    slug = _ready(store)
    ok = _add(store, slug, "你好")
    bad = _add(store, slug, "12:30開會")
    store.set_review(slug, ok.id, REVIEW_CONFIRMED)
    store.set_review(slug, bad.id, REVIEW_EXCLUDED)

    assert store.get(slug).trainability().trainable


def test_fixing_the_text_unblocks_training(store):
    slug = _ready(store)
    line = _add(store, slug, "12:30開會")
    store.set_review(slug, line.id, REVIEW_CONFIRMED)
    assert not store.get(slug).trainability().trainable

    store.set_text(slug, line.id, "十二點半開會")
    store.set_review(slug, line.id, REVIEW_CONFIRMED)

    assert store.get(slug).trainability().trainable


def test_every_blocking_reason_is_reported_together(store):
    slug = _ready(store, source=None)
    _add(store, slug, "還沒看")

    result = store.get(slug).trainability()

    assert result.reasons == ("source_missing", "pending_lines", "no_confirmed_lines")


def test_counts(store):
    slug = _ready(store)
    a = _add(store, slug, "一")
    b = _add(store, slug, "二")
    _add(store, slug, "三")
    store.set_review(slug, a.id, REVIEW_CONFIRMED)
    store.set_review(slug, b.id, REVIEW_EXCLUDED)

    counts = store.get(slug).counts

    assert (counts.pending, counts.confirmed, counts.excluded) == (1, 1, 1)


def test_training_lines_refuse_a_corpus_that_is_not_trainable(store):
    slug = _ready(store)
    _add(store, slug, "還沒看")

    with pytest.raises(CorpusError) as excinfo:
        store.get(slug).training_lines()
    assert excinfo.value.status == 409


def test_training_lines_carry_the_expanded_text(store):
    slug = _ready(store)
    line = _add(store, slug, "共15人")
    store.set_review(slug, line.id, REVIEW_CONFIRMED)

    _add(store, slug, "排除")
    drop = store.get(slug).lines[-1]
    store.set_review(slug, drop.id, REVIEW_EXCLUDED)

    [(line_out, text)] = store.get(slug).training_lines()

    assert (line_out.id, text) == ("000001", "共十五人")


# ------------------------------------------------------------------ bulk confirm and guarded text


def test_confirm_pending_confirms_lines_with_text_in_one_write(store):
    store.create("bulk", source="self-recorded")
    with_text = [_add(store, "bulk", text=f"句{i}").id for i in range(3)]
    without_text = _add(store, "bulk", text="").id
    excluded = _add(store, "bulk", text="排除").id
    store.set_review("bulk", excluded, REVIEW_EXCLUDED)

    result = store.confirm_pending("bulk")

    assert (result.confirmed, result.without_text) == (3, 1)
    states = {line.id: line.review for line in store.get("bulk").lines}
    assert [states[i] for i in with_text] == [REVIEW_CONFIRMED] * 3
    assert states[without_text] == REVIEW_PENDING and states[excluded] == REVIEW_EXCLUDED


def test_confirm_pending_can_be_limited_to_chosen_lines(store):
    store.create("bulk", source="self-recorded")
    first, second = _add(store, "bulk").id, _add(store, "bulk").id

    result = store.confirm_pending("bulk", [second])

    assert result.confirmed == 1
    assert [line.review for line in store.get("bulk").lines] == [REVIEW_PENDING, REVIEW_CONFIRMED]
    with pytest.raises(CorpusError) as excinfo:
        store.confirm_pending("bulk", ["999999"])
    assert excinfo.value.status == 404
    assert first != second


def test_set_text_only_if_empty_never_overwrites_a_typed_transcript(store):
    store.create("guarded", source="self-recorded")
    empty = _add(store, "guarded", text="").id
    typed = _add(store, "guarded", text="自己打的").id

    assert store.set_text("guarded", empty, "自動產生", only_if_empty=True).text == "自動產生"
    assert store.set_text("guarded", typed, "自動產生", only_if_empty=True).text == "自己打的"


# ------------------------------------------------------------------ server-managed sidecar files


def test_a_sidecar_file_is_written_and_read_beside_the_manifest(store):
    store.create("my-voice")

    assert store.read_sidecar("my-voice", "msa-acknowledgement.json") is None
    store.write_sidecar("my-voice", "msa-acknowledgement.json", b"{}")

    assert store.read_sidecar("my-voice", "msa-acknowledgement.json") == b"{}"
    assert (store.root / "my-voice" / "msa-acknowledgement.json").read_bytes() == b"{}"


@pytest.mark.parametrize("name", ["../corpus.json", "corpus.json", "other.json", "", None])
def test_only_the_listed_sidecar_names_are_accepted(store, name):
    store.create("my-voice")

    with pytest.raises(CorpusError):
        store.write_sidecar("my-voice", name, b"{}")
    with pytest.raises(CorpusError):
        store.read_sidecar("my-voice", name)


def test_a_sidecar_of_a_missing_corpus_is_not_found(store):
    with pytest.raises(CorpusError) as caught:
        store.read_sidecar("nowhere", "msa-acknowledgement.json")

    assert caught.value.status == 404


# ------------------------------------------------------------------ deletion


def test_deleting_a_corpus_moves_it_to_the_recycle_bin(store):
    store.create("old-voice", source="edge-test-teacher")
    _add(store, "old-voice")

    recycled = store.delete("old-voice")

    assert recycled.parent == store.root / ".deleted"
    assert recycled.name.startswith("old-voice-")
    assert (recycled / "corpus.json").is_file()  # moved, not erased
    assert store.list() == []
    with pytest.raises(CorpusError) as refused:
        store.get("old-voice")
    assert refused.value.status == 404


def test_a_deleted_slug_can_be_used_again(store):
    store.create("again")
    store.delete("again")

    assert store.create("again").slug == "again"
    assert len(list((store.root / ".deleted").iterdir())) == 1


def test_deleting_an_unknown_corpus_is_404_and_leaves_no_recycle_bin(store):
    with pytest.raises(CorpusError) as refused:
        store.delete("missing")

    assert refused.value.status == 404
    assert not (store.root / ".deleted").exists()


def test_deleting_with_a_bad_slug_is_refused(store):
    with pytest.raises(CorpusError):
        store.delete("../outside")


def test_a_symlinked_corpus_cannot_be_deleted(store, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "corpus.json").write_text("{}", encoding="utf-8")
    store.root.mkdir(parents=True)
    (store.root / "linked").symlink_to(target)

    with pytest.raises(CorpusError):
        store.delete("linked")

    assert (target / "corpus.json").is_file()
