"""Passages of a decision (port of the branch-53 SkGiurisChunker).

No header is known, so every piece is a body piece: the sentence-boundary segmenter over ``text_raw`` with the contextual prefix
``[<court> <cislo>[ <ecli>]]`` in front of the embedded text (P81-11; the legacy prefix carried the chamber, the ECLI identifies the decision better).
Pure, deterministic, lossless: ``"".join(p.text) == text_raw``.
"""
from __future__ import annotations

from dataclasses import dataclass

from dp_sk_judikatura_ingest.segmenter import segment


@dataclass(frozen=True)
class Piece:
    """One embeddable passage: ``text`` is stored and shown, ``text_contextual`` (prefix + text) is what gets embedded."""

    seq: int
    kind: str
    text: str
    text_contextual: str


def _prefix(court: str, cislo: str, ecli: str | None) -> str:
    out = f"[{court} {cislo}"
    if ecli is not None and ecli.strip():
        out += f" {ecli.strip()}"
    return out + "]\n"


def chunk_rozhodnutie(text_raw: str, court: str, cislo: str, ecli: str | None) -> list[Piece]:
    """The passages of one decision, ``seq`` from 0; no passages for a blank text."""
    if not text_raw or not text_raw.strip():
        return []
    prefix = _prefix(court, cislo, ecli)
    return [Piece(seq, "body", text, prefix + text) for seq, text in enumerate(segment(text_raw))]
