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
    COMPLETE = "complete"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {ImportJobStage.COMPLETE, ImportJobStage.FAILED}


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
    ) -> ImportJobRecord:
        return cls(
            job_id=job_id,
            stage=ImportJobStage.QUEUED,
            original_name=original_name,
            internal_name=internal_name,
            message="Waiting for the local import worker",
            progress_percent=_STAGE_PROGRESS[ImportJobStage.QUEUED],
            created_at=now,
            updated_at=now,
        )


def stage_progress(stage: ImportJobStage, previous: int = 0) -> int:
    """Return coarse pipeline completion, never fabricated parser byte progress."""

    if stage is ImportJobStage.FAILED:
        return previous
    return _STAGE_PROGRESS[stage]


__all__ = ["ImportJobRecord", "ImportJobStage", "stage_progress"]
