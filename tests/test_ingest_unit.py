"""run_ingest with a fake connection: statement order, parameters, transactions, the embedding rule, skipped and coverage, dry run, metrics, secrets."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest

from builders import LONG_TEXT, FakeConnection, decision, item, new_plan, window, write_plan
from dp_sk_judikatura_ingest.errors import CONFIG_ERROR, SYSTEM_ERROR, TRANSIENT_ERROR, IngestError
from dp_sk_judikatura_ingest.ingest import run_ingest

CONN = "Host=db;Port=5432;Database=lex;Username=ds_sk_judikatura_rw;Password=s3cr3t-pw"
SCHEMA = "ds_sk_judikatura"
ITEM_ID = "nsud:2026-09"


def params(directory: Path, *items: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"items": list(items), "dirIn": str(directory), "connString": CONN, "schema": SCHEMA, **extra}


def run(directory: Path, connection: FakeConnection, *items: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return run_ingest(params(directory, *items, **extra), lambda _dsn: connection, lambda *_: None)


def kinds(connection: FakeConnection) -> list[str]:
    return [" ".join(sql.split()[:3]) for _, sql, _ in connection.log]


def statement(connection: FakeConnection, text: str) -> tuple[str, str, Any]:
    return next(entry for entry in connection.log if text in entry[1])


@pytest.mark.unit
def test_a_decision_item_runs_the_statements_in_order_inside_one_transaction(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision()], coverage=window()))
    connection = FakeConnection()

    result = run(tmp_path, connection, item())

    assert connection.events == ["begin", "commit"]
    assert kinds(connection) == [
        "SET search_path TO",
        "INSERT INTO rozhodnutia",
        "INSERT INTO passages",
        "DELETE FROM passages",
        "DELETE FROM skipped",
        "INSERT INTO coverage",
    ]
    assert statement(connection, "SET search_path")[1] == f"SET search_path TO {SCHEMA}, public"
    assert connection.closed
    assert result["loaded"] == [f"{ITEM_ID}|1"]
    assert result["metrics"][f"written.{SCHEMA}.rozhodnutia"] == 1
    assert result["metrics"][f"written.{SCHEMA}.passages"] == 1
    assert result["metrics"][f"written.{SCHEMA}.coverage"] == 1


@pytest.mark.unit
def test_the_decision_is_upserted_on_fonte_and_source_id_keeping_the_id(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision(pii_flags=2)]))
    connection = FakeConnection()

    run(tmp_path, connection, item())

    _, sql, args = statement(connection, "INSERT INTO rozhodnutia")
    assert "ON CONFLICT (fonte, source_id) DO UPDATE" in sql
    assert "RETURNING id" in sql
    assert not re.search(r"(?<![a-z_])id = ", sql.split("DO UPDATE SET")[1]), "the id of an existing decision is never replaced"
    assert "search_vector" not in sql, "the generated column is never written"
    assert args[0:4] == ("nsud", "150000", "NSSR", "7Sžo/65/2016")
    assert args[-1] == 2
    assert "ingested_at = CASE WHEN" in sql


@pytest.mark.unit
def test_passages_keep_the_embedding_only_when_the_contextual_text_is_unchanged(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision()]))
    connection = FakeConnection()

    run(tmp_path, connection, item())

    _, sql, rows = statement(connection, "INSERT INTO passages")
    assert "ON CONFLICT (rozhodnutie_id, seq) DO UPDATE" in sql
    assert "CASE WHEN passages.text_contextual IS DISTINCT FROM EXCLUDED.text_contextual THEN NULL ELSE passages.embedding END" in sql
    assert len(rows) == 1
    assert rows[0][1] == 0
    assert rows[0][3].startswith("[NSSR 7Sžo/65/2016 ECLI:SK:NSSR:2017:7015201167.1]\n")


@pytest.mark.unit
def test_surplus_passages_of_the_decision_are_deleted(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision(text_raw=LONG_TEXT)]))
    connection = FakeConnection()

    run(tmp_path, connection, item())

    _, _, rows = statement(connection, "INSERT INTO passages")
    _, sql, args = statement(connection, "DELETE FROM passages")
    assert len(rows) >= 3
    assert "NOT (seq = ANY" in sql
    assert args[1] == [r[1] for r in rows]


@pytest.mark.unit
def test_a_now_ingested_decision_clears_its_stale_skipped_row(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision("177749")]))
    connection = FakeConnection()

    run(tmp_path, connection, item())

    _, sql, args = statement(connection, "DELETE FROM skipped")
    assert "fonte = %s AND item_ref = ANY" in sql
    assert args == ("nsud", ["nsud:177749"])


@pytest.mark.unit
def test_skipped_rows_are_upserted_on_their_natural_key(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan(skipped=[{"item_ref": "nsud:5", "reason": "parse_error"}, {"item_ref": "nsud:6", "reason": "ocr_empty"}], warnings=["nsud:7: odd_ecli"]))
    connection = FakeConnection()

    result = run(tmp_path, connection, item())

    assert "INSERT INTO rozhodnutia" not in " ".join(kinds(connection))
    _, sql, rows = statement(connection, "INSERT INTO skipped")
    assert "ON CONFLICT (fonte, item_ref) DO UPDATE" in sql
    assert rows == [("nsud", "nsud:5", "parse_error"), ("nsud", "nsud:6", "ocr_empty")]
    assert result["metrics"][f"written.{SCHEMA}.skipped"] == 2
    assert result["metrics"]["skipped_documents"] == 2
    assert result["metrics"]["warnings"] == 1


@pytest.mark.unit
def test_the_coverage_window_is_replaced_by_its_natural_key(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision()], coverage=window(listed=27, taken=25, pdf_only=2)))
    connection = FakeConnection()

    run(tmp_path, connection, item())

    _, sql, args = statement(connection, "INSERT INTO coverage")
    assert "ON CONFLICT (fonte, window_from, window_to) DO UPDATE" in sql
    assert args == ("nsud", "2026-09-01", "2026-09-30", 27, 25, 2)


@pytest.mark.unit
def test_an_explicit_ids_item_has_no_coverage_row(tmp_path: Path) -> None:
    write_plan(tmp_path, "nsud:ids", new_plan([decision()]))
    connection = FakeConnection()

    result = run(tmp_path, connection, item("nsud:ids", from_=None, to=None))

    assert "INSERT INTO coverage" not in " ".join(kinds(connection))
    assert result["metrics"][f"written.{SCHEMA}.coverage"] == 0


@pytest.mark.unit
def test_a_decision_with_empty_text_is_refused_and_not_written(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision(text_raw="   ")]))
    connection = FakeConnection()

    with pytest.raises(IngestError) as caught:
        run(tmp_path, connection, item())

    assert caught.value.code == SYSTEM_ERROR
    assert "INSERT INTO rozhodnutia" not in " ".join(kinds(connection))


@pytest.mark.unit
def test_dry_run_rolls_back_the_item(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision()], coverage=window()))
    connection = FakeConnection()

    result = run(tmp_path, connection, item(), dryRun=True)

    assert connection.events == ["begin", "rollback"]
    assert result["metrics"][f"written.{SCHEMA}.rozhodnutia"] == 1, "the counts say what would have been written"
    assert result["loaded"] == [f"{ITEM_ID}|1"]


@pytest.mark.unit
def test_null_dry_run_is_absent(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision()]))
    connection = FakeConnection()

    run(tmp_path, connection, item(), dryRun=None)

    assert connection.events == ["begin", "commit"]


@pytest.mark.unit
def test_two_items_run_in_two_transactions_and_a_failing_one_rolls_back_alone(tmp_path: Path) -> None:
    other = "nsud:2026-10"
    write_plan(tmp_path, ITEM_ID, new_plan([decision()]))
    write_plan(tmp_path, other, new_plan([decision("2")], coverage={**window(), "window_from": "2026-10-01", "window_to": "2026-10-31"}))
    connection = FakeConnection(fail_on="INSERT INTO coverage")

    with pytest.raises(IngestError) as caught:
        run(tmp_path, connection, item(), item(other, from_="2026-10-01", to="2026-10-31"))

    assert connection.events == ["begin", "commit", "begin", "rollback"]
    assert caught.value.code == SYSTEM_ERROR
    assert f"{other}|1" in str(caught.value)
    assert "s3cr3t-pw" not in str(caught.value)


@pytest.mark.unit
def test_the_failure_message_and_the_log_never_carry_the_password(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision()]))

    def refuse(_dsn: str) -> FakeConnection:
        raise OSError(CONN)

    with caplog.at_level(logging.DEBUG), pytest.raises(IngestError) as caught:
        run_ingest(params(tmp_path, item()), refuse, lambda *_: None)

    assert caught.value.code == TRANSIENT_ERROR
    assert "s3cr3t-pw" not in str(caught.value)
    assert "s3cr3t-pw" not in caplog.text


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [{"items": []}, {"dirIn": ""}, {"connString": ""}, {"schema": "public"}, {"schema": "ds_x; DROP"}, {"items": [{"key": "k", "meta": {"kind": "gazzetta", "itemId": "x"}}]}],
)
def test_bad_parameters_are_config_errors(tmp_path: Path, bad: dict[str, Any]) -> None:
    merged = {**params(tmp_path, item()), **bad}

    with pytest.raises(IngestError) as caught:
        run_ingest(merged, lambda _dsn: FakeConnection(), lambda *_: None)

    assert caught.value.code == CONFIG_ERROR


@pytest.mark.unit
def test_a_plan_that_breaks_the_schema_fails_the_item_before_the_database_is_touched(tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan([decision(text_source="scan")]))
    connection = FakeConnection()

    with pytest.raises(IngestError):
        run(tmp_path, connection, item())

    assert connection.events == []


@pytest.mark.unit
def test_a_missing_plan_file_fails_the_item(tmp_path: Path) -> None:
    with pytest.raises(IngestError) as caught:
        run(tmp_path, FakeConnection(), item())

    assert caught.value.code == SYSTEM_ERROR
