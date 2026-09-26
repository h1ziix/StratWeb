from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from threading import Event
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBTeamNameRepository
from stratweb.adapters.persistence._connections import (
    DuckDBConnectionManager,
    close_database_connections,
    get_connection_manager,
    read_connection,
    write_connection,
)
from stratweb.application.import_jobs import LocalImportJobManager
from stratweb.application.persistence_models import MatchQueryFilters
from stratweb.exceptions import PersistenceError
from stratweb.main import create_app


def test_repository_reads_reuse_one_pool_and_nested_snapshot(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database = tmp_path / "reuse.duckdb"
    dataset = canonical_dataset_factory()
    first = DuckDBMatchRepository(database)
    first.save_match(dataset)
    second = DuckDBMatchRepository(database)
    manager = get_connection_manager(database)
    opened = manager.statistics()["opened"]
    for _ in range(3):
        assert second.get_match(dataset.match.match_id) is not None
    with first.read_session() as conn, second.read_session() as nested:
        assert nested is conn
        assert {p.player_id for p in second.get_players(dataset.match.match_id)} == {
            p.player_id for p in dataset.players
        }
        assert DuckDBTeamNameRepository(database).list_for_match(dataset.match.match_id) == ()
        assert manager.statistics()["active"] == 1
        with pytest.raises(PersistenceError):
            first.delete_match(dataset.match.match_id)
        with pytest.raises(PersistenceError):
            first.initialize(force=True)
    assert manager.statistics()["opened"] == opened


def test_unfinished_and_failed_transactions_do_not_escape_a_lease(tmp_path: Path) -> None:
    database = tmp_path / "rollback.duckdb"
    DuckDBMatchRepository(database).initialize()
    with write_connection(database) as conn:
        conn.execute("CREATE TABLE rollback_probe (value INTEGER)")
        conn.execute("BEGIN TRANSACTION")
        conn.execute("INSERT INTO rollback_probe VALUES (1)")
    with read_connection(database, "probe") as conn:
        assert conn.execute("SELECT count(*) FROM rollback_probe").fetchone() == (0,)
    with pytest.raises(RuntimeError), write_connection(database) as conn:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("INSERT INTO rollback_probe VALUES (2)")
        raise RuntimeError("before commit")
    with write_connection(database) as conn:
        conn.execute("INSERT INTO rollback_probe VALUES (3)")
    with read_connection(database, "probe") as conn:
        assert conn.execute("SELECT * FROM rollback_probe").fetchall() == [(3,)]


def test_session_failure_cleans_thread_local_state(tmp_path: Path) -> None:
    database = tmp_path / "error.duckdb"
    repository = DuckDBMatchRepository(database)
    with pytest.raises(PersistenceError), repository.read_session():
        with read_connection(database, "missing") as conn:
            conn.execute("SELECT * FROM absent_table")
    manager = get_connection_manager(database)
    assert not manager.in_read_session
    assert manager.statistics()["active"] == manager.statistics()["idle"] == 0
    assert repository.count_matches(MatchQueryFilters()) == 0


def test_idle_limit_close_and_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "limit.duckdb"
    manager = DuckDBConnectionManager(database, max_idle=1)
    actual_connect = duckdb.connect
    configurations = []

    def connect(*args: Any, **kwargs: Any) -> Any:
        configurations.append(kwargs)
        return actual_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", connect)
    with manager.connection() as first, manager.connection() as second:
        assert first is not second
    assert manager.statistics()["idle"] == 1
    assert configurations == [{"read_only": False}, {"read_only": False}]
    manager.close()
    manager.close()
    assert manager.statistics()["idle"] == 0
    with pytest.raises(PersistenceError), manager.connection():
        pass
    with pytest.raises(ValueError):
        DuckDBConnectionManager(database, max_idle=-1)
    database.unlink()


def test_application_shutdown_releases_database_file(tmp_path: Path) -> None:
    database = tmp_path / "shutdown.duckdb"
    with TestClient(create_app(database)) as client:
        assert client.get("/ui").status_code == 200
        manager = get_connection_manager(database)
        assert manager.statistics()["idle"] == 1
    assert manager.statistics()["idle"] == manager.statistics()["active"] == 0
    database.unlink()
    close_database_connections(database)


def test_late_worker_completion_releases_reopened_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "late.duckdb"
    upload = tmp_path / "uploads"
    upload.mkdir()
    demo = upload / "late.dem"
    demo.write_bytes(b"PBDEMS2fixture")
    jobs = LocalImportJobManager(database, shutdown_timeout_seconds=0.01)
    entered, release = Event(), Event()
    late_pools = []

    def run(job_id: Any, _path: Any, _name: Any, _event: Event) -> None:
        entered.set()
        assert release.wait(5)
        jobs._mark_cancelled(job_id)
        late_pools.append(get_connection_manager(database))

    monkeypatch.setattr(jobs, "_run", run)
    job = jobs.submit(demo, "late.dem")
    assert entered.wait(5)
    future = jobs._futures[job.job_id]
    try:
        jobs.shutdown()
        close_database_connections(database)
    finally:
        release.set()
    future.result(timeout=5)
    assert len(late_pools) == 1
    assert late_pools[0].statistics()["active"] == late_pools[0].statistics()["idle"] == 0
    database.unlink()


def test_concurrent_leases_snapshots_writes_migration_and_shutdown(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("connection_lifecycle_probe.py")),
            str(tmp_path / "concurrent.duckdb"),
        ],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "shutdown: OK" in result.stdout
