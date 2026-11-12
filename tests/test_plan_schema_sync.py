"""plan.schema.json is one file kept in two class repos (convert writes the plan, ingest reads it): both must be equal.

The sibling repo is looked up lazily; where it is absent (the ProcMon test container holds this repo only) the comparison is skipped and the file is
still checked on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


def _own() -> Path:
    return Path(__file__).resolve().parent.parent / "plan.schema.json"


def _sibling() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "dp-sk-judikatura-convert" / "plan.schema.json"
        if candidate.is_file():
            return candidate
    return None


@pytest.mark.unit
def test_the_schema_is_valid() -> None:
    Draft202012Validator.check_schema(json.loads(_own().read_text(encoding="utf-8")))


@pytest.mark.unit
def test_the_two_repos_carry_the_same_plan_schema() -> None:
    other = _sibling()
    if other is None:
        pytest.skip("dp-sk-judikatura-convert is not next to this repo")

    assert json.loads(other.read_text(encoding="utf-8")) == json.loads(_own().read_text(encoding="utf-8"))
