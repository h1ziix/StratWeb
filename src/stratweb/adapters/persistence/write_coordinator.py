"""Process-wide serialization for DuckDB writers sharing one database file."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Condition, Lock, RLock, get_ident, local
from time import perf_counter
from weakref import WeakValueDictionary

from stratweb.exceptions import PersistenceError


class DuckDBWriteCoordinator:
    """Serialize nested write sections for one resolved DuckDB path.

    Lock order: this reentrant lock precedes the schema initialization/cache lock.
    Keep it held for an entire migration sequence, not just individual connections.
    """

    def __init__(self) -> None:
        self._write_lock = RLock()
        self._schema_condition = Condition(RLock())
        self._schema_owner: int | None = None
        self._schema_readers = 0
        self._timing = local()

    @contextmanager
    def serialized(self, *, timeout: float = -1) -> Iterator[None]:
        if getattr(self._timing, "read_depth", 0) and not getattr(self._timing, "depth", 0):
            raise PersistenceError("Cannot acquire the writer inside a database read scope.")
        started = perf_counter()
        if not self._write_lock.acquire(timeout=timeout):
            raise TimeoutError("Timed out waiting for the database writer.")
        acquired = perf_counter()
        depth = getattr(self._timing, "depth", 0)
        self._timing.depth = depth + 1
        try:
            yield
        finally:
            self._timing.depth = depth
            held = perf_counter() - acquired
            self._write_lock.release()
            if depth == 0:
                logging.getLogger(__name__).debug(
                    "database_writer wait_seconds=%.6f hold_seconds=%.6f",
                    acquired - started,
                    held,
                )

    @contextmanager
    def schema_read(self) -> Iterator[None]:
        """Concurrent query connections, excluded only by schema migration."""
        with self._schema_condition:
            while self._schema_owner not in (None, get_ident()):
                self._schema_condition.wait()
            self._schema_readers += 1
        depth = getattr(self._timing, "read_depth", 0)
        self._timing.read_depth = depth + 1
        try:
            yield
        finally:
            self._timing.read_depth = depth
            with self._schema_condition:
                self._schema_readers -= 1
                self._schema_condition.notify_all()

    @contextmanager
    def schema_change(self) -> Iterator[None]:
        """Caller holds the writer; exclude queries for the whole migration sequence."""
        with self._schema_condition:
            while self._schema_owner is not None or self._schema_readers:
                self._schema_condition.wait()
            self._schema_owner = get_ident()
        try:
            yield
        finally:
            with self._schema_condition:
                self._schema_owner = None
                self._schema_condition.notify_all()


_REGISTRY_LOCK = Lock()
_COORDINATORS: WeakValueDictionary[str, DuckDBWriteCoordinator] = WeakValueDictionary()


def get_write_coordinator(database_path: str | Path) -> DuckDBWriteCoordinator:
    """Return the shared in-process coordinator for a database path."""

    key = str(Path(database_path).expanduser().resolve()).casefold()
    with _REGISTRY_LOCK:
        coordinator = _COORDINATORS.get(key)
        if coordinator is None:
            coordinator = DuckDBWriteCoordinator()
            _COORDINATORS[key] = coordinator
        return coordinator


__all__ = ["DuckDBWriteCoordinator", "get_write_coordinator"]
