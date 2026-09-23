from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Event, Thread
from typing import Any
from uuid import uuid4

import duckdb
import pytest
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBImportJobRepository, DuckDBMatchRepository
from stratweb.adapters.persistence.migrations import MIGRATIONS
from stratweb.adapters.persistence.write_coordinator import get_write_coordinator
from stratweb.application.import_job_models import (
    ImportJobRecord,
    ImportJobStage,
    validate_stage_transition,
)
from stratweb.application.import_jobs import LocalImportJobManager, _safe_import_error_message
from stratweb.application.import_worker import ParserWorkerRunner, _artifact_matches
from stratweb.economy.models import EconomyExtraction
from stratweb.exceptions import (
    ImportDiskSpaceError,
    ImportDuplicateError,
    ImportJobNotRetryableError,
    ImportJobTransitionConflictError,
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


@pytest.mark.parametrize(
    ("current", "target"),
    (
        (ImportJobStage.QUEUED, ImportJobStage.CANONICALIZING),
        (ImportJobStage.CANONICALIZING, ImportJobStage.IMPORTING),
        (ImportJobStage.FEATURES, ImportJobStage.COMPLETE),
        (ImportJobStage.QUEUED, ImportJobStage.CANCEL_REQUESTED),
        (ImportJobStage.CANCEL_REQUESTED, ImportJobStage.CANCELLED),
        (ImportJobStage.FAILED, ImportJobStage.QUEUED),
        (ImportJobStage.CANCELLED, ImportJobStage.QUEUED),
    ),
)
def test_import_job_state_machine_accepts_declared_transitions(
    current: ImportJobStage, target: ImportJobStage
) -> None:
    validate_stage_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    (
        (ImportJobStage.QUEUED, ImportJobStage.COMPLETE),
        (ImportJobStage.CANONICALIZING, ImportJobStage.FEATURES),
        (ImportJobStage.COMPLETE, ImportJobStage.FAILED),
        (ImportJobStage.FAILED, ImportJobStage.COMPLETE),
        (ImportJobStage.CANCELLED, ImportJobStage.COMPLETE),
    ),
)
def test_import_job_state_machine_rejects_invalid_or_terminal_overwrite(
    current: ImportJobStage, target: ImportJobStage
) -> None:
    with pytest.raises(ValueError, match="Invalid import job transition"):
        validate_stage_transition(current, target)


@pytest.mark.parametrize("stage", tuple(ImportJobStage))
def test_import_job_state_machine_allows_idempotent_repeated_state(
    stage: ImportJobStage,
) -> None:
    validate_stage_transition(stage, stage)


def test_import_failure_message_does_not_expose_path_or_traceback() -> None:
    error = RuntimeError(
        "failed at C:\\Users\\analyst\\private\\match.dem\n"
        "Traceback (most recent call last): secret-token"
    )

    message = _safe_import_error_message(error)

    assert message == "Import failed during processing. The retained demo can be retried."
    assert "Users" not in message
    assert "Traceback" not in message
    assert "secret-token" not in message


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


def test_import_job_repository_rejects_stale_stage_update(tmp_path: Path) -> None:
    repository = DuckDBImportJobRepository(tmp_path / "jobs.duckdb")
    queued = _queued_record()
    repository.create(queued)
    canonicalizing = queued.model_copy(
        update={
            "stage": ImportJobStage.CANONICALIZING,
            "message": "Parsing completed demo",
            "updated_at": datetime.now(UTC),
        }
    )
    repository.update(canonicalizing, expected_stage=ImportJobStage.QUEUED)

    with pytest.raises(ImportJobTransitionConflictError):
        repository.update(
            queued.model_copy(
                update={
                    "stage": ImportJobStage.CANCEL_REQUESTED,
                    "message": "Cancellation requested",
                    "updated_at": datetime.now(UTC),
                }
            ),
            expected_stage=ImportJobStage.QUEUED,
        )

    assert repository.get(queued.job_id) == canonicalizing


def test_import_job_manager_rejects_pipeline_stage_jump(tmp_path: Path) -> None:
    database = tmp_path / "jobs.duckdb"
    repository = DuckDBImportJobRepository(database)
    queued = _queued_record()
    repository.create(queued)
    manager = LocalImportJobManager(database, repository=repository)

    with pytest.raises(ValueError, match="Invalid import job transition"):
        manager._update(queued.job_id, ImportJobStage.COMPLETE, "Match is ready")

    assert repository.get(queued.job_id) == queued
    manager.shutdown()


