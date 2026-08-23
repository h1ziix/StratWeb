"""Persisted contracts for the local completed-demo import queue."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ImportJobStage(StrEnum):
    QUEUED = "queued"
    CANONICALIZING = "canonicalizing"
    IMPORTING = "importing"
    ECONOMY = "economy"
    ANALYTICS = "analytics"
    TEMPORAL = "temporal"
    SPATIAL = "spatial"
    ZONES = "zones"
    FEATURES = "features"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETE = "complete"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {
            ImportJobStage.COMPLETE,
            ImportJobStage.FAILED,
            ImportJobStage.CANCELLED,
        }


_STAGE_PROGRESS = {
    ImportJobStage.QUEUED: 0,
    ImportJobStage.CANONICALIZING: 10,
    ImportJobStage.IMPORTING: 45,
    ImportJobStage.ECONOMY: 55,
    ImportJobStage.ANALYTICS: 65,
    ImportJobStage.TEMPORAL: 77,
    ImportJobStage.SPATIAL: 87,
    ImportJobStage.ZONES: 93,
    ImportJobStage.FEATURES: 97,
    ImportJobStage.CANCEL_REQUESTED: 0,
    ImportJobStage.CANCELLED: 0,
    ImportJobStage.COMPLETE: 100,
    ImportJobStage.FAILED: 0,
}


class ImportJobRecord(BaseModel):
    """One durable import attempt and its latest pipeline checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    stage: ImportJobStage
    original_name: str = Field(min_length=1, max_length=255)
    internal_name: str = Field(min_length=1, max_length=255)
    match_id: UUID | None = None
    message: str = Field(min_length=1, max_length=400)
    error_code: str | None = None
    attempt_count: int = Field(default=1, ge=1)
    recoverable: bool = False
    progress_percent: int = Field(default=0, ge=0, le=100)
    demo_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    file_size_bytes: int | None = Field(default=None, ge=0)
    last_completed_stage: ImportJobStage | None = None
    worker_version: str | None = Field(default="2.0", min_length=1, max_length=32)
    worker_pid: int | None = Field(default=None, ge=1)
    peak_worker_memory_bytes: int | None = Field(default=None, ge=0)
    cancel_requested_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def create(
        cls,
        *,
        job_id: UUID,
        original_name: str,
        internal_name: str,
        now: datetime,
        demo_sha256: str | None = None,
        file_size_bytes: int | None = None,
    ) -> ImportJobRecord:
        return cls(
            job_id=job_id,
            stage=ImportJobStage.QUEUED,
            original_name=original_name,
            internal_name=internal_name,
            demo_sha256=demo_sha256,
            file_size_bytes=file_size_bytes,
            message="Waiting for the local import worker",
            progress_percent=_STAGE_PROGRESS[ImportJobStage.QUEUED],
            created_at=now,
            updated_at=now,
        )


def stage_progress(stage: ImportJobStage, previous: int = 0) -> int:
    """Return coarse pipeline completion, never fabricated parser byte progress."""

    if stage in {
        ImportJobStage.FAILED,
        ImportJobStage.CANCEL_REQUESTED,
        ImportJobStage.CANCELLED,
    }:
        return previous
    return _STAGE_PROGRESS[stage]


__all__ = ["ImportJobRecord", "ImportJobStage", "stage_progress"]
