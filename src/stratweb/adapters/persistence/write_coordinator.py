"""Process-wide serialization for DuckDB writers sharing one database file."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock
from weakref import WeakValueDictionary


class DuckDBWriteCoordinator:
    """Serialize nested write sections for one resolved DuckDB path."""

    def __init__(self) -> None:
        self._write_lock = RLock()

    @contextmanager
    def serialized(self) -> Iterator[None]:
        with self._write_lock:
            yield


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
