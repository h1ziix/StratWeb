"""Database-independent contracts for canonical match persistence and queries."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalRound,
    CanonicalShot,
    CapabilityCoverageStatus,
    Sha256,
)


class PersistenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImportStatus(StrEnum):
    IMPORTED = "imported"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"
    FAILED = "failed"


class ImportResult(PersistenceModel):
    match_id: UUID
    dataset_fingerprint: Sha256
    status: ImportStatus
    row_counts: dict[str, int] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    database_path: Path


class RepositorySaveResult(PersistenceModel):
    match_id: UUID
    dataset_fingerprint: Sha256
    status: ImportStatus
    row_counts: dict[str, int]


class MatchQueryFilters(PersistenceModel):
    map_name: str | None = None
    source_demo_sha256: Sha256 | None = None
    parser_name: str | None = None
    limit: int = Field(default=100, ge=1, le=10_000)
    offset: int = Field(default=0, ge=0)


class StoredMatch(PersistenceModel):
    match_id: UUID
    demo_file_id: UUID
    dataset_fingerprint: Sha256
    source_demo_sha256: Sha256
    source_original_name: str | None = None
    map_name: str | None = None
    server_name: str | None = None
    round_count: int = Field(ge=0)
    complete_round_count: int = Field(ge=0)
    incomplete_round_count: int = Field(ge=0)
    validation_has_fatal_errors: bool
    validation_fatal_error_count: int = Field(ge=0)
    parser_name: str
    parser_version: str
    canonical_schema_version: str
    normalization_rule_version: str
    normalization_config_hash: Sha256
    imported_at: datetime


class OutcomeCapability(PersistenceModel):
    status: CapabilityCoverageStatus
    available_rounds: int = Field(ge=0)
    unavailable_rounds: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1, allow_inf_nan=False)
    can_compute_win_metrics: bool
    unavailable_reason: str | None = None


class DataUseCapability(PersistenceModel):
    status: CapabilityCoverageStatus
    available_rounds: int = Field(ge=0)
    unavailable_rounds: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1, allow_inf_nan=False)
    can_use: bool
    unavailable_reason: str | None = None


class ResultUsePolicy(PersistenceModel):
    round_winner: OutcomeCapability
    round_score: DataUseCapability


class MatchImportSummary(PersistenceModel):
    match: StoredMatch
    row_counts: dict[str, int]
    validation_issue_counts: dict[str, int]
    round_outcome: OutcomeCapability


class RoundEvents(PersistenceModel):
    match_id: UUID
    round_number: int = Field(ge=1)
    kills: tuple[CanonicalKill, ...] = ()
    damages: tuple[CanonicalDamage, ...] = ()
    shots: tuple[CanonicalShot, ...] = ()
    grenades: tuple[CanonicalGrenade, ...] = ()
    bomb_events: tuple[CanonicalBombEvent, ...] = ()


class RoundDetails(PersistenceModel):
    round: CanonicalRound
    events: RoundEvents


class DeleteMatchResult(PersistenceModel):
    match_id: UUID
    deleted: bool


class DatabaseInitResult(PersistenceModel):
    database_path: Path
    applied_migrations: tuple[int, ...]
    current_version: int = Field(ge=0)
