"""Passages of a decision: contextual prefix `[<court> <cislo>[ <ecli>]]`, kind body, seq from 0 (P81-11)."""
from __future__ import annotations

from dp_sk_judikatura_ingest.chunker import chunk_rozhodnutie


def _text(characters: int) -> str:
    sentence = "Odsek rozhodnutia obsahuje konkretny pravny profil veci a jeho odovodnenie. "
    return (sentence * (characters // len(sentence) + 1))[:characters]


def test_prefix_with_ecli() -> None:
    pieces = chunk_rozhodnutie("Kratky text rozhodnutia.", "NSSR", "8Cdo/27/2025", "ECLI:SK:NSSR:2026:12345")

    assert pieces[0].text_contextual == "[NSSR 8Cdo/27/2025 ECLI:SK:NSSR:2026:12345]\nKratky text rozhodnutia."
    assert pieces[0].text == "Kratky text rozhodnutia."


def test_prefix_without_ecli_has_no_orphan_space() -> None:
    pieces = chunk_rozhodnutie("Kratky text.", "NSSSR", "1Szk/12/2025", None)

    assert pieces[0].text_contextual.startswith("[NSSSR 1Szk/12/2025]\n")
    assert "  " not in pieces[0].text_contextual.split("\n")[0]
    assert pieces[0].kind == "body"


def test_blank_ecli_is_like_none() -> None:
    assert chunk_rozhodnutie("text.", "NSSR", "1", "  ")[0].text_contextual.startswith("[NSSR 1]\n")


def test_a_2500_character_text_is_one_passage() -> None:
    pieces = chunk_rozhodnutie(_text(2500), "NSSR", "8Cdo/1/2020", None)

    assert len(pieces) == 1
    assert pieces[0].seq == 0


def test_a_20000_character_text_makes_5_to_8_contiguous_passages_whose_text_concatenates_to_the_input() -> None:
    text = _text(20000)

    pieces = chunk_rozhodnutie(text, "NSSR", "8Cdo/1/2020", "ECLI:SK:NSSR:2020:1.1")

    assert 5 <= len(pieces) <= 8
    assert [p.seq for p in pieces] == list(range(len(pieces)))
    assert "".join(p.text for p in pieces) == text
    assert all(p.text_contextual.startswith("[NSSR 8Cdo/1/2020 ECLI:SK:NSSR:2020:1.1]\n") for p in pieces)


def test_blank_text_gives_no_passages() -> None:
    assert chunk_rozhodnutie("", "NSSR", "1", None) == []
    assert chunk_rozhodnutie("   \n ", "NSSR", "1", None) == []
