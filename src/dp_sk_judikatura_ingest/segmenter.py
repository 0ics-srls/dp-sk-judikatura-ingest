"""Sentence-boundary segmentation (port of the branch-53 TextSegmenter, found at src/LexCorpus.Data/TextSegmenter.cs).

Accumulates sentences into pieces of about ``TARGET_CHARS``, merges a tail shorter than ``MIN_CHARS`` into the previous piece and hard-cuts anything above
``MAX_CHARS`` (the embedding input limit). Lossless: ``"".join(segment(text)) == text``.

Difference from the legacy (P81-11): a dot after a Slovak abbreviation (JUDr., Mgr., sp. zn., č. k., ods., písm.), after a single letter (initials) or
after an ordinal number before a lower-case word (``26. januára``) is not a sentence end, so a piece never ends in the middle of a case number or a name.
"""
from __future__ import annotations

import re

TARGET_CHARS = 3000
MIN_CHARS = 500
MAX_CHARS = 8000

_SENTENCE_END = re.compile(r"\.\s+")
_ABBREVIATIONS = frozenset(
    {
        "judr", "mudr", "mvdr", "ing", "mgr", "bc", "dr", "phd", "csc", "prof", "doc", "phdr", "paeddr", "rndr", "artd",
        "č", "čl", "čís", "sp", "zn", "ods", "odst", "písm", "pís", "napr", "tzv", "resp", "tj", "príp", "str", "bod", "sv", "tel", "pozn",
        "atď", "pod", "vr", "zák", "nár", "uzn", "rozh", "zb", "st",
    },
)
_LAST_TOKEN = re.compile(r"([^\W\d_]+|\d+)$")


def _is_sentence_end(text: str, match: re.Match[str]) -> bool:
    """False when the dot belongs to an abbreviation, an initial/single letter or an ordinal (``26. januára``)."""
    token = _LAST_TOKEN.search(text[max(0, match.start() - 12) : match.start()])
    if token is None:
        return True
    word = token.group(1)
    if word.isdigit():
        following = text[match.end() : match.end() + 1]
        return not following.islower()
    if len(word) == 1:
        return False
    return word.lower() not in _ABBREVIATIONS


def _split_sentences(text: str) -> list[str]:
    """Cut after every real sentence end; each segment keeps its own delimiter so the concatenation reproduces the input."""
    segments: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        if not _is_sentence_end(text, match):
            continue
        segments.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        segments.append(text[start:])
    return segments


def segment(text: str) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in _split_sentences(text):
        if current and len(current) + len(sentence) > TARGET_CHARS and len(current) >= MIN_CHARS:
            pieces.append(current)
            current = ""
        current += sentence
    if current:
        if pieces and len(current) < MIN_CHARS:
            pieces[-1] += current
        else:
            pieces.append(current)

    capped: list[str] = []
    for piece in pieces:
        if len(piece) <= MAX_CHARS:
            capped.append(piece)
            continue
        capped.extend(piece[i : i + MAX_CHARS] for i in range(0, len(piece), MAX_CHARS))
    return capped
