"""Test builders: plan files (schema v1), item entries and a fake psycopg connection that records statements and transaction boundaries."""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
LONG_TEXT = "Dovolaci sud konstatuje, ze dovolanie zalobcu nie je dovodne z dovodov uvedenych v odovodneni tohto rozhodnutia. " * 90


def safe_name(item_id: str) -> str:
    return _UNSAFE.sub("_", item_id.replace(" ", "-"))


def item(item_id: str = "nsud:2026-09", *, from_: str | None = "2026-09-01", to: str | None = "2026-09-30") -> dict[str, Any]:
    meta: dict[str, Any] = {"kind": "nsud", "itemId": item_id, "version": "1"}
    if from_ and to:
        meta.update({"from": from_, "to": to})
    return {"key": f"{item_id}|1", "meta": meta}


def decision(source_id: str = "150000", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "fonte": "nsud",
        "source_id": source_id,
        "court": "NSSR",
        "cislo": "7Sžo/65/2016",
        "senat": "7",
        "ecli": "ECLI:SK:NSSR:2017:7015201167.1",
        "datum_rozhodnutia": "2017-01-26",
        "kolegium": "3",
        "kolegium_nazov": "Správne",
        "merito": "katastrálne veci",
        "sudca": "JUDr. Zdenka Reisenauerová",
        "text_raw": "Najvyšší súd Slovenskej republiky v právnej veci navrhovateľa rozhodol o dovolaní. Dovolanie zamietol. ",
        "text_source": "api",
        "source_url": "https://www.nsud.sk/data/att/x/1.pdf",
        "pdf_url": "https://www.nsud.sk/data/att/x/1.pdf",
        "pii_flags": 0,
    }
    base.update(overrides)
    return base


def new_plan(
    rows: list[dict[str, Any]] | None = None, skipped: list[dict[str, str]] | None = None, coverage: dict[str, Any] | None = None, warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {"planVersion": 1, "rozhodnutia": rows or [], "skipped": skipped or [], "coverage": coverage, "warnings": warnings or []}


def window(listed: int = 3, taken: int = 1, pdf_only: int = 0) -> dict[str, Any]:
    return {"window_from": "2026-09-01", "window_to": "2026-09-30", "ids_listed": listed, "ids_taken": taken, "pdf_only": pdf_only}


def write_plan(directory: Path, item_id: str, plan: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_name(item_id)}.plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return path


class FakeCursor:
    """Records (kind, sql, params); ``RETURNING id`` answers a deterministic uuid; ``fail_on`` makes the statement containing that text raise."""

    def __init__(self, log: list[tuple[str, str, Any]], fail_on: str | None) -> None:
        self._log = log
        self._fail_on = fail_on

    def execute(self, sql: Any, params: Any = None) -> FakeCursor:
        text = str(sql)
        if self._fail_on and self._fail_on in text:
            msg = f"boom in {self._fail_on}"
            raise RuntimeError(msg)
        self._log.append(("execute", text, params))
        return self

    def executemany(self, sql: Any, params: Any) -> None:
        if self._fail_on and self._fail_on in str(sql):
            msg = f"boom in {self._fail_on}"
            raise RuntimeError(msg)
        self._log.append(("executemany", str(sql), list(params)))

    def fetchone(self) -> tuple[Any, ...]:
        return (uuid.UUID(int=len(self._log)),)


class FakeConnection:
    """Records statements and transaction boundaries."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.log: list[tuple[str, str, Any]] = []
        self.events: list[str] = []
        self.closed = False
        self._fail_on = fail_on

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.events.append("begin")
        try:
            yield
        except BaseException:
            self.events.append("rollback")
            raise
        self.events.append("commit")

    @contextmanager
    def cursor(self) -> Iterator[FakeCursor]:
        yield FakeCursor(self.log, self._fail_on)

    def execute(self, sql: Any, params: Any = None) -> FakeCursor:
        return FakeCursor(self.log, self._fail_on).execute(sql, params)

    def close(self) -> None:
        self.closed = True
