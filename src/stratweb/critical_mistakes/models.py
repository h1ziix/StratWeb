"""Versioned contracts for coach-facing critical mistakes."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.domain.enums import Side

CRITICAL_MISTAKES_SCHEMA_VERSION = "1.0.0"
CRITICAL_MISTAKES_RULE_VERSION = "critical_round_filters_v1"
EARLY_DEATH_WINDOW_SECONDS = 15.0


class CriticalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CriticalMistakeType(StrEnum):
    LOST_PLUS_TWO = "lost_plus_two"
    LOST_VS_FULL_ECO = "lost_vs_full_eco"
    EARLY_UNTRADED_DEATH = "early_untraded_death"


class CriticalCapabilityStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class CriticalSourcePin(CriticalModel):
    match_id: UUID
    team_id: UUID
    map_name: str
    dataset_fingerprint: Sha256
    analytics_fingerprint: Sha256
    analytics_rule_version: str
    temporal_run_id: UUID
    temporal_fingerprint: Sha256
    temporal_rule_version: str
    economy_run_id: UUID | None = None
    economy_fingerprint: Sha256 | None = None
    economy_rule_version: str | None = None
    tickrate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    tickrate_source: str | None = None


class CriticalEvidence(CriticalModel):
    match_id: UUID
    round_number: int = Field(ge=1)
    tick: int | None = Field(default=None, ge=0)
    event_ids: tuple[UUID, ...] = ()
    temporal_group_id: UUID | None = None
    economy_snapshot_id: UUID | None = None
    victim_player_id: UUID | None = None
    facts: tuple[str, ...] = Field(min_length=1)


class CriticalCandidate(CriticalModel):
    mistake_type: CriticalMistakeType
    map_name: str
    side: Side
    evidence: CriticalEvidence
    title: str
    observation: str
    tactical_interpretation: str
    recommendation: str


class CriticalMistakesInput(CriticalModel):
    profile_id: UUID
    source_pins: tuple[CriticalSourcePin, ...]
    eligible_counts: dict[CriticalMistakeType, int]
    candidates: tuple[CriticalCandidate, ...]
    capabilities: dict[CriticalMistakeType, CriticalCapabilityStatus]
    limitations: dict[CriticalMistakeType, tuple[str, ...]]
    warnings: tuple[str, ...] = ()


class CriticalMistake(CriticalModel):
    mistake_id: UUID
    critical_run_id: UUID
    mistake_type: CriticalMistakeType
    map_name: str
    side: Side
    title: str
    observation: str
    tactical_interpretation: str
    recommendation: str
    numerator: int = Field(ge=1)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1, allow_inf_nan=False)
    sample_size: int = Field(ge=1)
    evidence: CriticalEvidence
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_metric(self) -> CriticalMistake:
        if self.numerator > self.denominator:
            raise ValueError("critical mistake numerator exceeds denominator")
        if abs(self.frequency - (self.numerator / self.denominator)) > 1e-12:
            raise ValueError("critical mistake frequency is inconsistent")
        return self


class CriticalMistakesSummary(CriticalModel):
    total: int = Field(ge=0)
    lost_plus_two: int = Field(ge=0)
    lost_vs_full_eco: int = Field(ge=0)
    early_untraded_death: int = Field(ge=0)


class CriticalMistakesRun(CriticalModel):
    critical_schema_version: str = CRITICAL_MISTAKES_SCHEMA_VERSION
    critical_rule_version: str = CRITICAL_MISTAKES_RULE_VERSION
    critical_run_id: UUID
    critical_fingerprint: Sha256
    profile_id: UUID
    source_pins: tuple[CriticalSourcePin, ...]
    capabilities: dict[CriticalMistakeType, CriticalCapabilityStatus]
    mistakes: tuple[CriticalMistake, ...]
    summary: CriticalMistakesSummary
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def validate_contents(self) -> CriticalMistakesRun:
        if any(item.critical_run_id != self.critical_run_id for item in self.mistakes):
            raise ValueError("critical mistake belongs to another run")
        if self.summary.total != len(self.mistakes):
            raise ValueError("critical mistakes total is inconsistent")
        return self


class CriticalSaveStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"


class CriticalSaveResult(CriticalModel):
    critical_run_id: UUID
    critical_fingerprint: Sha256
    status: CriticalSaveStatus


__all__ = [
    name
    for name in globals()
    if name.startswith("Critical")
    or name.startswith("CRITICAL")
    or name == "EARLY_DEATH_WINDOW_SECONDS"
]
