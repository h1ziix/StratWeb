"""Typed parser-independent contracts for Gameplay Analytics Engine V1."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from math import isfinite
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalKill,
    CanonicalPlayer,
    CanonicalRound,
    CanonicalShot,
    CanonicalTeam,
    PlayerTeamMembership,
    Sha256,
    ValidationSeverity,
)
from stratweb.domain.enums import Side

ANALYTICS_SCHEMA_VERSION = "1.1.0"
ANALYTICS_RULE_VERSION = "1.1.0"
DEFAULT_TRADE_WINDOW_TICKS = 320
Percentage = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Ratio = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalyticsAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class AnalyticsUnavailableReason(StrEnum):
    MISSING_ROUND_WINNER = "missing_round_winner"
    INCOMPLETE_ROUNDS = "incomplete_rounds"
    MISSING_PARTICIPANTS = "missing_participants"
    MISSING_TICKRATE = "missing_tickrate"
    UNSUPPORTED_EVENT_SEMANTICS = "unsupported_event_semantics"
    NO_POPULATION = "no_population"
    SOURCE_CONFLICT = "source_conflict"
    LEGACY_AMBIGUOUS = "legacy_ambiguous"


class TradeWindowMode(StrEnum):
    TICKS = "ticks"
    SECONDS = "seconds"
    LEGACY_AMBIGUOUS = "legacy_ambiguous"


class TradeWindowResolutionSource(StrEnum):
    EXPLICIT_TICKS = "explicit_ticks"
    CANONICAL_TICKRATE = "canonical_tickrate"
    LEGACY_AMBIGUOUS = "legacy_ambiguous"


class TimeConversionStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    LEGACY_AMBIGUOUS = "legacy_ambiguous"


class AnalyticsCapability(AnalyticsModel):
    status: AnalyticsAvailability
    reasons: tuple[AnalyticsUnavailableReason, ...] = ()
    population: int = Field(ge=0)
    covered: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_coverage(self) -> AnalyticsCapability:
        if self.covered > self.population:
            raise ValueError("analytics capability covered count exceeds population")
        if self.status is AnalyticsAvailability.AVAILABLE and self.reasons:
            raise ValueError("available analytics capability cannot have unavailable reasons")
        return self


class TradePolicyCapability(AnalyticsCapability):
    trade_window_mode: TradeWindowMode
    requested_ticks: int | None = Field(default=None, gt=0)
    requested_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    resolved_ticks: int | None = Field(default=None, gt=0)
    tickrate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    tickrate_source: str | None = None
    resolution_source: TradeWindowResolutionSource

    @model_validator(mode="after")
    def validate_policy(self) -> TradePolicyCapability:
        TradeWindowConfig(
            mode=self.trade_window_mode,
            requested_ticks=self.requested_ticks,
            requested_seconds=self.requested_seconds,
            resolved_ticks=self.resolved_ticks,
            tickrate=self.tickrate,
            tickrate_source=self.tickrate_source,
            resolution_source=self.resolution_source,
        )
        return self


class AnalyticsAvailabilitySummary(AnalyticsModel):
    combat_metrics: AnalyticsCapability
    opening_metrics: AnalyticsCapability
    trade_metrics: TradePolicyCapability
    kast_metrics: TradePolicyCapability
    win_conversion_metrics: AnalyticsCapability
    bomb_metrics: AnalyticsCapability
    score_metrics: AnalyticsCapability
    advantage_metrics: AnalyticsCapability


class TradeWindowConfig(AnalyticsModel):
    mode: TradeWindowMode = TradeWindowMode.TICKS
    requested_ticks: int | None = Field(default=DEFAULT_TRADE_WINDOW_TICKS, gt=0)
    requested_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    resolved_ticks: int | None = Field(default=DEFAULT_TRADE_WINDOW_TICKS, gt=0)
    tickrate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    tickrate_source: str | None = None
    resolution_source: TradeWindowResolutionSource = TradeWindowResolutionSource.EXPLICIT_TICKS

    @classmethod
    def ticks(cls, ticks: int = DEFAULT_TRADE_WINDOW_TICKS) -> TradeWindowConfig:
        return cls(requested_ticks=ticks, resolved_ticks=ticks)

    @classmethod
    def seconds(
        cls,
        seconds: float,
        *,
        tickrate: float,
        tickrate_source: str,
    ) -> TradeWindowConfig:
        return cls(
            mode=TradeWindowMode.SECONDS,
            requested_ticks=None,
            requested_seconds=seconds,
            resolved_ticks=seconds_to_ticks(seconds, tickrate),
            tickrate=tickrate,
            tickrate_source=tickrate_source,
            resolution_source=TradeWindowResolutionSource.CANONICAL_TICKRATE,
        )

    @classmethod
    def legacy_ambiguous(cls) -> TradeWindowConfig:
        return cls(
            mode=TradeWindowMode.LEGACY_AMBIGUOUS,
            requested_ticks=None,
            requested_seconds=None,
            resolved_ticks=None,
            resolution_source=TradeWindowResolutionSource.LEGACY_AMBIGUOUS,
        )

    @model_validator(mode="after")
    def validate_mode(self) -> TradeWindowConfig:
        if self.mode is TradeWindowMode.TICKS:
            if (
                self.requested_ticks is None
                or self.requested_seconds is not None
                or self.resolved_ticks != self.requested_ticks
                or self.tickrate is not None
                or self.tickrate_source is not None
                or self.resolution_source is not TradeWindowResolutionSource.EXPLICIT_TICKS
            ):
                raise ValueError("ticks mode requires only matching requested/resolved ticks")
        elif self.mode is TradeWindowMode.SECONDS:
            if (
                self.requested_ticks is not None
                or self.requested_seconds is None
                or self.tickrate is None
                or not self.tickrate_source
                or self.resolution_source is not TradeWindowResolutionSource.CANONICAL_TICKRATE
                or self.resolved_ticks != seconds_to_ticks(self.requested_seconds, self.tickrate)
            ):
                raise ValueError(
                    "seconds mode requires proven tickrate and deterministic resolved ticks"
                )
        elif (
            any(
                value is not None
                for value in (
                    self.requested_ticks,
                    self.requested_seconds,
                    self.resolved_ticks,
                    self.tickrate,
                    self.tickrate_source,
                )
            )
            or self.resolution_source is not TradeWindowResolutionSource.LEGACY_AMBIGUOUS
        ):
            raise ValueError("legacy ambiguous mode cannot assert a trade-window value")
        return self


class AnalyticsConfig(AnalyticsModel):
    trade_window: TradeWindowConfig = Field(default_factory=TradeWindowConfig)

    @property
    def resolved_trade_window_ticks(self) -> int | None:
        return self.trade_window.resolved_ticks


class TickrateEvidence(AnalyticsModel):
    tickrate: float = Field(gt=0, allow_inf_nan=False)
    source: str = Field(min_length=1)
    conflicting_sources: tuple[str, ...] = ()


def seconds_to_ticks(seconds: float, tickrate: float) -> int:
    """Round positive seconds*tickrate to nearest tick, with exact halves rounded up."""

    if not isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be a positive finite value")
    if not isfinite(tickrate) or tickrate <= 0:
        raise ValueError("tickrate must be a positive finite value")
    product = Decimal(str(seconds)) * Decimal(str(tickrate))
    return max(1, int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


class MatchAnalyticsInput(AnalyticsModel):
    match_id: UUID
    dataset_fingerprint: Sha256
    teams: tuple[CanonicalTeam, ...]
    players: tuple[CanonicalPlayer, ...]
    memberships: tuple[PlayerTeamMembership, ...]
    rounds: tuple[CanonicalRound, ...]
    kills: tuple[CanonicalKill, ...]
    damages: tuple[CanonicalDamage, ...]
    shots: tuple[CanonicalShot, ...]
    bomb_events: tuple[CanonicalBombEvent, ...]


class MultikillCategory(StrEnum):
    ZERO = "zero"
    ONE = "one"
    TWO = "two"
    THREE = "three"
    FOUR = "four"
    FIVE = "five"
    FIVE_PLUS = "five_plus"


class PlayerRoundAnalytics(AnalyticsModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    player_id: UUID
    team_id: UUID
    side: Side
    kills: int = Field(ge=0)
    deaths: int = Field(ge=0)
    assists: int = Field(ge=0)
    headshots: int = Field(ge=0)
    damage: int = Field(ge=0)
    enemy_damage: int = Field(ge=0)
    team_damage: int = Field(ge=0)
    shots: int = Field(ge=0)
    survived: bool
    traded_kills: int | None = Field(default=None, ge=0)
    traded_deaths: int | None = Field(default=None, ge=0)
    trade_opportunities: int | None = Field(default=None, ge=0)
    successful_trades: int | None = Field(default=None, ge=0)
    opening_kill: bool
    opening_death: bool
    multikill_count: int = Field(ge=0)
    multikill_category: MultikillCategory
    kast_k: bool
    kast_a: bool
    kast_s: bool
    kast_t: bool | None = None
    kast: bool | None = None
    teamkill_count: int = Field(ge=0)
    suicide_count: int = Field(ge=0)
    plants: int = Field(ge=0)
    defuses: int = Field(ge=0)


class PlayerMatchAnalytics(AnalyticsModel):
    match_id: UUID
    player_id: UUID
    current_name: str
    steam_id: str | None = None
    rounds_played: int = Field(ge=0)
    kills: int = Field(ge=0)
    deaths: int = Field(ge=0)
    assists: int = Field(ge=0)
    kd_ratio: Ratio | None = None
    kill_differential: int
    adr: Ratio | None = None
    kpr: Ratio | None = None
    dpr: Ratio | None = None
    apr: Ratio | None = None
    headshots: int = Field(ge=0)
    headshot_percentage: Percentage | None = None
    total_damage: int = Field(ge=0)
    enemy_damage: int = Field(ge=0)
    team_damage: int = Field(ge=0)
    shots: int = Field(ge=0)
    survival_rounds: int = Field(ge=0)
    survival_percentage: Percentage | None = None
    opening_kills: int = Field(ge=0)
    opening_deaths: int = Field(ge=0)
    opening_duel_attempts: int = Field(ge=0)
    opening_duel_success_percentage: Percentage | None = None
    opening_kill_round_wins: int | None = Field(default=None, ge=0)
    opening_kill_conversion_percentage: Percentage | None = None
    traded_kills: int | None = Field(default=None, ge=0)
    traded_deaths: int | None = Field(default=None, ge=0)
    trade_opportunities: int | None = Field(default=None, ge=0)
    successful_trades: int | None = Field(default=None, ge=0)
    trade_success_percentage: Percentage | None = None
    traded_death_percentage: Percentage | None = None
    multikill_rounds: int = Field(ge=0)
    two_k_rounds: int = Field(ge=0)
    three_k_rounds: int = Field(ge=0)
    four_k_rounds: int = Field(ge=0)
    five_k_rounds: int = Field(ge=0)
    five_plus_rounds: int = Field(ge=0)
    kast_rounds: int | None = Field(default=None, ge=0)
    kast_percentage: Percentage | None = None
    kast_k_rounds: int = Field(ge=0)
    kast_a_rounds: int = Field(ge=0)
    kast_s_rounds: int = Field(ge=0)
    kast_t_rounds: int | None = Field(default=None, ge=0)
    teamkills: int = Field(ge=0)
    suicides: int = Field(ge=0)
    plants: int = Field(ge=0)
    defuses: int = Field(ge=0)


class OpeningDuel(AnalyticsModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    opening_killer_player_id: UUID
    opening_victim_player_id: UUID
    killer_team_id: UUID
    victim_team_id: UUID
    killer_side: Side
    victim_side: Side
    tick: int = Field(ge=0)
    relative_tick: int | None = Field(default=None, ge=0)
    event_id: UUID
    round_winner: Side | None = None
    opening_team_won_round: bool | None = None
    seconds_from_freeze_end: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class TradeEvent(AnalyticsModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    traded_kill_event_id: UUID
    original_kill_event_id: UUID
    trader_player_id: UUID
    traded_player_id: UUID
    traded_enemy_player_id: UUID
    tick_delta: int = Field(ge=0)
    seconds_delta: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    seconds_delta_status: TimeConversionStatus
    seconds_delta_source: str | None = None
    team_id: UUID
    side: Side


class DeathClassification(StrEnum):
    ENEMY = "enemy"
    TEAMKILL = "teamkill"
    SUICIDE = "suicide"
    WORLD = "world"
    INVALID = "invalid"
    REPEATED = "repeated"


class AdvantageState(StrEnum):
    T_ADVANTAGE = "t_advantage"
    EVEN = "even"
    CT_ADVANTAGE = "ct_advantage"


class ManAdvantageTransition(AnalyticsModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    event_id: UUID
    t_alive_before: int = Field(ge=0)
    t_alive_after: int = Field(ge=0)
    ct_alive_before: int = Field(ge=0)
    ct_alive_after: int = Field(ge=0)
    signed_advantage_before: int
    signed_advantage_after: int
    advantage_before: AdvantageState
    advantage_after: AdvantageState
    causing_killer_player_id: UUID | None = None
    causing_victim_player_id: UUID
    event_classification: DeathClassification


class TeamRoundAnalytics(AnalyticsModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    team_id: UUID
    opponent_team_id: UUID
    side: Side
    participant_count: int = Field(ge=0)
    lineup_valid: bool
    round_won: bool | None = None
    kills: int = Field(ge=0)
    deaths: int = Field(ge=0)
    assists: int = Field(ge=0)
    enemy_damage: int = Field(ge=0)
    opening_kill: bool
    opening_death: bool
    opening_kill_converted: bool | None = None
    recovered_after_opening_death: bool | None = None
    trade_opportunities: int | None = Field(default=None, ge=0)
    successful_trades: int | None = Field(default=None, ge=0)
    traded_deaths: int | None = Field(default=None, ge=0)
    untraded_deaths: int | None = Field(default=None, ge=0)
    gained_first_advantage: bool
    first_advantage_size: int = Field(ge=0)
    lost_first_advantage: bool
    converted_first_advantage: bool | None = None
    recovered_after_first_disadvantage: bool | None = None
    reached_plus_two: bool
    converted_plus_two: bool | None = None
    max_advantage: int = Field(ge=0)
    final_alive: int = Field(ge=0)
    plants: int = Field(ge=0)
    defuses: int = Field(ge=0)
    explosions: int = Field(ge=0)
    planted_round: bool
    post_plant_won: bool | None = None
    bomb_outcome_observed: bool


class TeamMatchAnalytics(AnalyticsModel):
    match_id: UUID
    team_id: UUID
    internal_name: str
    display_name: str | None = None
    rounds_played: int = Field(ge=0)
    round_wins: int | None = Field(default=None, ge=0)
    t_rounds: int = Field(ge=0)
    ct_rounds: int = Field(ge=0)
    t_round_wins: int | None = Field(default=None, ge=0)
    ct_round_wins: int | None = Field(default=None, ge=0)
    kills: int = Field(ge=0)
    deaths: int = Field(ge=0)
    assists: int = Field(ge=0)
    enemy_damage: int = Field(ge=0)
    adr: Ratio | None = None
    opening_kills: int = Field(ge=0)
    opening_deaths: int = Field(ge=0)
    opening_kill_conversions: int | None = Field(default=None, ge=0)
    opening_conversion_percentage: Percentage | None = None
    opening_death_recoveries: int | None = Field(default=None, ge=0)
    opening_death_recovery_percentage: Percentage | None = None
    trade_opportunities: int | None = Field(default=None, ge=0)
    successful_trades: int | None = Field(default=None, ge=0)
    trade_percentage: Percentage | None = None
    traded_deaths: int | None = Field(default=None, ge=0)
    untraded_deaths: int | None = Field(default=None, ge=0)
    first_advantage_rounds: int = Field(ge=0)
    first_advantage_conversions: int | None = Field(default=None, ge=0)
    first_advantage_conversion_percentage: Percentage | None = None
    first_disadvantage_rounds: int = Field(ge=0)
    first_disadvantage_recoveries: int | None = Field(default=None, ge=0)
    first_disadvantage_recovery_percentage: Percentage | None = None
    plus_two_rounds: int = Field(ge=0)
    plus_two_conversions: int | None = Field(default=None, ge=0)
    plus_two_conversion_percentage: Percentage | None = None
    plants: int = Field(ge=0)
    defuses: int = Field(ge=0)
    explosions: int = Field(ge=0)
    rounds_with_plant: int = Field(ge=0)
    rounds_with_defuse: int = Field(ge=0)
    rounds_with_explosion: int = Field(ge=0)
    post_plant_wins: int | None = Field(default=None, ge=0)
    post_plant_conversion_percentage: Percentage | None = None
    bomb_outcome_coverage_percentage: Percentage | None = None
    ct_defuse_success_percentage: Percentage | None = None


class AnalyticsValidationIssue(AnalyticsModel):
    code: str = Field(min_length=1)
    severity: ValidationSeverity
    is_fatal: bool = False
    entity_type: str = Field(min_length=1)
    entity_id: str | None = None
    message: str = Field(min_length=1)
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class AnalyticsSummary(AnalyticsModel):
    rounds: int = Field(ge=0)
    players: int = Field(ge=0)
    teams: int = Field(ge=0)
    valid_enemy_kills: int = Field(ge=0)
    excluded_teamkills: int = Field(ge=0)
    excluded_suicides: int = Field(ge=0)
    excluded_world_kills: int = Field(ge=0)
    opening_duels: int = Field(ge=0)
    trade_events: int = Field(ge=0)
    trade_window_mode: TradeWindowMode
    trade_window_requested_ticks: int | None = Field(default=None, gt=0)
    trade_window_requested_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    trade_window_resolved_ticks: int | None = Field(default=None, gt=0)
    trade_window_tickrate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    trade_window_tickrate_source: str | None = None
    trade_window_resolution_source: TradeWindowResolutionSource
    rounds_with_plant: int = Field(ge=0)
    winner_covered_rounds: int = Field(ge=0)


class MatchAnalytics(AnalyticsModel):
    analytics_schema_version: str = ANALYTICS_SCHEMA_VERSION
    analytics_rule_version: str = ANALYTICS_RULE_VERSION
    analytics_config_hash: Sha256
    analytics_fingerprint: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    config: AnalyticsConfig
    availability: AnalyticsAvailabilitySummary
    summary: AnalyticsSummary
    player_rounds: tuple[PlayerRoundAnalytics, ...]
    player_matches: tuple[PlayerMatchAnalytics, ...]
    team_rounds: tuple[TeamRoundAnalytics, ...]
    team_matches: tuple[TeamMatchAnalytics, ...]
    opening_duels: tuple[OpeningDuel, ...]
    trade_events: tuple[TradeEvent, ...]
    man_advantage_transitions: tuple[ManAdvantageTransition, ...]
    validation_issues: tuple[AnalyticsValidationIssue, ...]
    warnings: tuple[str, ...] = ()


class RoundAnalyticsView(AnalyticsModel):
    match_id: UUID
    round_number: int = Field(ge=1)
    player_rounds: tuple[PlayerRoundAnalytics, ...]
    team_rounds: tuple[TeamRoundAnalytics, ...]
    opening_duel: OpeningDuel | None = None
    trade_events: tuple[TradeEvent, ...]
    man_advantage_transitions: tuple[ManAdvantageTransition, ...]


class AnalyticsComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class AnalyticsComputeResult(AnalyticsModel):
    match_id: UUID
    dataset_fingerprint: Sha256
    analytics_fingerprint: Sha256
    status: AnalyticsComputeStatus
    row_counts: dict[str, int]
    config: AnalyticsConfig
    availability: AnalyticsAvailabilitySummary
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


class AnalyticsRunSummary(AnalyticsModel):
    analytics_schema_version: str
    analytics_rule_version: str
    analytics_config_hash: Sha256
    analytics_fingerprint: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    config: AnalyticsConfig
    availability: AnalyticsAvailabilitySummary
    summary: AnalyticsSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]


class AnalyticsSaveResult(AnalyticsModel):
    analytics_fingerprint: Sha256
    status: AnalyticsComputeStatus
    row_counts: dict[str, int]


class DeleteAnalyticsResult(AnalyticsModel):
    analytics_fingerprint: Sha256 | None = None
    deleted: bool
