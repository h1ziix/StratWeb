"""Versioned public contract for a normalized Counter-Strike match dataset."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from stratweb.domain.enums import Side

CANONICAL_SCHEMA_VERSION = "1.1.0"
NORMALIZATION_RULE_VERSION = "1.2.0"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SteamId = Annotated[str, Field(pattern=r"^[0-9]+$", min_length=1, max_length=32)]
Coordinate = Annotated[float, Field(allow_inf_nan=False)]


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EventPhase(StrEnum):
    FREEZE_TIME = "freeze_time"
    LIVE = "live"
    POST_ROUND = "post_round"
    UNKNOWN = "unknown"


class DataAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING_FROM_SOURCE = "missing_from_source"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class RoundOutcomeStatus(StrEnum):
    SOURCE_EVENT = "source_event"
    DERIVED_FROM_AUTHORITATIVE_SCORE_DELTA = "derived_from_authoritative_score_delta"
    MISSING_FROM_SOURCE = "missing_from_source"
    UNRESOLVED = "unresolved"
    UNRESOLVED_CONFLICT = "unresolved_conflict"

    @property
    def is_available(self) -> bool:
        return self in {
            RoundOutcomeStatus.SOURCE_EVENT,
            RoundOutcomeStatus.DERIVED_FROM_AUTHORITATIVE_SCORE_DELTA,
        }


class CapabilityCoverageStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING_FROM_SOURCE = "missing_from_source"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CanonicalMatch(CanonicalModel):
    match_id: UUID
    demo_file_id: UUID
    map_name: str | None = None
    server_name: str | None = None
    round_count: int = Field(ge=0)
    complete_round_count: int = Field(ge=0)
    incomplete_round_count: int = Field(ge=0)
    round_count_candidates: dict[str, int]
    selected_round_count: int | None = Field(default=None, ge=0)
    selected_round_count_source: str | None = None
    round_count_disagreement: bool = False


class CanonicalTeam(CanonicalModel):
    team_id: UUID
    match_id: UUID
    internal_name: str = Field(min_length=1)
    display_name: str | None = None
    starting_player_ids: tuple[UUID, ...]
    identity_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    warnings: tuple[str, ...] = ()


class CanonicalPlayer(CanonicalModel):
    player_id: UUID
    steam_id: SteamId | None = None
    current_name: str = Field(min_length=1)
    known_names: tuple[str, ...] = Field(min_length=1)
    is_bot: bool = False
    warnings: tuple[str, ...] = ()


class PlayerTeamMembership(CanonicalModel):
    player_id: UUID
    team_id: UUID | None = None
    side: Side
    valid_from_tick: int = Field(ge=0)
    valid_to_tick: int | None = Field(default=None, ge=0)
    source: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class CanonicalRound(CanonicalModel):
    round_id: UUID
    match_id: UUID
    round_number: int = Field(ge=1)
    start_tick: int | None = Field(default=None, ge=0)
    freeze_end_tick: int | None = Field(default=None, ge=0)
    end_tick: int | None = Field(default=None, ge=0)
    official_end_tick: int | None = Field(default=None, ge=0)
    start_source: str | None = None
    end_source: str | None = None
    t_team_id: UUID | None = None
    ct_team_id: UUID | None = None
    winner_side: Side | None = None
    outcome_status: RoundOutcomeStatus = RoundOutcomeStatus.MISSING_FROM_SOURCE
    outcome_source: str | None = None
    end_reason: str | None = None
    end_reason_status: DataAvailability = DataAvailability.MISSING_FROM_SOURCE
    end_reason_source: str | None = None
    score_t_before: int | None = Field(default=None, ge=0)
    score_ct_before: int | None = Field(default=None, ge=0)
    score_t_after: int | None = Field(default=None, ge=0)
    score_ct_after: int | None = Field(default=None, ge=0)
    score_status: DataAvailability = DataAvailability.MISSING_FROM_SOURCE
    score_source: str | None = None
    is_warmup: bool = False
    is_overtime: bool = False
    is_complete: bool = False
    exclusion_reason: str | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_result_availability(self) -> Self:
        if self.winner_side is Side.UNKNOWN:
            raise ValueError("round winner must use null, not Side.UNKNOWN")
        if self.outcome_status.is_available:
            if self.winner_side not in {Side.T, Side.CT} or self.outcome_source is None:
                raise ValueError("available round outcome requires winner and source")
        elif self.winner_side is not None:
            raise ValueError("unavailable round outcome must not expose a winner")

        scores = (
            self.score_t_before,
            self.score_ct_before,
            self.score_t_after,
            self.score_ct_after,
        )
        if self.score_status is DataAvailability.AVAILABLE:
            if any(score is None for score in scores) or self.score_source is None:
                raise ValueError("available score requires before/after values and source")
        elif any(score is not None for score in scores):
            raise ValueError("unavailable score must not expose score values")

        if self.end_reason_status is DataAvailability.AVAILABLE:
            if self.end_reason is None or self.end_reason_source is None:
                raise ValueError("available end reason requires value and source")
        elif self.end_reason is not None:
            raise ValueError("unavailable end reason must not expose a value")
        return self


class CanonicalGameplayEvent(CanonicalModel):
    event_id: UUID
    match_id: UUID
    round_id: UUID | None = None
    round_number: int | None = Field(default=None, ge=1)
    tick: int = Field(ge=0)
    relative_tick: int | None = Field(default=None, ge=0)
    phase: EventPhase = EventPhase.UNKNOWN
    source_event: str = Field(min_length=1)
    warnings: tuple[str, ...] = ()


class CanonicalKill(CanonicalGameplayEvent):
    attacker_player_id: UUID | None = None
    victim_player_id: UUID | None = None
    assister_player_id: UUID | None = None
    attacker_team_id: UUID | None = None
    victim_team_id: UUID | None = None
    attacker_side: Side = Side.UNKNOWN
    victim_side: Side = Side.UNKNOWN
    weapon: str | None = None
    headshot: bool | None = None
    penetrated: int | None = Field(default=None, ge=0)
    through_smoke: bool | None = None
    no_scope: bool | None = None
    attacker_blind: bool | None = None
    distance: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    is_teamkill: bool | None = None
    is_suicide: bool | None = None


class CanonicalDamage(CanonicalGameplayEvent):
    attacker_player_id: UUID | None = None
    victim_player_id: UUID | None = None
    attacker_team_id: UUID | None = None
    victim_team_id: UUID | None = None
    attacker_side: Side = Side.UNKNOWN
    victim_side: Side = Side.UNKNOWN
    weapon: str | None = None
    damage_health: int | None = Field(default=None, ge=0)
    damage_armor: int | None = Field(default=None, ge=0)
    victim_health_after: int | None = Field(default=None, ge=0)
    hitgroup: str | None = None


class CanonicalShot(CanonicalGameplayEvent):
    player_id: UUID | None = None
    team_id: UUID | None = None
    side: Side = Side.UNKNOWN
    weapon: str | None = None
    silenced: bool | None = None


class CanonicalGrenade(CanonicalGameplayEvent):
    player_id: UUID | None = None
    team_id: UUID | None = None
    side: Side = Side.UNKNOWN
    grenade_type: str = Field(min_length=1)
    lifecycle_event: str = Field(min_length=1)
    entity_id: int | None = Field(default=None, ge=0)
    x: Coordinate | None = None
    y: Coordinate | None = None
    z: Coordinate | None = None


class CanonicalBombEvent(CanonicalGameplayEvent):
    player_id: UUID | None = None
    team_id: UUID | None = None
    side: Side = Side.UNKNOWN
    event_type: str = Field(min_length=1)
    site_raw: str | int | None = None
    site_normalized: str | None = None


class ValidationIssue(CanonicalModel):
    code: str = Field(min_length=1)
    severity: ValidationSeverity
    is_fatal: bool = False
    entity_type: str = Field(min_length=1)
    entity_id: str | None = None
    message: str = Field(min_length=1)
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
    rule_version: str = Field(min_length=1)


class ValidationReport(CanonicalModel):
    is_valid: bool
    has_fatal_errors: bool
    fatal_error_count: int = Field(ge=0)
    issue_counts: dict[ValidationSeverity, int]
    unassigned_event_count: int = Field(ge=0)
    unknown_player_count: int = Field(ge=0)
    incomplete_round_count: int = Field(ge=0)
    issues: tuple[ValidationIssue, ...]


class ResultCapability(CanonicalModel):
    status: CapabilityCoverageStatus
    source_events_checked: tuple[str, ...]
    detected_fields: tuple[str, ...]
    authoritative_source_found: bool
    total_round_count: int = Field(ge=0)
    rounds_available: int = Field(ge=0)
    rounds_missing: int = Field(ge=0)
    rounds_unresolved: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_coverage_counts(self) -> Self:
        if (
            self.rounds_available + self.rounds_missing + self.rounds_unresolved
            != self.total_round_count
        ):
            raise ValueError("result capability counts must cover every round")
        if self.authoritative_source_found != bool(self.detected_fields):
            raise ValueError("authoritative source flag must match detected fields")
        if self.total_round_count == 0:
            expected_status = CapabilityCoverageStatus.NOT_APPLICABLE
        elif self.rounds_available == self.total_round_count:
            expected_status = CapabilityCoverageStatus.AVAILABLE
        elif self.rounds_available:
            expected_status = CapabilityCoverageStatus.PARTIAL
        elif self.rounds_unresolved:
            expected_status = CapabilityCoverageStatus.UNRESOLVED
        else:
            expected_status = CapabilityCoverageStatus.MISSING_FROM_SOURCE
        if self.status is not expected_status:
            raise ValueError("result capability status is inconsistent with counts")
        return self


class ResultCapabilities(CanonicalModel):
    round_winner: ResultCapability
    round_score: ResultCapability
    round_end_reason: ResultCapability


class NormalizationMetadata(CanonicalModel):
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    canonical_schema_version: str = CANONICAL_SCHEMA_VERSION
    normalization_rule_version: str = NORMALIZATION_RULE_VERSION
    normalization_config_hash: Sha256
    source_demo_sha256: Sha256
    source_event_counts: dict[str, int]
    selected_event_aliases: dict[str, str | None]
    result_capabilities: ResultCapabilities
    warnings: tuple[str, ...] = ()


class CanonicalMatchDataset(CanonicalModel):
    schema_version: str = CANONICAL_SCHEMA_VERSION
    dataset_fingerprint: Sha256
    match: CanonicalMatch
    teams: tuple[CanonicalTeam, ...]
    players: tuple[CanonicalPlayer, ...]
    player_team_memberships: tuple[PlayerTeamMembership, ...]
    rounds: tuple[CanonicalRound, ...]
    kills: tuple[CanonicalKill, ...]
    damages: tuple[CanonicalDamage, ...]
    shots: tuple[CanonicalShot, ...]
    grenades: tuple[CanonicalGrenade, ...]
    bomb_events: tuple[CanonicalBombEvent, ...]
    validation_report: ValidationReport
    normalization_metadata: NormalizationMetadata


class CanonicalizationSummary(CanonicalModel):
    schema_version: str = CANONICAL_SCHEMA_VERSION
    map_name: str | None = None
    round_count: int = Field(ge=0)
    complete_round_count: int = Field(ge=0)
    incomplete_round_count: int = Field(ge=0)
    players: int = Field(ge=0)
    teams: int = Field(ge=0)
    kills: int = Field(ge=0)
    damages: int = Field(ge=0)
    shots: int = Field(ge=0)
    grenades: int = Field(ge=0)
    bomb_events: int = Field(ge=0)
    unassigned_events: int = Field(ge=0)
    validation_issues: dict[ValidationSeverity, int]
    fatal_validation_errors: int = Field(ge=0)
    dataset_fingerprint: Sha256

    @classmethod
    def from_dataset(cls, dataset: CanonicalMatchDataset) -> CanonicalizationSummary:
        return cls(
            map_name=dataset.match.map_name,
            round_count=dataset.match.round_count,
            complete_round_count=dataset.match.complete_round_count,
            incomplete_round_count=dataset.match.incomplete_round_count,
            players=len(dataset.players),
            teams=len(dataset.teams),
            kills=len(dataset.kills),
            damages=len(dataset.damages),
            shots=len(dataset.shots),
            grenades=len(dataset.grenades),
            bomb_events=len(dataset.bomb_events),
            unassigned_events=dataset.validation_report.unassigned_event_count,
            validation_issues=dataset.validation_report.issue_counts,
            fatal_validation_errors=dataset.validation_report.fatal_error_count,
            dataset_fingerprint=dataset.dataset_fingerprint,
        )
