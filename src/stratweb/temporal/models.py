"""Immutable contracts for Temporal Round State Engine 1.1."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalPlayer,
    CanonicalRound,
    CanonicalShot,
    CanonicalTeam,
    EventPhase,
    PlayerTeamMembership,
    Sha256,
    ValidationSeverity,
)
from stratweb.domain.enums import Side

TEMPORAL_SCHEMA_VERSION = "1.1.0"
TEMPORAL_RULE_VERSION = "1.1.0"
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class TemporalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TemporalAvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNRESOLVED = "unresolved"


class TemporalUnavailableReason(StrEnum):
    MISSING_TICKRATE = "missing_tickrate"
    MISSING_ROUND_BOUNDARY = "missing_round_boundary"
    MISSING_PARTICIPANTS = "missing_participants"
    CONFLICTING_EVENTS = "conflicting_events"
    OUT_OF_RANGE_EVENTS = "out_of_range_events"
    INCOMPLETE_ROUND = "incomplete_round"
    UNSUPPORTED_BOMB_SEMANTICS = "unsupported_bomb_semantics"
    SOURCE_CONFLICT = "source_conflict"
    NO_POPULATION = "no_population"
    AMBIGUOUS_SAME_TICK_ORDER = "ambiguous_same_tick_order"
    DEATH_EFFECT_UNAVAILABLE = "death_effect_unavailable"
    LEGACY_SEMANTICS = "legacy_semantics"


class TemporalConversionStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class RoundPhase(StrEnum):
    PRESTART = "prestart"
    FREEZE_TIME = "freeze_time"
    LIVE = "live"
    POST_ROUND = "post_round"
    ENDED = "ended"
    UNKNOWN = "unknown"


class PhaseIntervalStatus(StrEnum):
    AVAILABLE = "available"
    INFERRED_AUTHORITATIVELY = "inferred_authoritatively"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"


class ParticipationStatus(StrEnum):
    CONFIRMED = "confirmed"
    INFERRED_FROM_MEMBERSHIP = "inferred_from_membership"
    EVENT_OBSERVED = "event_observed"
    UNRESOLVED = "unresolved"
    NOT_PARTICIPATING = "not_participating"


class PlayerLifeStatus(StrEnum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"
    NOT_PARTICIPATING = "not_participating"


class TemporalDeathClassification(StrEnum):
    ENEMY = "enemy"
    TEAMKILL = "teamkill"
    SUICIDE = "suicide"
    WORLD = "world"
    UNKNOWN = "unknown"
    REPEATED = "repeated"


class BombState(StrEnum):
    UNAVAILABLE = "unavailable"
    CARRIED = "carried"
    DROPPED = "dropped"
    PLANTED = "planted"
    DEFUSING = "defusing"
    DEFUSED = "defused"
    EXPLODED = "exploded"
    ROUND_ENDED_BEFORE_RESOLUTION = "round_ended_before_resolution"
    UNRESOLVED = "unresolved"


class TemporalEventKind(StrEnum):
    PHASE_BOUNDARY = "phase_boundary"
    DAMAGE = "damage"
    SHOT = "shot"
    GRENADE = "grenade"
    DEATH = "death"
    BOMB = "bomb"
    ROUND_END = "round_end"
    OFFICIAL_END = "official_end"
    FALLBACK_END = "fallback_end"


class TemporalOrderingStatus(StrEnum):
    DEFINITIVE = "definitive"
    SIMULTANEOUS_AMBIGUOUS = "simultaneous_ambiguous"
    OUT_OF_RANGE = "out_of_range"


class SimultaneousOrderingStatus(StrEnum):
    DEFINITIVELY_ORDERED = "definitively_ordered"
    CANONICALLY_GROUPED = "canonically_grouped"
    AMBIGUOUS_ORDER = "ambiguous_order"
    CONFLICTING = "conflicting"


class IntermediateStateStatus(StrEnum):
    DETERMINISTIC = "deterministic"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class FinalStateStatus(StrEnum):
    DETERMINISTIC = "deterministic"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


class DeathEffectStatus(StrEnum):
    APPLIED = "applied"
    UNAVAILABLE = "unavailable"
    CONFLICTING = "conflicting"
    OUT_OF_RANGE = "out_of_range"


class SnapshotStateStatus(StrEnum):
    AVAILABLE = "available"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class TemporalTransitionType(StrEnum):
    PHASE_CHANGED = "phase_changed"
    PARTICIPANT_OBSERVED = "participant_observed"
    PLAYER_DIED = "player_died"
    BOMB_PLANTED = "bomb_planted"
    BOMB_DEFUSED = "bomb_defused"
    BOMB_EXPLODED = "bomb_exploded"
    ROUND_ENDED = "round_ended"
    AMBIGUITY_DETECTED = "ambiguity_detected"


class TemporalTransitionStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"


class TemporalComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class TemporalTime(TemporalModel):
    tick: int = Field(ge=0)
    seconds: NonNegativeFloat | None = None
    conversion_status: TemporalConversionStatus
    conversion_source: str | None = None
    tickrate: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_conversion(self) -> TemporalTime:
        available = self.conversion_status is TemporalConversionStatus.AVAILABLE
        if available != (
            self.seconds is not None and self.tickrate is not None and bool(self.conversion_source)
        ):
            raise ValueError("temporal seconds require tickrate and conversion source")
        if not available and any(
            value is not None for value in (self.seconds, self.tickrate, self.conversion_source)
        ):
            raise ValueError("unavailable temporal conversion cannot expose seconds metadata")
        return self


class TemporalConfig(TemporalModel):
    tickrate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    tickrate_source: str | None = None
    conflicting_tickrate_sources: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_tickrate_source(self) -> TemporalConfig:
        if (self.tickrate is None) != (self.tickrate_source is None):
            raise ValueError("tickrate and tickrate source must be supplied together")
        if self.tickrate is not None and not isfinite(self.tickrate):
            raise ValueError("tickrate must be finite")
        if self.tickrate_source is not None and not self.tickrate_source.startswith("canonical:"):
            raise ValueError("tickrate source must be proven canonical evidence")
        return self


class TemporalCapability(TemporalModel):
    status: TemporalAvailabilityStatus
    reasons: tuple[TemporalUnavailableReason, ...] = ()
    population: int = Field(ge=0)
    covered: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_coverage(self) -> TemporalCapability:
        if self.covered > self.population:
            raise ValueError("temporal capability covered count exceeds population")
        if self.status is TemporalAvailabilityStatus.AVAILABLE and self.reasons:
            raise ValueError("available temporal capability cannot contain reasons")
        return self


def _legacy_capability() -> TemporalCapability:
    return TemporalCapability(
        status=TemporalAvailabilityStatus.UNAVAILABLE,
        reasons=(TemporalUnavailableReason.LEGACY_SEMANTICS,),
        population=1,
        covered=0,
    )


class TemporalAvailability(TemporalModel):
    tick_timeline: TemporalCapability
    seconds_timeline: TemporalCapability
    phase_timeline: TemporalCapability
    participant_state: TemporalCapability
    alive_state: TemporalCapability
    bomb_state: TemporalCapability
    final_state: TemporalCapability
    # Defaults keep persisted 1.0 payloads readable without pretending that they
    # had 1.1 group semantics.
    tick_group_state: TemporalCapability = Field(default_factory=lambda: _legacy_capability())
    per_event_state: TemporalCapability = Field(default_factory=lambda: _legacy_capability())
    intermediate_ordering: TemporalCapability = Field(default_factory=lambda: _legacy_capability())
    final_alive_state: TemporalCapability = Field(default_factory=lambda: _legacy_capability())


class PhaseInterval(TemporalModel):
    interval_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    phase: RoundPhase
    start_tick: int = Field(ge=0)
    end_tick: int | None = Field(default=None, ge=0)
    start_source: str
    end_source: str | None = None
    status: PhaseIntervalStatus


class ParticipantRoundState(TemporalModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    player_id: UUID
    physical_team_id: UUID | None = None
    side: Side
    participation_status: ParticipationStatus
    participation_sources: tuple[str, ...] = ()
    initial_alive_status: PlayerLifeStatus
    first_seen_tick: int | None = Field(default=None, ge=0)
    last_seen_tick: int | None = Field(default=None, ge=0)


class TemporalEvent(TemporalModel):
    event_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    time: TemporalTime
    kind: TemporalEventKind
    event_type: str
    source_event: str
    canonical_phase: EventPhase
    priority: int = Field(ge=0)
    actor_player_id: UUID | None = None
    victim_player_id: UUID | None = None
    physical_team_id: UUID | None = None
    side: Side = Side.UNKNOWN
    site_raw: str | int | None = None
    combat_death_classification: TemporalDeathClassification | None = None
    death_effect_status: DeathEffectStatus | None = None
    state_affecting: bool
    ordering_status: TemporalOrderingStatus = TemporalOrderingStatus.DEFINITIVE
    simultaneous_group_id: UUID | None = None
    warnings: tuple[str, ...] = ()


class GroupStateProjection(TemporalModel):
    alive_players: tuple[UUID, ...]
    dead_players: tuple[UUID, ...]
    unknown_players: tuple[UUID, ...]
    t_alive: int = Field(ge=0)
    ct_alive: int = Field(ge=0)
    team_alive_counts: dict[UUID, int]
    bomb_state: BombState


class SimultaneousEventGroup(TemporalModel):
    group_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    ordered_event_ids: tuple[UUID, ...]
    event_count: int = Field(ge=2)
    involved_player_ids: tuple[UUID, ...]
    involved_event_families: tuple[TemporalEventKind, ...]
    ordering_status: SimultaneousOrderingStatus
    intermediate_state_status: IntermediateStateStatus
    final_state_status: FinalStateStatus
    ambiguity_reasons: tuple[str, ...] = ()
    validation_issues: tuple[TemporalValidationIssue, ...] = ()
    pre_group_state: GroupStateProjection
    possible_intermediate_states: tuple[GroupStateProjection, ...] = ()
    post_group_state: GroupStateProjection | None = None
    post_group_snapshot_deterministic: bool


class LifeTransition(TemporalModel):
    transition_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    time: TemporalTime
    event_id: UUID
    player_id: UUID
    before: PlayerLifeStatus
    after: PlayerLifeStatus
    death_classification: TemporalDeathClassification
    killer_player_id: UUID | None = None
    source: str
    status: TemporalTransitionStatus


class BombTransition(TemporalModel):
    transition_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    time: TemporalTime
    event_id: UUID | None = None
    before: BombState
    after: BombState
    actor_player_id: UUID | None = None
    physical_team_id: UUID | None = None
    side: Side = Side.UNKNOWN
    site_raw: str | int | None = None
    source: str
    status: TemporalTransitionStatus


class TemporalTransition(TemporalModel):
    transition_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    time: TemporalTime
    event_id: UUID | None = None
    transition_type: TemporalTransitionType
    before_state: dict[str, JsonValue]
    after_state: dict[str, JsonValue]
    source: str
    status: TemporalTransitionStatus


class TemporalValidationIssue(TemporalModel):
    code: str = Field(min_length=1)
    severity: ValidationSeverity
    is_fatal: bool = False
    entity_type: str = Field(min_length=1)
    entity_id: str | None = None
    message: str = Field(min_length=1)
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class RoundTimeline(TemporalModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    start_tick: int | None = Field(default=None, ge=0)
    freeze_end_tick: int | None = Field(default=None, ge=0)
    live_start_tick: int | None = Field(default=None, ge=0)
    end_tick: int | None = Field(default=None, ge=0)
    official_end_tick: int | None = Field(default=None, ge=0)
    effective_end_tick: int | None = Field(default=None, ge=0)
    end_source: str | None = None
    complete: bool
    overtime: bool
    participants: tuple[ParticipantRoundState, ...]
    ordered_events: tuple[TemporalEvent, ...]
    simultaneous_groups: tuple[SimultaneousEventGroup, ...] = ()
    phase_intervals: tuple[PhaseInterval, ...]
    state_transitions: tuple[TemporalTransition, ...]
    life_transitions: tuple[LifeTransition, ...]
    bomb_transitions: tuple[BombTransition, ...]
    final_bomb_state: BombState
    availability: TemporalAvailability
    validation_issues: tuple[TemporalValidationIssue, ...]
    ambiguity_flags: tuple[str, ...] = ()


class TemporalMatchInput(TemporalModel):
    match_id: UUID
    dataset_fingerprint: Sha256
    teams: tuple[CanonicalTeam, ...]
    players: tuple[CanonicalPlayer, ...]
    memberships: tuple[PlayerTeamMembership, ...]
    rounds: tuple[CanonicalRound, ...]
    kills: tuple[CanonicalKill, ...]
    damages: tuple[CanonicalDamage, ...]
    shots: tuple[CanonicalShot, ...]
    grenades: tuple[CanonicalGrenade, ...]
    bomb_events: tuple[CanonicalBombEvent, ...]


class TemporalSummary(TemporalModel):
    rounds: int = Field(ge=0)
    complete_rounds: int = Field(ge=0)
    total_temporal_events: int = Field(ge=0)
    total_transitions: int = Field(ge=0)
    life_transitions: int = Field(ge=0)
    bomb_transitions: int = Field(ge=0)
    participant_states: int = Field(ge=0)
    ambiguity_groups: int = Field(ge=0)
    ambiguous_order_groups: int = Field(default=0, ge=0)
    ambiguous_intermediate_groups: int = Field(default=0, ge=0)
    ambiguous_final_groups: int = Field(default=0, ge=0)
    conflicting_groups: int = Field(default=0, ge=0)
    death_events_without_victim: int = Field(default=0, ge=0)
    availability: TemporalAvailability


class TemporalMatchState(TemporalModel):
    temporal_schema_version: str = TEMPORAL_SCHEMA_VERSION
    temporal_rule_version: str = TEMPORAL_RULE_VERSION
    temporal_config_hash: Sha256
    temporal_fingerprint: Sha256
    temporal_run_id: UUID
    match_id: UUID
    dataset_fingerprint: Sha256
    config: TemporalConfig
    timelines: tuple[RoundTimeline, ...]
    summary: TemporalSummary
    validation_issues: tuple[TemporalValidationIssue, ...]
    warnings: tuple[str, ...] = ()


class RoundSnapshot(TemporalModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    time: TemporalTime
    phase: RoundPhase
    participants: tuple[UUID, ...]
    alive_players: tuple[UUID, ...]
    dead_players: tuple[UUID, ...]
    unknown_players: tuple[UUID, ...]
    t_alive: int = Field(ge=0)
    ct_alive: int = Field(ge=0)
    team_alive_counts: dict[UUID, int]
    bomb_state: BombState
    last_event_ids: tuple[UUID, ...]
    availability: TemporalAvailability
    state_status: SnapshotStateStatus = SnapshotStateStatus.AVAILABLE
    tick_group_id: UUID | None = None
    post_group_state_deterministic: bool | None = None
    possible_states: tuple[GroupStateProjection, ...] = ()
    unavailable_reasons: tuple[TemporalUnavailableReason, ...] = ()
    ambiguity_flags: tuple[str, ...] = ()


class TemporalSaveResult(TemporalModel):
    temporal_fingerprint: Sha256
    temporal_run_id: UUID
    status: TemporalComputeStatus
    row_counts: dict[str, int]


class TemporalComputeResult(TemporalModel):
    match_id: UUID
    dataset_fingerprint: Sha256
    temporal_fingerprint: Sha256
    temporal_run_id: UUID
    temporal_schema_version: str
    temporal_rule_version: str
    temporal_config_hash: Sha256
    status: TemporalComputeStatus
    row_counts: dict[str, int]
    config: TemporalConfig
    capability_summary: TemporalAvailability
    warnings: tuple[str, ...]
    duration_seconds: NonNegativeFloat


class TemporalRunSummary(TemporalModel):
    temporal_schema_version: str
    temporal_rule_version: str
    temporal_config_hash: Sha256
    temporal_fingerprint: Sha256
    temporal_run_id: UUID
    match_id: UUID
    dataset_fingerprint: Sha256
    config: TemporalConfig
    summary: TemporalSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]


class TemporalRunRecord(TemporalModel):
    temporal_run_id: UUID
    temporal_fingerprint: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    temporal_schema_version: str
    temporal_rule_version: str
    created_at: datetime
    compatible: bool
    legacy: bool
    selected_by_default: bool


class DeleteTemporalResult(TemporalModel):
    temporal_fingerprint: Sha256 | None = None
    deleted: bool
