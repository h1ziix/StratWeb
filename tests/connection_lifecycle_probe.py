"""Killable, event-controlled concurrency regression for the connection pool."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

from stratweb.adapters.persistence import DuckDBMatchRepository
from stratweb.adapters.persistence._connections import (
    close_database_connections,
    get_connection_manager,
    maintenance_read_connection,
    read_connection,
    read_session,
    write_connection,
)
from stratweb.adapters.persistence.write_coordinator import get_write_coordinator
from stratweb.application.canonicalization import compute_dataset_fingerprint


def main(database: Path) -> None:
    matches = DuckDBMatchRepository(database)
    matches.initialize()
    with write_connection(database) as conn:
        conn.execute("CREATE TABLE connection_probe (value INTEGER)")
        conn.execute("INSERT INTO connection_probe VALUES (0)")
    barrier = Barrier(4, timeout=10)
    committed = Event()
    handles = []

    def reader() -> int:
        with read_session(database) as conn:
            handles.append(conn)
            assert conn.execute("SELECT value FROM connection_probe").fetchone() == (0,)
            with read_connection(database, "probe") as nested:
                assert nested is conn
            barrier.wait()
            assert committed.wait(10)
            assert conn.execute("SELECT value FROM connection_probe").fetchone() == (0,)
        with read_connection(database, "probe") as fresh:
            assert fresh.execute("SELECT value FROM connection_probe").fetchone() == (1,)
        return 1

    def writer() -> None:
        barrier.wait()
        with write_connection(database) as conn:
            handles.append(conn)
            conn.execute("BEGIN TRANSACTION")
            conn.execute("UPDATE connection_probe SET value=1")
            conn.execute("COMMIT")
        committed.set()

    with ThreadPoolExecutor(max_workers=4) as executor:
        readers = [executor.submit(reader) for _ in range(3)]
        writing = executor.submit(writer)
        assert sum(f.result(timeout=15) for f in readers) == 3
        writing.result(timeout=15)
    assert len({id(conn) for conn in handles}) == 4

    # Several writers updating the same row must not lose increments or conflict.
    barrier = Barrier(6, timeout=10)

    def increment() -> None:
        barrier.wait()
        for _ in range(20):
            with write_connection(database) as conn:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("UPDATE connection_probe SET value=value+1")
                conn.execute("COMMIT")

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(increment) for _ in range(6)]
        for future in futures:
            future.result(timeout=15)
    with read_connection(database, "probe") as conn:
        assert conn.execute("SELECT value FROM connection_probe").fetchone() == (121,)

    # Canonical replacement is atomic for composed reads across repositories.
    from conftest import canonical_dataset_factory

    dataset = canonical_dataset_factory.__wrapped__()("concurrent-replacement")
    matches.save_match(dataset)
    changed = dataset.model_copy(
        update={"match": dataset.match.model_copy(update={"server_name": "replacement"})}
    )
    changed = changed.model_copy(
        update={"dataset_fingerprint": compute_dataset_fingerprint(changed)}
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        with matches.read_session():
            before = matches.get_match(dataset.match.match_id)
            assert before is not None
            future = executor.submit(matches.save_match, changed, replace=True)
            future.result(timeout=10)
            assert matches.get_match(dataset.match.match_id) == before
            assert len(matches.get_players(dataset.match.match_id)) == len(dataset.players)
            assert len(matches.get_rounds(dataset.match.match_id)) == len(dataset.rounds)
        after = matches.get_match(dataset.match.match_id)
        assert after is not None and after.server_name == "replacement"

    # Migration waits for the entire snapshot; shutdown never closes active SQL.
    started, finished = Event(), Event()

    def migrate() -> None:
        started.set()
        matches.initialize(force=True)
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with matches.read_session() as conn:
            future = executor.submit(migrate)
            assert started.wait(5)
            assert not finished.wait(0.1)
            assert conn.execute("SELECT value FROM connection_probe").fetchone() == (121,)
        future.result(timeout=10)
    manager = get_connection_manager(database)
    with matches.read_session() as conn:
        close_database_connections(database)
        with read_connection(database, "probe") as nested:
            assert nested is conn
        assert conn.execute("SELECT value FROM connection_probe").fetchone() == (121,)
    assert manager.statistics()["active"] == manager.statistics()["idle"] == 0
    with maintenance_read_connection(database) as readonly:
        assert readonly.execute("SELECT value FROM connection_probe").fetchone() == (121,)
    with write_connection(database) as writable:
        writable.execute("UPDATE connection_probe SET value=122")
    # A waiter must resolve the pool only after migration/shutdown retires it.
    coordinator = get_write_coordinator(database)
    started = Event()
    original_schema_read = coordinator.schema_read

    @contextmanager
    def observed_schema_read() -> Iterator[None]:
        started.set()
        with original_schema_read():
            yield

    def waiting_reader() -> None:
        with read_connection(database, "probe") as conn:
            assert conn.execute("SELECT value FROM connection_probe").fetchone() == (122,)

    with (
        patch.object(coordinator, "schema_read", observed_schema_read),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        with coordinator.serialized(), coordinator.schema_change():
            future = executor.submit(waiting_reader)
            assert started.wait(5)
            close_database_connections(database)
        future.result(timeout=10)
    close_database_connections()
    print("concurrent snapshots, distinct leases, serialized writes, migration and shutdown: OK")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
