from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBImportJobRepository
from stratweb.application.import_job_models import ImportJobRecord, ImportJobStage
from stratweb.application.import_jobs import LocalImportJobManager
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
