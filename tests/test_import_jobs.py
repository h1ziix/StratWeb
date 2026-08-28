from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import duckdb
import pytest
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBImportJobRepository, DuckDBMatchRepository
from stratweb.adapters.persistence.migrations import MIGRATIONS
from stratweb.application.import_job_models import ImportJobRecord, ImportJobStage
from stratweb.application.import_jobs import LocalImportJobManager
from stratweb.application.import_worker import ParserWorkerRunner, _artifact_matches
from stratweb.economy.models import EconomyExtraction
from stratweb.exceptions import (
    ImportDiskSpaceError,
    ImportDuplicateError,
    ImportQueueFullError,
    ImportWorkerTimeoutError,
)
from stratweb.main import create_app


def _queued_record(internal_name: str = "retained.dem") -> ImportJobRecord:
    now = datetime.now(UTC)
    return ImportJobRecord.create(
        job_id=uuid4(),
        original_name="opponent.dem",
        internal_name=internal_name,
        now=now,
    )


def test_import_job_repository_round_trip_and_unfinished_query(tmp_path: Path) -> None:
    repository = DuckDBImportJobRepository(tmp_path / "jobs.duckdb")
    record = _queued_record()

    repository.create(record)

    assert repository.get(record.job_id) == record
    assert repository.list_unfinished() == (record,)

    complete = record.model_copy(
        update={
            "stage": ImportJobStage.COMPLETE,
            "message": "Match is ready",
            "progress_percent": 100,
            "updated_at": datetime.now(UTC),
        }
    )
    repository.update(complete)

    assert repository.get(record.job_id) == complete
    assert repository.list_unfinished() == ()


def test_worker_v2_migration_does_not_relabel_legacy_job(tmp_path: Path) -> None:
    database = tmp_path / "legacy-jobs.duckdb"
    DuckDBMatchRepository(database, migrations=MIGRATIONS[:23]).initialize()
    record = _queued_record()
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO import_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record.job_id,
                record.stage.value,
                record.original_name,
                record.internal_name,
                None,
                record.message,
                None,
                1,
                False,
                0,
                record.created_at.replace(tzinfo=None),
                record.updated_at.replace(tzinfo=None),
            ],
        )

    repository = DuckDBImportJobRepository(database)
    repository.initialize()
    migrated = repository.get(record.job_id)

    assert migrated is not None
    assert migrated.worker_version is None