def test_cancel_does_not_overwrite_concurrent_terminal_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "jobs.duckdb"
    repository = DuckDBImportJobRepository(database)
    queued = _queued_record()
    repository.create(queued)
    manager = LocalImportJobManager(database, repository=repository)
    manager._started = True
    original_update = repository.update
    raced = False

    def update_with_race(
        record: ImportJobRecord,
        *,
        expected_stage: ImportJobStage | None = None,
    ) -> None:
        nonlocal raced
        if record.stage is ImportJobStage.CANCEL_REQUESTED and not raced:
            raced = True
            original_update(
                queued.model_copy(
                    update={
                        "stage": ImportJobStage.FAILED,
                        "message": "Concurrent failure",
                        "updated_at": datetime.now(UTC),
                    }
                ),
                expected_stage=ImportJobStage.QUEUED,
            )
        original_update(record, expected_stage=expected_stage)

    monkeypatch.setattr(repository, "update", update_with_race)

    with pytest.raises(ImportJobTransitionConflictError):
        manager.cancel(queued.job_id)

    current = repository.get(queued.job_id)
    assert current is not None
    assert current.stage is ImportJobStage.FAILED
    manager.shutdown()


def test_write_coordinator_serializes_independent_clients_for_same_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.duckdb"
    first = get_write_coordinator(database)
    second = get_write_coordinator(database)
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def hold_first_writer() -> None:
        with first.serialized():
            first_entered.set()
            assert release_first.wait(timeout=2)

    def enter_second_writer() -> None:
        assert first_entered.wait(timeout=2)
        with second.serialized():
            second_entered.set()

    first_thread = Thread(target=hold_first_writer)
    second_thread = Thread(target=enter_second_writer)
    first_thread.start()
    second_thread.start()
    assert first_entered.wait(timeout=2)
    assert not second_entered.wait(timeout=0.1)
    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert second_entered.is_set()


def test_import_job_repository_uses_shared_write_coordinator(tmp_path: Path) -> None:
    database = tmp_path / "jobs.duckdb"
    repository = DuckDBImportJobRepository(database)
    repository.initialize()
    coordinator = get_write_coordinator(database)
    created = Event()
    errors: list[BaseException] = []

    def create_job() -> None:
        try:
            repository.create(_queued_record())
        except BaseException as exc:
            errors.append(exc)
        finally:
            created.set()

    with coordinator.serialized():
        writer = Thread(target=create_job)
        writer.start()
        assert not created.wait(timeout=0.1)

    writer.join(timeout=2)
    assert not writer.is_alive()
    assert created.is_set()
    assert errors == []


