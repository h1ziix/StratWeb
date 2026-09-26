from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import duckdb
import pytest

from stratweb.adapters.persistence import _bulk


def test_columnar_batches_preserve_uuid_json_and_constraints(monkeypatch: Any) -> None:
    monkeypatch.setattr(_bulk, "_BATCH_SIZE", 2)
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE evidence (id UUID PRIMARY KEY, payload JSON NOT NULL, "
        "lookup_key VARCHAR NOT NULL, tick INTEGER CHECK (tick >= 0))"
    )
    ids = [uuid4() for _ in range(5)]
    rows = [
        [identifier, json.dumps({"name": "игрок", "missing": None, "x": 1.25}), f"key:{i}", i]
        for i, identifier in enumerate(ids)
    ]

    class CountedConnection:
        def __init__(self) -> None:
            self.inserts = 0
            self.registered: list[str] = []

        def register(self, name: str, frame: Any) -> None:
            assert frame.height <= 2
            self.registered.append(name)
            connection.register(name, frame)

        def execute(self, sql: str) -> Any:
            assert "INSERT" in sql and "SELECT" in sql
            self.inserts += 1
            return connection.execute(sql)

        def unregister(self, name: str) -> None:
            self.registered.remove(name)
            connection.unregister(name)

    counted = CountedConnection()
    connection.execute("BEGIN")
    _bulk.insert_rows(counted, "evidence", ("id", "payload", "lookup_key", "tick"), rows)
    connection.execute("COMMIT")
    actual = connection.execute("SELECT * FROM evidence ORDER BY tick").fetchall()
    assert [row[0] for row in actual] == ids
    assert all(json.loads(row[1]) == json.loads(rows[0][1]) for row in actual)
    assert [row[2] for row in actual] == [f"key:{i}" for i in range(5)]
    assert counted.inserts == 3 and counted.registered == []
    connection.close()


@pytest.mark.parametrize("bad_value", [-1, None])
def test_later_batch_error_rolls_back_prior_batches_and_unregisters(
    monkeypatch: Any, bad_value: int | None
) -> None:
    monkeypatch.setattr(_bulk, "_BATCH_SIZE", 2)
    connection = duckdb.connect()
    connection.execute("CREATE TABLE evidence (tick INTEGER NOT NULL CHECK (tick >= 0))")
    connection.execute("INSERT INTO evidence VALUES (42)")
    connection.execute("BEGIN")
    with pytest.raises(duckdb.ConstraintException):
        _bulk.insert_rows(connection, "evidence", ("tick",), [[1], [2], [bad_value]])
    connection.execute("ROLLBACK")
    assert connection.execute("SELECT * FROM evidence").fetchall() == [(42,)]
    with pytest.raises(duckdb.CatalogException):
        connection.execute("SELECT * FROM _stratweb_bulk_evidence")
    _bulk.insert_rows(connection, "evidence", ("tick",), [[3]])
    assert connection.execute("SELECT count(*) FROM evidence").fetchone() == (2,)
    connection.close()
