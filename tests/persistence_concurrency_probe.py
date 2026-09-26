"""Killable, event-controlled reproduction of the initialization/import lock race."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread, current_thread
from time import monotonic

import duckdb

from stratweb.adapters.persistence import DuckDBMatchRepository
from stratweb.adapters.persistence.migrations import MIGRATIONS
from stratweb.adapters.persistence.write_coordinator import get_write_coordinator
from stratweb.application.import_jobs import LocalImportJobManager
from stratweb.application.persistence import ImportCanonicalMatchService, load_canonical_dataset
from stratweb.application.persistence_models import ImportStatus, MatchQueryFilters


def main() -> None:
    database, dataset_path = Path(sys.argv[1]), Path(sys.argv[2])
    legacy = bool(int(sys.argv[3]))
    dataset = load_canonical_dataset(dataset_path)
    if legacy:
        # Includes the spatial backfill/index sequence; preserve real match/event rows.
        old = DuckDBMatchRepository(database, migrations=MIGRATIONS[:14])
        old.save_match(dataset)
        expected_counts = old.get_table_counts(dataset.match.match_id)
    else:
        expected_counts = None

    coordinator = get_write_coordinator(database)
    original_serialized = coordinator.serialized
    writer_held, initializer_waiting, reader_waiting = Event(), Event(), Event()
    errors: list[BaseException] = []
    results: list[ImportStatus] = []
    reads: list[int] = []
    manager = LocalImportJobManager(database)

    @contextmanager
    def observed_serialized(*, timeout: float = -1) -> Iterator[None]:
        # Signal immediately before attempting the writer lock. In the buggy code
        # the initializer already owns _INITIALIZATION_LOCK at this point.
        if current_thread().name == "initializer":
            initializer_waiting.set()
        if current_thread().name == "reader":
            reader_waiting.set()
        with original_serialized(timeout=timeout):
            yield

    coordinator.serialized = observed_serialized  # type: ignore[method-assign]

    def importer() -> None:
        with coordinator.serialized():
            writer_held.set()
            assert initializer_waiting.wait(5), "Initializer never attempted writer lock"
            assert reader_waiting.wait(5), "Reader never attempted writer lock"
            with manager._database_write():
                result = ImportCanonicalMatchService(
                    DuckDBMatchRepository(database)
                ).import_dataset(dataset)
                results.append(result.status)

    def initialize() -> None:
        DuckDBMatchRepository(database).initialize()

    def read() -> None:
        # An uninitialized/legacy database still waits for complete migrations.
        DuckDBMatchRepository(database).initialize()
        reads.append(DuckDBMatchRepository(database).count_matches(MatchQueryFilters()))

    def guarded(action: Callable[[], None]) -> None:
        try:
            action()
        except BaseException as exc:
            errors.append(exc)

    writer = Thread(target=guarded, args=(importer,), name="importer", daemon=True)
    initializer = Thread(target=guarded, args=(initialize,), name="initializer", daemon=True)
    reader = Thread(target=guarded, args=(read,), name="reader", daemon=True)
    writer.start()
    assert writer_held.wait(5), "Importer never acquired writer lock"
    initializer.start()
    reader.start()
    deadline = monotonic() + 15
    for thread in (writer, initializer, reader):
        thread.join(max(0, deadline - monotonic()))
    assert not any(thread.is_alive() for thread in (writer, initializer, reader)), "Lock deadlock"
    assert not errors, repr(errors)
    assert results == [ImportStatus.ALREADY_EXISTS if legacy else ImportStatus.IMPORTED]
    assert reads == [1]
    repository = DuckDBMatchRepository(database)
    assert repository.initialize(force=True) == ()
    assert repository.get_match(dataset.match.match_id) is not None
    if expected_counts is not None:
        assert repository.get_table_counts(dataset.match.match_id) == expected_counts
    with duckdb.connect(str(database)) as connection:
        rows = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert rows == [(item.version, item.name, item.checksum) for item in MIGRATIONS]
    manager.shutdown()
    print("Concurrent initialization/import/read: OK")


if __name__ == "__main__":
    main()
