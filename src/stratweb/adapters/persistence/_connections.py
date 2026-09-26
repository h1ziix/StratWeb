"""Managed, exclusively leased DuckDB connections and thread-local read sessions."""

from __future__ import annotations

import atexit
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, local

import duckdb

from stratweb.exceptions import PersistenceError

from .write_coordinator import get_write_coordinator

_READ_SESSIONS = local()


def _current_session(database_path: Path) -> duckdb.DuckDBPyConnection | None:
    sessions: dict[Path, duckdb.DuckDBPyConnection] = getattr(_READ_SESSIONS, "connections", {})
    return sessions.get(database_path)


class DuckDBConnectionManager:
    """Keep up to four idle handles, exclusively leased to one thread at a time.

    Active demand is uncapped: callers holding writer/schema locks must never wait
    for a slot held by a caller waiting for those locks. Close drains idle resources
    immediately and active handles on return. Materialize results inside the lease.
    """

    def __init__(self, database_path: Path, *, max_idle: int = 4) -> None:
        if max_idle < 0:
            raise ValueError("max_idle must be nonnegative")
        self.database_path = database_path.expanduser().resolve()
        self._max_idle = max_idle
        self._lock = Lock()
        self._idle: list[duckdb.DuckDBPyConnection] = []
        self._closed = False
        self._active = 0
        self._opened = 0
        self._reused = 0

    @property
    def in_read_session(self) -> bool:
        return _current_session(self.database_path) is not None

    def statistics(self) -> dict[str, int]:
        with self._lock:
            return {
                "opened": self._opened,
                "reused": self._reused,
                "active": self._active,
                "idle": len(self._idle),
            }

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._lock:
            if self._closed:
                raise PersistenceError("DuckDB connection manager is closed.")
            if self._idle:
                connection = self._idle.pop()
                self._reused += 1
            else:
                connection = duckdb.connect(str(self.database_path), read_only=False)
                self._opened += 1
            self._active += 1
        reusable = True
        try:
            yield connection
        except BaseException:
            reusable = False
            raise
        finally:
            # Roll back unfinished transactions, including errors caught by callers.
            # After autocommit/explicit commit, no-active-transaction is expected.
            try:
                connection.execute("ROLLBACK")
            except duckdb.TransactionException as exc:
                if "no transaction is active" not in str(exc).lower():
                    reusable = False
            except duckdb.Error:
                reusable = False
            with self._lock:
                self._active -= 1
                if reusable and not self._closed and len(self._idle) < self._max_idle:
                    self._idle.append(connection)
                else:
                    connection.close()

    @contextmanager
    def read_session(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Reuse one connection and MVCC snapshot for nested reads in this thread.

        Writes and migration misses are rejected before acquiring the writer to
        prevent schema-reader -> writer lock inversion against migration.
        """
        existing = _current_session(self.database_path)
        if existing is not None:
            yield existing
            return
        with get_write_coordinator(self.database_path).schema_read(), self.connection() as conn:
            conn.execute("BEGIN TRANSACTION")
            if not hasattr(_READ_SESSIONS, "connections"):
                _READ_SESSIONS.connections = {}
            _READ_SESSIONS.connections[self.database_path] = conn
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except duckdb.Error:
                    # The lease is discarded; preserve the original failure.
                    pass
                raise
            finally:
                del _READ_SESSIONS.connections[self.database_path]

    def close(self) -> None:
        with self._lock:
            self._closed = True
            idle, self._idle = self._idle, []
        for connection in idle:
            connection.close()


_REGISTRY_LOCK = Lock()
_MANAGERS: dict[Path, DuckDBConnectionManager] = {}


def get_connection_manager(database_path: str | Path) -> DuckDBConnectionManager:
    key = Path(database_path).expanduser().resolve()
    with _REGISTRY_LOCK:
        manager = _MANAGERS.get(key)
        if manager is None:
            manager = DuckDBConnectionManager(key)
            _MANAGERS[key] = manager
        return manager


def close_database_connections(database_path: str | Path | None = None) -> None:
    """Close pools on shutdown or before replacing a database file."""
    with _REGISTRY_LOCK:
        if database_path is None:
            managers = tuple(_MANAGERS.values())
            _MANAGERS.clear()
        else:
            manager = _MANAGERS.pop(Path(database_path).expanduser().resolve(), None)
            managers = (manager,) if manager is not None else ()
    for manager in managers:
        manager.close()


@contextmanager
def read_session(database_path: str | Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Schema must be initialized before entering the session."""
    # Resolve the manager after the gate: a migration may retire an old pool
    # while this reader is waiting for schema access.
    with get_write_coordinator(database_path).schema_read():
        with get_connection_manager(database_path).read_session() as connection:
            yield connection


@contextmanager
def read_connection(database_path: Path, subsystem: str) -> Iterator[duckdb.DuckDBPyConnection]:
    try:
        existing = _current_session(database_path.expanduser().resolve())
        if existing is not None:
            yield existing
        else:
            with get_write_coordinator(database_path).schema_read():
                with get_connection_manager(database_path).connection() as conn:
                    yield conn
    except duckdb.Error as exc:
        raise PersistenceError(f"Could not read {subsystem} data.") from exc


@contextmanager
def write_connection(database_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    if _current_session(database_path.expanduser().resolve()) is not None:
        raise PersistenceError("Cannot write inside a DuckDB read session.")
    with get_write_coordinator(database_path).serialized():
        with get_connection_manager(database_path).connection() as connection:
            yield connection


@contextmanager
def maintenance_read_connection(database_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Keep offline audits truly read-only without mixing DuckDB configurations.

    Drain pooled readers under the schema gate and exclude writers until the
    temporary read-only handle is closed. This scope intentionally is not pooled.
    """
    coordinator = get_write_coordinator(database_path)
    with coordinator.serialized(), coordinator.schema_change():
        close_database_connections(database_path)
        with duckdb.connect(str(database_path), read_only=True) as connection:
            yield connection


atexit.register(close_database_connections)
