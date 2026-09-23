from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from stratweb.adapters.persistence import DuckDBImportBatchRepository
from stratweb.application.import_batch_models import (
    ImportBatchItem,
    ImportBatchItemDisposition,
    ImportBatchItemView,
    ImportBatchRecord,
    ImportBatchStatus,
    ImportBatchView,
)
from stratweb.application.import_job_models import ImportJobRecord, ImportJobStage
from stratweb.exceptions import PersistenceError


def test_batch_and_items_are_registered_atomically(tmp_path: Path) -> None:
    repository = DuckDBImportBatchRepository(tmp_path / "batch.duckdb")
    now = datetime.now(UTC)
    batch = ImportBatchRecord(
        batch_id=uuid4(),
        display_name="Atomic batch",
        opponent_profile_id=uuid4(),
        created_at=now,
    )
    first = ImportBatchItem(
        batch_id=batch.batch_id,
        item_index=0,
        original_name="first.dem",
        disposition=ImportBatchItemDisposition.REJECTED,
        error_code="fixture",
        message="fixture",
        created_at=now,
    )
    conflicting = first.model_copy(update={"original_name": "second.dem"})

    with pytest.raises(PersistenceError):
        repository.create_with_items(batch, (first, conflicting))

    assert repository.get(batch.batch_id) is None
    assert repository.list_items(batch.batch_id) == ()


def test_batch_summary_reports_partial_outcomes_separately() -> None:
    now = datetime.now(UTC)
    batch = ImportBatchRecord(
        batch_id=uuid4(),
        display_name="Partial batch",
        opponent_profile_id=uuid4(),
        created_at=now,
    )

    def job(stage: ImportJobStage) -> ImportJobRecord:
        return ImportJobRecord.create(
            job_id=uuid4(),
            original_name=f"{stage.value}.dem",
            internal_name=f"{uuid4()}.dem",
            now=now,
        ).model_copy(
            update={
                "stage": stage,
                "message": stage.value,
                "recoverable": stage in {ImportJobStage.FAILED, ImportJobStage.CANCELLED},
            }
        )

    jobs = (
        job(ImportJobStage.COMPLETE),
        job(ImportJobStage.FAILED),
        job(ImportJobStage.CANCELLED),
    )
    items = tuple(
        ImportBatchItemView(
            item=ImportBatchItem(
                batch_id=batch.batch_id,
                item_index=index,
                original_name=current.original_name,
                disposition=ImportBatchItemDisposition.QUEUED,
                job_id=current.job_id,
                message="queued",
                created_at=now,
            ),
            job=current,
        )
        for index, current in enumerate(jobs)
    ) + (
        ImportBatchItemView(
            item=ImportBatchItem(
                batch_id=batch.batch_id,
                item_index=3,
                original_name="duplicate.dem",
                disposition=ImportBatchItemDisposition.DUPLICATE,
                message="duplicate",
                created_at=now,
            )
        ),
    )

    view = ImportBatchView.compose(batch, items)

    assert view.status is ImportBatchStatus.PARTIAL
    assert view.succeeded_count == 1
    assert view.failed_count == 1
    assert view.skipped_count == 1
    assert view.cancelled_count == 1
    assert view.terminal is True