def test_duplicate_demo_hash_reservation_is_atomic_across_repositories(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.duckdb"
    first = DuckDBImportJobRepository(database)
    second = DuckDBImportJobRepository(database)
    first.initialize()
    start = Barrier(3)
    created: list[ImportJobRecord] = []
    duplicates: list[ImportDuplicateError] = []

    def reserve(repository: DuckDBImportJobRepository) -> None:
        record = _queued_record().model_copy(update={"demo_sha256": "a" * 64})
        start.wait(timeout=2)
        try:
            repository.create_if_sha256_absent(record)
            created.append(record)
        except ImportDuplicateError as exc:
            duplicates.append(exc)

    threads = (Thread(target=reserve, args=(first,)), Thread(target=reserve, args=(second,)))
    for thread in threads:
        thread.start()
    start.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert len(created) == 1
    assert len(duplicates) == 1
    assert first.find_by_sha256("a" * 64) == created[0]


def test_import_job_managers_share_database_write_coordinator(tmp_path: Path) -> None:
    database = tmp_path / "jobs.duckdb"
    first = LocalImportJobManager(database)
    second = LocalImportJobManager(database)

    assert first._write_coordinator is second._write_coordinator

    first.shutdown()
    second.shutdown()


def test_manager_database_write_section_serializes_across_instances(tmp_path: Path) -> None:
    database = tmp_path / "jobs.duckdb"
    first = LocalImportJobManager(database)
    second = LocalImportJobManager(database)
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def hold_first() -> None:
        with first._database_write():
            first_entered.set()
            assert release_first.wait(timeout=2)

    def enter_second() -> None:
        assert first_entered.wait(timeout=2)
        with second._database_write():
            second_entered.set()

    threads = (Thread(target=hold_first), Thread(target=enter_second))
    for thread in threads:
        thread.start()
    assert first_entered.wait(timeout=2)
    assert not second_entered.wait(timeout=0.1)
    release_first.set()
    for thread in threads:
        thread.join(timeout=2)

    assert second_entered.is_set()
    first.shutdown()
    second.shutdown()


def test_completed_job_cleanup_removes_only_job_owned_runtime_files(tmp_path: Path) -> None:
    database = tmp_path / "jobs.duckdb"
    manager = LocalImportJobManager(database)
    job_id = uuid4()
    upload_directory = tmp_path / "uploads"
    artifact_root = tmp_path / "import_artifacts"
    owned_demo = upload_directory / "owned.dem"
    owned_artifact = artifact_root / str(job_id) / "canonical.json"
    other_demo = upload_directory / "other.dem"
    other_artifact = artifact_root / str(uuid4()) / "canonical.json"
    owned_artifact.parent.mkdir(parents=True)
    other_artifact.parent.mkdir(parents=True)
    upload_directory.mkdir(exist_ok=True)
    owned_demo.write_bytes(b"owned")
    other_demo.write_bytes(b"other")
    owned_artifact.write_text("owned", encoding="utf-8")
    other_artifact.write_text("other", encoding="utf-8")

    manager._cleanup_completed_job(job_id, owned_demo.name)

    assert not owned_demo.exists()
    assert not owned_artifact.parent.exists()
    assert other_demo.read_bytes() == b"other"
    assert other_artifact.read_text(encoding="utf-8") == "other"
    manager.shutdown()


def test_completed_job_cleanup_rejects_path_outside_upload_directory(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.duckdb"
    manager = LocalImportJobManager(database)
    outside = tmp_path / "outside.dem"
    outside.write_bytes(b"do-not-delete")

    with pytest.raises(ImportJobNotRetryableError, match="unsafe"):
        manager._cleanup_completed_job(uuid4(), "../outside.dem")

    assert outside.read_bytes() == b"do-not-delete"
    manager.shutdown()


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
    queued = _queued_record(demo_path.name)
    repository.create(queued)
    record = queued.model_copy(
        update={
            "stage": ImportJobStage.CANONICALIZING,
            "message": "Parsing completed demo",
            "updated_at": datetime.now(UTC),
        }
    )
    repository.update(record, expected_stage=ImportJobStage.QUEUED)

    recovered = LocalImportJobManager(database).get(record.job_id)

    assert recovered is not None
    assert recovered.stage is ImportJobStage.FAILED
    assert recovered.error_code == "import_interrupted"
    assert recovered.recoverable is True
    assert recovered.progress_percent == 0


def test_manager_resumes_queued_job_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    demo_path = upload_directory / "queued.dem"
    demo_path.write_bytes(b"PBDEMS2fixture")
    repository = DuckDBImportJobRepository(database)
    queued = _queued_record(demo_path.name)
    repository.create(queued)
    manager = LocalImportJobManager(database, repository=repository)
    scheduled: list[tuple[ImportJobRecord, Path]] = []
    monkeypatch.setattr(
        manager,
        "_schedule",
        lambda record, path: scheduled.append((record, path)),
    )

    recovered = manager.get(queued.job_id)

    assert recovered == queued
    assert scheduled == [(queued, demo_path)]
    manager.shutdown()


def test_manager_finishes_cancelling_job_as_cancelled_after_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    demo_path = upload_directory / "cancelling.dem"
    demo_path.write_bytes(b"PBDEMS2fixture")
    repository = DuckDBImportJobRepository(database)
    queued = _queued_record(demo_path.name)
    repository.create(queued)
    cancelling = queued.model_copy(
        update={
            "stage": ImportJobStage.CANCEL_REQUESTED,
            "message": "Cancellation requested",
            "cancel_requested_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    repository.update(cancelling, expected_stage=ImportJobStage.QUEUED)

    manager = LocalImportJobManager(database, repository=repository)
    recovered = manager.get(queued.job_id)

    assert recovered is not None
    assert recovered.stage is ImportJobStage.CANCELLED
    assert recovered.error_code == "import_worker_cancelled"
    assert recovered.recoverable is True
    manager.shutdown()


def test_recovered_job_page_exposes_retry_and_retry_increments_attempt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    demo_path = upload_directory / "retained.dem"
    demo_path.write_bytes(b"PBDEMS2fixture")
    repository = DuckDBImportJobRepository(database)
    queued = _queued_record(demo_path.name)
    repository.create(queued)
    record = queued.model_copy(
        update={
            "stage": ImportJobStage.CANONICALIZING,
            "message": "Parsing completed demo",
            "updated_at": datetime.now(UTC),
        }
    )
    repository.update(record, expected_stage=ImportJobStage.QUEUED)

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
