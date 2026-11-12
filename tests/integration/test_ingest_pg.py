"""Real Postgres + pgvector (Testcontainers) with the package migrations applied; no Jina call (embeddings are set by SQL)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from builders import LONG_TEXT, decision, item, new_plan, window, write_plan
from dp_sk_judikatura_ingest.db import connect
from dp_sk_judikatura_ingest.errors import IngestError
from dp_sk_judikatura_ingest.ingest import run_ingest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

SCHEMA = "ds_sk_judikatura"
VECTOR = "[" + ",".join(["0.25"] * 1024) + "]"
ITEM_ID = "nsud:2026-09"


def migrations_dir() -> Path:
    """The package migrations next to this class repo; resolved lazily so collecting the module in a container (no sibling repo) cannot fail."""
    for parent in Path(__file__).resolve().parents:
        for candidate in (parent / "dp-sk-judikatura" / "schema" / "migrations", parent.parent / "dp-sk-judikatura" / "schema" / "migrations"):
            if candidate.is_dir():
                return candidate
    msg = "package migrations (dp-sk-judikatura/schema/migrations) not found next to this repo"
    raise FileNotFoundError(msg)


class Db:
    def __init__(self, container: PostgresContainer) -> None:
        self.dsn = container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        self.conn_string = (
            f"Host={container.get_container_host_ip()};Port={container.get_exposed_port(5432)};"
            f"Database={container.dbname};Username={container.username};Password={container.password}"
        )

    def scalar(self, sql: str) -> Any:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            row = conn.execute(sql).fetchone()
            assert row is not None
            return row[0]

    def execute(self, sql: str) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(sql)

    def ingest(self, directory: Path, *items: dict[str, Any]) -> dict[str, Any]:
        params = {"items": list(items), "dirIn": str(directory), "connString": self.conn_string, "schema": SCHEMA}
        return run_ingest(params, connect, lambda *_: None)

    def count(self, table: str, where: str = "true") -> int:
        return int(self.scalar(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE {where}"))


@pytest.fixture(scope="module")
def container() -> Iterator[PostgresContainer]:
    with PostgresContainer("pgvector/pgvector:pg17", username="lex", password="pw", dbname="lex") as pg:
        yield pg


@pytest.fixture
def db(container: PostgresContainer) -> Db:
    database = Db(container)
    database.execute("CREATE EXTENSION IF NOT EXISTS vector")
    database.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    database.execute(f"CREATE SCHEMA {SCHEMA}")
    with psycopg.connect(database.dsn, autocommit=True) as conn:
        conn.execute(f"SET search_path TO {SCHEMA}, public")
        for migration in sorted(migrations_dir().glob("*.sql")):
            conn.execute(migration.read_text(encoding="utf-8"))
    return database


def three(tmp_path: Path) -> None:
    rows = [decision("1", cislo="1Cdo/1/2020", text_raw=LONG_TEXT), decision("2", cislo="2Cdo/2/2020", ecli=None), decision("3", cislo="3Cdo/3/2020", text_source="pdf")]
    write_plan(tmp_path, ITEM_ID, new_plan(rows, skipped=[{"item_ref": "nsud:9", "reason": "parse_error"}], coverage=window(listed=4, taken=3, pdf_only=1)))


def embed_everything(db: Db) -> None:
    db.execute(f"UPDATE {SCHEMA}.passages SET embedding = '{VECTOR}'::vector")


@pytest.mark.integration
def test_loading_the_same_plan_twice_keeps_the_row_counts_stable(db: Db, tmp_path: Path) -> None:
    three(tmp_path)

    db.ingest(tmp_path, item())
    first = (db.count("rozhodnutia"), db.count("passages"), db.count("skipped"), db.count("coverage"))
    ingested = db.scalar(f"SELECT max(ingested_at) FROM {SCHEMA}.rozhodnutia")
    db.ingest(tmp_path, item())

    assert first[0] == 3
    assert first[1] >= 5
    assert (db.count("rozhodnutia"), db.count("passages"), db.count("skipped"), db.count("coverage")) == first
    assert db.scalar(f"SELECT max(ingested_at) FROM {SCHEMA}.rozhodnutia") == ingested, "an unchanged decision does not move ingested_at"
    assert db.count("rozhodnutia", "search_vector IS NOT NULL") == 3


@pytest.mark.integration
def test_a_changed_text_replaces_its_passages_and_keeps_the_other_embeddings(db: Db, tmp_path: Path) -> None:
    three(tmp_path)
    db.ingest(tmp_path, item())
    embed_everything(db)
    rows = [decision("1", cislo="1Cdo/1/2020", text_raw="Úplne nový krátky text rozhodnutia. "), decision("2", cislo="2Cdo/2/2020", ecli=None), decision("3", cislo="3Cdo/3/2020", text_source="pdf")]
    write_plan(tmp_path, ITEM_ID, new_plan(rows, coverage=window(listed=3, taken=3)))

    db.ingest(tmp_path, item())

    first_id = f"(SELECT id FROM {SCHEMA}.rozhodnutia WHERE source_id = '1')"
    assert db.count("passages", f"rozhodnutie_id = {first_id}") == 1
    assert db.count("passages", f"rozhodnutie_id = {first_id} AND embedding IS NULL") == 1
    assert db.count("passages", f"rozhodnutie_id <> {first_id} AND embedding IS NULL") == 0
    assert db.count("passages", f"rozhodnutie_id <> {first_id}") >= 2


@pytest.mark.integration
def test_skipped_and_coverage_are_replaced_not_duplicated(db: Db, tmp_path: Path) -> None:
    three(tmp_path)
    db.ingest(tmp_path, item())
    write_plan(tmp_path, ITEM_ID, new_plan([decision("1", text_raw=LONG_TEXT)], skipped=[{"item_ref": "nsud:9", "reason": "ocr_empty"}], coverage=window(listed=9, taken=1, pdf_only=0)))

    db.ingest(tmp_path, item())

    assert db.count("skipped") == 1
    assert db.scalar(f"SELECT reason FROM {SCHEMA}.skipped WHERE item_ref = 'nsud:9'") == "ocr_empty"
    assert db.count("coverage") == 1
    assert db.scalar(f"SELECT ids_listed FROM {SCHEMA}.coverage") == 9


@pytest.mark.integration
def test_a_decision_that_is_ingested_later_clears_its_skipped_row(db: Db, tmp_path: Path) -> None:
    write_plan(tmp_path, ITEM_ID, new_plan(skipped=[{"item_ref": "nsud:9", "reason": "ocr_unavailable"}]))
    db.ingest(tmp_path, item())
    assert db.count("skipped") == 1

    write_plan(tmp_path, ITEM_ID, new_plan([decision("9")]))
    db.ingest(tmp_path, item())

    assert db.count("skipped") == 0
    assert db.count("rozhodnutia") == 1


@pytest.mark.integration
def test_a_bad_row_rolls_the_whole_item_back(db: Db, tmp_path: Path) -> None:
    rows = [decision("1"), decision("2", court="KSBA")]
    write_plan(tmp_path, ITEM_ID, new_plan(rows))

    with pytest.raises(IngestError):
        db.ingest(tmp_path, item())

    assert db.count("rozhodnutia") == 0
    assert db.count("passages") == 0


@pytest.mark.integration
def test_dry_run_leaves_the_database_untouched(db: Db, tmp_path: Path) -> None:
    three(tmp_path)

    params = {"items": [item()], "dirIn": str(tmp_path), "connString": db.conn_string, "schema": SCHEMA, "dryRun": True}
    run_ingest(params, connect, lambda *_: None)

    assert db.count("rozhodnutia") == 0