def test_manager_marks_interrupted_job_retryable_when_demo_is_retained(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    demo_path = upload_directory / "retained.dem"
    demo_path.write_bytes(b"PBDEMS2fixture")
    repository = DuckDBImportJobRepository(database)
    record = _queued_record(demo_path.name)
    repository.create(record)

    recovered = LocalImportJobManager(database).get(record.job_id)

    assert recovered is not None
    assert recovered.stage is ImportJobStage.FAILED
    assert recovered.error_code == "import_interrupted"
    assert recovered.recoverable is True
    assert recovered.progress_percent == 0


def test_recovered_job_page_exposes_retry_and_retry_increments_attempt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    demo_path = upload_directory / "retained.dem"
    demo_path.write_bytes(b"PBDEMS2fixture")
    repository = DuckDBImportJobRepository(database)
    record = _queued_record(demo_path.name)
    repository.create(record)

    with TestClient(create_app(database)) as client:
        page = client.get(f"/ui/import-jobs/{record.job_id}")
        library = client.get("/ui")
        retry = client.post(
            f"/api/import-jobs/{record.job_id}/retry",
            headers={"Accept": "application/json"},
        )

    assert page.status_code == 200
    assert "import_interrupted" in page.text
    assert "Повторить импорт" in page.text
    assert library.status_code == 200
    assert "Последние загрузки" in library.text
    assert "opponent.dem" not in library.text
    assert retry.status_code == 202
    assert retry.json()["attempt_count"] == 2


def test_retry_rejects_completed_or_missing_job(tmp_path: Path) -> None:
    database = tmp_path / "jobs.duckdb"
    repository = DuckDBImportJobRepository(database)
    record = _queued_record()
    repository.create(
        record.model_copy(
            update={
                "stage": ImportJobStage.COMPLETE,
                "message": "Match is ready",
                "progress_percent": 100,
            }
        )
    )

    with TestClient(create_app(database)) as client:
        complete = client.post(
            f"/api/import-jobs/{record.job_id}/retry",
            headers={"Accept": "application/json"},
        )
        missing = client.post(
            f"/api/import-jobs/{uuid4()}/retry",
            headers={"Accept": "application/json"},
        )

    assert complete.status_code == 409
    assert missing.status_code == 404


def test_worker_v2_rejects_duplicate_hash_before_second_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    demo = upload_directory / "first.dem"
    payload = b"PBDEMS2same-demo"
    demo.write_bytes(payload)
    digest = sha256(payload).hexdigest()
    manager = LocalImportJobManager(database, minimum_free_disk_bytes=0)
    started = Event()
    release = Event()

    def blocked(*_args: object) -> None:
        started.set()
        release.wait(5)

    monkeypatch.setattr(manager, "_run", blocked)
    manager.submit(demo, "first.dem", demo_sha256=digest, file_size_bytes=len(payload))
    assert started.wait(2)

    with pytest.raises(ImportDuplicateError):
        manager.submit(demo, "copy.dem", demo_sha256=digest, file_size_bytes=len(payload))
    release.set()


def test_worker_v2_bounds_queue_and_can_cancel_waiting_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    paths = []
    for index in range(3):
        path = upload_directory / f"{index}.dem"
        path.write_bytes(b"PBDEMS2" + bytes([index]))
        paths.append(path)
    manager = LocalImportJobManager(database, max_queue_size=1, minimum_free_disk_bytes=0)
    started = Event()
    release = Event()

    def blocked(*_args: object) -> None:
        started.set()
        release.wait(5)

    monkeypatch.setattr(manager, "_run", blocked)
    first = manager.submit(paths[0], "0.dem")
    assert started.wait(2)
    waiting = manager.submit(paths[1], "1.dem")

    with pytest.raises(ImportQueueFullError):
        manager.submit(paths[2], "2.dem")

    cancelled = manager.cancel(waiting.job_id)
    assert cancelled.stage is ImportJobStage.CANCELLED
    assert cancelled.recoverable is True
    assert manager.get(first.job_id) is not None
    release.set()


def test_worker_v2_reuses_valid_atomic_artifact_without_process(tmp_path: Path) -> None:
    digest = "a" * 64
    artifact_directory = tmp_path / "artifacts"
    artifact_directory.mkdir()
    extraction = EconomyExtraction(
        parser_name="demoparser2",
        parser_version="0.41.4",
        source_demo_sha256=digest,
        requested_ticks=(10, 20),
        samples=(),
        requested_fields=(),
        source_columns=(),
    )
    (artifact_directory / "economy.json").write_text(extraction.model_dump_json(), encoding="utf-8")
    runner = ParserWorkerRunner(
        artifact_directory,
        timeout_seconds=10,
        memory_limit_bytes=1,
        minimum_free_disk_bytes=0,
        cancel_grace_seconds=0.1,
        cancel_event=Event(),
    )

    assert runner.economy(tmp_path / "missing.dem", (10, 20), digest) == extraction


def test_worker_v2_rejects_cached_canonical_artifact_from_old_normalization_rule(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("stale-canonical-worker")
    current_sha = dataset.normalization_metadata.source_demo_sha256
    stale = dataset.model_copy(
        update={
            "normalization_metadata": dataset.normalization_metadata.model_copy(
                update={"normalization_rule_version": "1.1.0"}
            )
        }
    )

    assert _artifact_matches(dataset, current_sha, ()) is True
    assert _artifact_matches(stale, current_sha, ()) is False


def test_worker_v2_checks_disk_capacity_before_spawning(tmp_path: Path) -> None:
    runner = ParserWorkerRunner(
        tmp_path / "artifacts",
        timeout_seconds=10,
        memory_limit_bytes=1024,
        minimum_free_disk_bytes=2**63,
        cancel_grace_seconds=0.1,
        cancel_event=Event(),
    )

    with pytest.raises(ImportDiskSpaceError):
        runner.canonicalize(tmp_path / "missing.dem", "a" * 64)


def test_worker_v2_terminates_timed_out_parser_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NeverFinishes:
        pid = 999_999
        returncode: int | None = None
        terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is not None
            assert self.returncode is not None
            return self.returncode

    process = NeverFinishes()
    monkeypatch.setattr(
        "stratweb.application.import_worker.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        "stratweb.application.import_worker._process_memory_bytes", lambda _pid: None
    )
    runner = ParserWorkerRunner(
        tmp_path / "artifacts",
        timeout_seconds=0,
        memory_limit_bytes=1024,
        minimum_free_disk_bytes=0,
        cancel_grace_seconds=0.1,
        cancel_event=Event(),
    )

    with pytest.raises(ImportWorkerTimeoutError):
        runner.canonicalize(tmp_path / "missing.dem", "a" * 64)
    assert process.terminated is True
