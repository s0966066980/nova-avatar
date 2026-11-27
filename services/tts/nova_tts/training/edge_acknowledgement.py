# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Recorded acknowledgement of the Microsoft Services Agreement clause (ADR 0026).

Edge read-aloud output may only train a Matcha voice model after the
administrator has read the Microsoft Services Agreement §14(s)(iv) text and
confirmed it. The confirmation is a file in the corpus folder, next to the
source declaration (``corpus.json``)::

    data/tts/training/<slug>/msa-acknowledgement.json

It holds the timestamp and the exact clause text that was shown. Nothing in the
service layer creates it: only ``record_acknowledgement`` writes it, and a route
may call that only after the administrator ticked the confirmation box next to
the displayed ``MSA_CLAUSE`` text. ``require_acknowledgement`` is the gate the
synthesis service calls before any request leaves the machine; a record for
different clause wording no longer opens it, so a reworded clause is shown and
confirmed again.

The acknowledgement does not clear anything: a model trained from an
``edge-test-teacher`` corpus is still labelled Development only and is never
exported (``usage``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from nova_tts.training.corpus import CorpusError, CorpusStore
from nova_tts.training.usage import SOURCE_EDGE_TEST_TEACHER
from nova_core.utils.logging import logger

ACKNOWLEDGEMENT_FILE = "msa-acknowledgement.json"
ACKNOWLEDGEMENT_VERSION = 1


@dataclass(frozen=True)
class MsaClause:
    reference: str
    effective: str
    text: str


# Quoted as in THIRD_PARTY_NOTICES.md; the user interface shows exactly this text.
MSA_CLAUSE = MsaClause(
    reference="Microsoft Services Agreement §14(s)(iv)",
    effective="2026-09-30",
    text=(
        "You may not use the AI services, or data from the AI services, to create, "
        "train, or improve (directly or indirectly) any AI technology"
    ),
)


@dataclass(frozen=True)
class Acknowledgement:
    acknowledged_at: str
    clause_reference: str
    clause_effective: str
    clause_text: str


def read_acknowledgement(store: CorpusStore, slug: str) -> Acknowledgement | None:
    """The recorded acknowledgement of a corpus, ``None`` if there is none; a damaged file raises."""
    raw = store.read_sidecar(slug, ACKNOWLEDGEMENT_FILE)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError(f"MSA 確認紀錄無法讀取：{exc}", status=500) from exc
    fields = ("acknowledged_at", "clause_reference", "clause_effective", "clause_text")
    if (
        not isinstance(data, dict)
        or data.get("version") != ACKNOWLEDGEMENT_VERSION
        or data.get("source") != SOURCE_EDGE_TEST_TEACHER
        or not all(isinstance(data.get(name), str) and data[name] for name in fields)
    ):
        raise CorpusError("MSA 確認紀錄格式不符", status=500)
    return Acknowledgement(*(data[name] for name in fields))


def record_acknowledgement(
    store: CorpusStore, slug: str, shown_text: str, *, now: datetime | None = None
) -> Acknowledgement:
    """Record that the administrator confirmed the clause text ``shown_text``.

    ``shown_text`` must be exactly ``MSA_CLAUSE.text``: the record states what
    was displayed, so a different text is refused rather than stored. An
    existing valid record is returned unchanged (the first timestamp stays).
    """
    _require_edge_corpus(store, slug)
    if shown_text != MSA_CLAUSE.text:
        raise CorpusError("顯示給管理者的條文與目前的 MSA 條文不一致，無法記錄確認")
    existing = read_acknowledgement(store, slug)
    if existing is not None and existing.clause_text == MSA_CLAUSE.text:
        return existing
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    record = Acknowledgement(stamp, MSA_CLAUSE.reference, MSA_CLAUSE.effective, MSA_CLAUSE.text)
    payload = {
        "version": ACKNOWLEDGEMENT_VERSION,
        "source": SOURCE_EDGE_TEST_TEACHER,
        "acknowledged_at": record.acknowledged_at,
        "clause_reference": record.clause_reference,
        "clause_effective": record.clause_effective,
        "clause_text": record.clause_text,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    store.write_sidecar(slug, ACKNOWLEDGEMENT_FILE, text.encode("utf-8"))
    logger.info("Recorded MSA acknowledgement for training corpus %s", slug)
    return record


def require_acknowledgement(store: CorpusStore, slug: str) -> Acknowledgement:
    """The acknowledgement of a corpus, or a 403 ``CorpusError`` when synthesis must not start."""
    _require_edge_corpus(store, slug)
    record = read_acknowledgement(store, slug)
    if record is None:
        raise CorpusError(
            f"尚未確認 {MSA_CLAUSE.reference} 條文，不能開始用 Edge 合成語料", status=403
        )
    if record.clause_text != MSA_CLAUSE.text or record.clause_reference != MSA_CLAUSE.reference:
        raise CorpusError(
            f"{MSA_CLAUSE.reference} 的確認紀錄對應的是舊的條文，請重新閱讀並確認", status=403
        )
    return record


def _require_edge_corpus(store: CorpusStore, slug: str) -> None:
    if store.get(slug).source != SOURCE_EDGE_TEST_TEACHER:
        raise CorpusError("只有來源為 Edge 測試用老師的語料需要 MSA 確認", status=409)
