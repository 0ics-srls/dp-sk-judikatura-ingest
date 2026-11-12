"""Sentence-boundary segmenter: golden cases of the legacy TextSegmenterTests plus the Slovak abbreviation rules (P81-11)."""
from __future__ import annotations

import pytest

from dp_sk_judikatura_ingest.segmenter import MAX_CHARS, MIN_CHARS, TARGET_CHARS, segment


def test_constants() -> None:
    assert (TARGET_CHARS, MIN_CHARS, MAX_CHARS) == (3000, 500, 8000)


def test_sentence_boundaries_concatenation_is_exactly_the_input() -> None:
    text = "".join(f"Veta cislo {i} rozhodnutia obsahuje konkretny pravny profil. " for i in range(1, 51))

    pieces = segment(text)

    assert pieces
    assert "".join(pieces) == text


def test_twenty_thousand_chars_no_piece_over_max() -> None:
    sentence = "Dovolaci sud konstatuje, ze dovolanie zalobcu nie je dovodne z dovodov uvedenych nizsie. "
    text = sentence * 250
    assert len(text) > 20000

    pieces = segment(text)

    assert all(len(p) <= MAX_CHARS for p in pieces)
    assert "".join(pieces) == text


def test_short_tail_is_merged_with_the_previous_piece() -> None:
    big = "a" * 2900 + ". "
    stub = "b" * 300 + "."

    pieces = segment(big + stub)

    if len(pieces) > 1:
        assert all(len(p) >= MIN_CHARS for p in pieces)
    assert pieces[-1].endswith(stub)
    assert "".join(pieces) == big + stub


def test_oversize_text_splits_at_sentence_boundaries_into_target_sized_pieces() -> None:
    sentence = "x" * 99 + ". "
    text = sentence * 100

    pieces = segment(text)

    assert len(pieces) >= 3
    assert all(len(p) <= MAX_CHARS for p in pieces)
    assert all(p.endswith(". ") for p in pieces)
    assert "".join(pieces) == text


def test_a_long_sentence_beyond_max_is_hard_split() -> None:
    text = "y" * 9000

    pieces = segment(text)

    assert all(len(p) <= MAX_CHARS for p in pieces)
    assert "".join(pieces) == text


def test_no_boundary_single_piece_and_empty_text() -> None:
    assert segment("x" * 4000) == ["x" * 4000]
    assert segment("") == []


@pytest.mark.parametrize(
    "abbreviation",
    ["JUDr. Peter Novák", "Mgr. Renáta Gavalcová", "Ing. Ján Kováč, PhD. a ďalší", "sp. zn. 8Cdo/21/2014", "č. k. 5Sžo/221/2010", "podľa § 250d ods. 3 písm. a) O.s.p.", "dňa 26. januára 2017", "M. K. bol uznaný vinným"],
)
def test_slovak_abbreviations_and_ordinals_are_not_sentence_ends(abbreviation: str) -> None:
    # filler so that the abbreviation sits exactly where the first piece would be cut (the target size), then enough text for a second piece
    filler = "x" * (TARGET_CHARS - len(abbreviation) // 2 - 700)
    text = filler + " " + abbreviation + " " + "z" * 1200 + ". " + "w" * 700 + "."

    pieces = segment(text)

    assert "".join(pieces) == text
    for piece in pieces:
        assert not piece.endswith(("JUDr. ", "Mgr. ", "Ing. ", "sp. ", "č. ", "k. ", "ods. ", "písm. ", "M. ", "K. ", "26. ", "PhD. "))


def test_segmentation_is_deterministic_and_stable_on_its_own_output() -> None:
    text = "".join(f"Súd sa zaoberal otázkou č. {i} podľa § 12 ods. 3 zákona. " for i in range(1, 400))

    first = segment(text)

    assert segment(text) == first
    assert segment("".join(first)) == first


def test_slovak_quotes_around_a_sentence_keep_the_text_lossless() -> None:
    text = "".join(f"Súd uviedol: „Dovolanie sa zamieta.“ Ďalej konštatoval, že vec č. {i} je jasná. " for i in range(300))

    pieces = segment(text)

    assert "".join(pieces) == text
    assert all(len(p) <= MAX_CHARS for p in pieces)
