"""Durable contracts for one multi-demo training-pool upload."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from stratweb.application.import_job_models import ImportJobRecord, ImportJobStage


class ImportBatchItemDisposition(StrEnum):
    QUEUED = "queued"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class ImportBatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: UUID
    display_name: str = Field(min_length=1, max_length=100)
    opponent_profile_id: UUID
    created_at: AwareDatetime


class ImportBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: UUID
    item_index: int = Field(ge=0)
    original_name: str = Field(min_length=1, max_length=255)
    disposition: ImportBatchItemDisposition
    job_id: UUID | None = None
    existing_match_id: UUID | None = None
    error_code: str | None = Field(default=None, max_length=100)
    message: str = Field(min_length=1, max_length=400)
    created_at: AwareDatetime


class ImportBatchItemView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item: ImportBatchItem
    job: ImportJobRecord | None = None

    @property
    def terminal(self) -> bool:
        if self.item.disposition is not ImportBatchItemDisposition.QUEUED:
            return True
        return self.job is None or self.job.stage.terminal


class ImportBatchView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch: ImportBatchRecord
    items: tuple[ImportBatchItemView, ...]
    total_count: int = Field(ge=0)
    queued_count: int = Field(ge=0)
    complete_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    progress_percent: int = Field(ge=0, le=100)
    terminal: bool

    @classmethod
    def compose(
        cls,
        batch: ImportBatchRecord,
        items: tuple[ImportBatchItemView, ...],
    ) -> ImportBatchView:
        queued = tuple(
            item for item in items if item.item.disposition is ImportBatchItemDisposition.QUEUED
        )
        complete = sum(
            item.job is not None and item.job.stage is ImportJobStage.COMPLETE for item in queued
        )
        failed = sum(
            item.job is None or item.job.stage in {ImportJobStage.FAILED, ImportJobStage.CANCELLED}
            for item in queued
        )
        duplicates = sum(
            item.item.disposition is ImportBatchItemDisposition.DUPLICATE for item in items
        )
        rejected = sum(
            item.item.disposition is ImportBatchItemDisposition.REJECTED for item in items
        )
        progress_units = sum(
            100 if item.job is None or item.job.stage.terminal else item.job.progress_percent
            for item in queued
        ) + 100 * (duplicates + rejected)
        total = len(items)
        return cls(
            batch=batch,
            items=items,
            total_count=total,
            queued_count=len(queued),
            complete_count=complete,
            failed_count=failed,
            duplicate_count=duplicates,
            rejected_count=rejected,
            progress_percent=round(progress_units / total) if total else 100,
            terminal=all(item.terminal for item in items),
        )


__all__ = [
    "ImportBatchItem",
    "ImportBatchItemDisposition",
    "ImportBatchItemView",
    "ImportBatchRecord",
    "ImportBatchView",
]
