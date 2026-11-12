"""SQL of one item (plan file v1): decisions, passages, skipped items and coverage.

All statements run inside one transaction opened by the caller; the dataset schema is on the search_path (names are unqualified). The rules:

* a decision is upserted on ``(fonte, source_id)``; its ``id`` survives and ``ingested_at`` moves only when something changed (a second ingest of the
  same plan is a no-op); the generated ``search_vector`` is never written;
* passages are upserted on ``(rozhodnutie_id, seq)``: the embedding is KEPT when ``text_contextual`` is unchanged and set NULL when it changed, and the
  passages beyond the current set are deleted (P78-06);
* ``skipped`` and ``coverage`` are upserted on their natural keys; a decision that is now ingested clears its stale ``skipped`` row.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from dp_sk_judikatura_ingest.chunker import chunk_rozhodnutie

if TYPE_CHECKING:
    from collections.abc import Iterable

TABLES = ("rozhodnutia", "passages", "skipped", "coverage")

ROZHODNUTIE_COLUMNS = (
    "fonte", "source_id", "court", "cislo", "senat", "ecli", "datum_rozhodnutia", "kolegium", "kolegium_nazov", "merito", "sudca", "text_raw",
    "text_source", "source_url", "pdf_url", "pii_flags",
)
_SET_ALL = ", ".join(f"{c} = EXCLUDED.{c}" for c in ROZHODNUTIE_COLUMNS)
_OLD = ", ".join(f"rozhodnutia.{c}" for c in ROZHODNUTIE_COLUMNS)
_NEW = ", ".join(f"EXCLUDED.{c}" for c in ROZHODNUTIE_COLUMNS)

UPSERT_ROZHODNUTIE = f"""
INSERT INTO rozhodnutia ({", ".join(ROZHODNUTIE_COLUMNS)}, ingested_at)
VALUES ({", ".join(["%s"] * len(ROZHODNUTIE_COLUMNS))}, now())
ON CONFLICT (fonte, source_id) DO UPDATE SET {_SET_ALL},
    ingested_at = CASE WHEN ({_OLD}) IS DISTINCT FROM ({_NEW}) THEN now() ELSE rozhodnutia.ingested_at END
RETURNING id
"""

# Text changed -> the embedding is stale: NULL it; identical contextual text keeps it.
UPSERT_PASSAGE = """
INSERT INTO passages (rozhodnutie_id, seq, text, text_contextual) VALUES (%s, %s, %s, %s)
ON CONFLICT (rozhodnutie_id, seq) DO UPDATE SET
    text = EXCLUDED.text,
    embedding = CASE WHEN passages.text_contextual IS DISTINCT FROM EXCLUDED.text_contextual THEN NULL ELSE passages.embedding END,
    text_contextual = EXCLUDED.text_contextual
"""
DELETE_SURPLUS_PASSAGES = "DELETE FROM passages WHERE rozhodnutie_id = %s AND NOT (seq = ANY(%s::int[]))"

CLEAR_SKIPPED = "DELETE FROM skipped WHERE fonte = %s AND item_ref = ANY(%s)"
UPSERT_SKIPPED = """
INSERT INTO skipped (fonte, item_ref, reason) VALUES (%s, %s, %s)
ON CONFLICT (fonte, item_ref) DO UPDATE SET reason = EXCLUDED.reason, seen_at = now()
"""
UPSERT_COVERAGE = """
INSERT INTO coverage (fonte, window_from, window_to, ids_listed, ids_taken, pdf_only) VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (fonte, window_from, window_to) DO UPDATE SET
    ids_listed = EXCLUDED.ids_listed, ids_taken = EXCLUDED.ids_taken, pdf_only = EXCLUDED.pdf_only, noted_at = now()
"""


class Cursor(Protocol):
    def execute(self, sql: Any, params: Any = None) -> Any: ...

    def executemany(self, sql: Any, params: Iterable[Any]) -> Any: ...


def write_rozhodnutie(cursor: Cursor, row: dict[str, Any]) -> dict[str, int]:
    """Writes one decision with its passages; returns the row counts."""
    if not isinstance(row["text_raw"], str) or not row["text_raw"].strip():
        msg = f"{row['source_id']}: empty text, the plan is not written"
        raise ValueError(msg)
    found = cursor.execute(UPSERT_ROZHODNUTIE, tuple(row[c] for c in ROZHODNUTIE_COLUMNS)).fetchone()
    rozhodnutie_id = found[0]
    pieces = chunk_rozhodnutie(row["text_raw"], row["court"], row["cislo"], row["ecli"])
    if pieces:
        cursor.executemany(UPSERT_PASSAGE, [(rozhodnutie_id, p.seq, p.text, p.text_contextual) for p in pieces])
    cursor.execute(DELETE_SURPLUS_PASSAGES, (rozhodnutie_id, [p.seq for p in pieces]))
    cursor.execute(CLEAR_SKIPPED, (row["fonte"], [f"{row['fonte']}:{row['source_id']}"]))
    return {"rozhodnutia": 1, "passages": len(pieces)}


def write_skipped(cursor: Cursor, rows: list[tuple[str, str, str]]) -> int:
    if rows:
        cursor.executemany(UPSERT_SKIPPED, rows)
    return len(rows)


def write_coverage(cursor: Cursor, fonte: str, coverage: dict[str, Any]) -> int:
    cursor.execute(
        UPSERT_COVERAGE,
        (fonte, coverage["window_from"], coverage["window_to"], coverage["ids_listed"], coverage["ids_taken"], coverage["pdf_only"]),
    )
    return 1
