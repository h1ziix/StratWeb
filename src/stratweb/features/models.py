"""Versioned contracts for deterministic per-round tactical facts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType

ROUND_FEATURE_SCHEMA_VERSION = "1.0.0"
ROUND_FEATURE_RULE_VERSION = "per_round_facts_v1"


class FeatureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FeatureAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class RoundFeatureType(StrEnum):
    STARTING_ZONE_DISTRIBUTION = "starting_zone_distribution"
    CHECKPOINT_ZONE_DISTRIBUTION = "checkpoint_zone_distribution"
    FIRST_CONTACT = "first_contact"
    OPENING_DUEL = "opening_duel"
    FIRST_UTILITY = "first_utility"
    EARLY_ZONE_PRESENCE = "early_zone_presence"
    BOMB_ROUTE = "bomb_route"
    BOMBSITE = "bombsite"
    PLANT_TIMING = "plant_timing"
    POST_PLANT_ROSTER = "post_plant_roster"
    FIRST_CT_ROTATION = "first_ct_rotation"
    LOST_MAN_ADVANTAGE = "lost_man_advantage"
    UNTRADED_DEATH = "untraded_death"
    RETAKE_ATTEMPT = "retake_attempt"
    SAVE_EXIT = "save_exit"


class FeatureComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class RoundFeatureConfig(FeatureModel):
    checkpoint_offsets_ticks: tuple[int, ...] = (640, 1280, 1920)
    early_window_ticks: int = Field(default=1280, ge=1)
    include_incomplete_rounds: bool = False

    @model_validator(mode="after")
    def validate_offsets(self) -> RoundFeatureConfig:
        if any(value <= 0 for value in self.checkpoint_offsets_ticks):
            raise ValueError("checkpoint offsets must be positive ticks")
        if tuple(sorted(set(self.checkpoint_offsets_ticks))) != self.checkpoint_offsets_ticks:
            raise ValueError("checkpoint offsets must be unique and strictly increasing")
        return self


class PlayerZoneEvidence(FeatureModel):
    player_id: UUID
    snapshot_id: UUID | None = None
    tick: int | None = Field(default=None, ge=0)
    zone_id: str | None = None
    zone_name: str | None = None
    status: str


class ZoneDistributionPayload(FeatureModel):
    kind: Literal["zone_distribution"] = "zone_distribution"
    checkpoint_label: str
    requested_tick: int = Field(ge=0)
    observed_tick: int = Field(ge=0)
    players: tuple[PlayerZoneEvidence, ...]


class ContactCandidate(FeatureModel):
    event_id: UUID
    event_kind: Literal["damage", "death"]
    tick: int = Field(ge=0)
    actor_player_id: UUID
    victim_player_id: UUID
    actor_team_id: UUID
    victim_team_id: UUID
    actor_side: Side
    victim_side: Side
    actor_zone_id: str | None = None
    actor_zone_name: str | None = None
    victim_zone_id: str | None = None
    victim_zone_name: str | None = None
    actor_snapshot_id: UUID | None = None
    victim_snapshot_id: UUID | None = None


class FirstContactPayload(FeatureModel):
    kind: Literal["first_contact"] = "first_contact"
    role: Literal["initiator", "receiver"]
    candidates: tuple[ContactCandidate, ...] = Field(min_length=1)


class OpeningDuelPayload(FeatureModel):
    kind: Literal["opening_duel"] = "opening_duel"
    role: Literal["winner", "loser"]
    killer_player_id: UUID
    victim_player_id: UUID
    event_id: UUID
    ordering_status: Literal["proven", "same_tick_ambiguous"]


class UtilityCandidate(FeatureModel):
    event_id: UUID
    tick: int = Field(ge=0)
    player_id: UUID
    grenade_type: str
    lifecycle_event: str
    zone_id: str | None = None
    zone_name: str | None = None


class FirstUtilityPayload(FeatureModel):
    kind: Literal["first_utility"] = "first_utility"
    candidates: tuple[UtilityCandidate, ...] = Field(min_length=1)


class EarlyZonePresencePayload(FeatureModel):
    kind: Literal["early_zone_presence"] = "early_zone_presence"
    first_observed_tick: int = Field(ge=0)
    player_ids: tuple[UUID, ...] = Field(min_length=1)


class BombRouteStop(FeatureModel):
    tick: int = Field(ge=0)
    zone_id: str
    zone_name: str
    carrier_player_id: UUID
    snapshot_id: UUID


class BombRoutePayload(FeatureModel):
    kind: Literal["bomb_route"] = "bomb_route"
    stops: tuple[BombRouteStop, ...] = Field(min_length=1)


class BombsitePayload(FeatureModel):
    kind: Literal["bombsite"] = "bombsite"
    site: Literal["A", "B"] | None = None
    plant_event_id: UUID
    planter_player_id: UUID | None = None
    resolution_source: str


class PlantTimingPayload(FeatureModel):
    kind: Literal["plant_timing"] = "plant_timing"
    plant_event_id: UUID
    planter_player_id: UUID | None = None
    relative_tick: int | None = Field(default=None, ge=0)
    seconds_from_freeze_end: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    seconds_source: str | None = None


class PostPlantRosterPayload(FeatureModel):
    kind: Literal["post_plant_roster"] = "post_plant_roster"
    alive_player_ids: tuple[UUID, ...]
    dead_player_ids: tuple[UUID, ...]
    unknown_player_ids: tuple[UUID, ...]


class LostAdvantagePayload(FeatureModel):
    kind: Literal["lost_man_advantage"] = "lost_man_advantage"
    event_id: UUID
    t_alive_before: int = Field(ge=0)
    t_alive_after: int = Field(ge=0)
    ct_alive_before: int = Field(ge=0)
    ct_alive_after: int = Field(ge=0)
    advantage_before: str
    advantage_after: str
    event_classification: str


class UntradedDeathPayload(FeatureModel):
    kind: Literal["untraded_death"] = "untraded_death"
    kill_event_id: UUID
    attacker_player_id: UUID
    victim_player_id: UUID
    trade_window_ticks: int = Field(ge=1)


class RetakeAttemptPayload(FeatureModel):
    kind: Literal["retake_attempt"] = "retake_attempt"
    attempted: bool
    site_zone_id: str
    entering_player_ids: tuple[UUID, ...]


class SaveExitPayload(FeatureModel):
    kind: Literal["save_exit"] = "save_exit"
    saved: bool
    surviving_player_ids: tuple[UUID, ...]


FeaturePayload = Annotated[
    ZoneDistributionPayload
    | FirstContactPayload
    | OpeningDuelPayload
    | FirstUtilityPayload
    | EarlyZonePresencePayload
    | BombRoutePayload
    | BombsitePayload
    | PlantTimingPayload
    | PostPlantRosterPayload
    | LostAdvantagePayload
    | UntradedDeathPayload
    | RetakeAttemptPayload
    | SaveExitPayload,
    Field(discriminator="kind"),
]


class RoundFeature(FeatureModel):
    feature_id: UUID
    feature_run_id: UUID
    feature_rule_version: str
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    team_id: UUID
    side: Side
    feature_type: RoundFeatureType
    availability: FeatureAvailability
    tick_start: int | None = Field(default=None, ge=0)
    tick_end: int | None = Field(default=None, ge=0)
    zone_id: str | None = None
    zone_name: str | None = None
    buy_type: BuyType | None = None
    payload: FeaturePayload | None = None
    evidence_event_ids: tuple[UUID, ...] = ()
    evidence_snapshot_ids: tuple[UUID, ...] = ()
    evidence_economy_snapshot_ids: tuple[UUID, ...] = ()
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_evidence(self) -> RoundFeature:
        if (
            self.availability
            in {
                FeatureAvailability.AVAILABLE,
                FeatureAvailability.PARTIAL,
            }
            and self.payload is None
        ):
            raise ValueError("available or partial feature requires typed payload")
        if (
            self.availability
            in {
                FeatureAvailability.UNAVAILABLE,
                FeatureAvailability.NOT_APPLICABLE,
            }
            and self.payload is not None
        ):
            raise ValueError("unavailable feature cannot expose a payload")
        if self.tick_start is not None and self.tick_end is not None:
            if self.tick_end < self.tick_start:
                raise ValueError("feature tick_end cannot precede tick_start")
        if (self.zone_id is None) != (self.zone_name is None):
            raise ValueError("zone id and name must be present together")
        return self


class FeatureTypeCapability(FeatureModel):
    population: int = Field(ge=0)
    available: int = Field(ge=0)
    partial: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    not_applicable: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> FeatureTypeCapability:
        total = self.available + self.partial + self.unavailable + self.not_applicable
        if total != self.population:
            raise ValueError("feature capability counts must equal population")
        return self


class RoundFeatureSummary(FeatureModel):
    eligible_rounds: int = Field(ge=0)
    excluded_rounds: int = Field(ge=0)
    features: int = Field(ge=0)
    available: int = Field(ge=0)
    partial: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    not_applicable: int = Field(ge=0)
    feature_type_counts: dict[RoundFeatureType, int]

    @model_validator(mode="after")
    def validate_counts(self) -> RoundFeatureSummary:
        total = self.available + self.partial + self.unavailable + self.not_applicable
        if total != self.features:
            raise ValueError("round feature summary statuses must equal features")
        return self


class RoundFeatureState(FeatureModel):
    feature_schema_version: str = ROUND_FEATURE_SCHEMA_VERSION
    feature_rule_version: str = ROUND_FEATURE_RULE_VERSION
    feature_run_id: UUID
    feature_fingerprint: Sha256
    feature_config_hash: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    analytics_fingerprint: Sha256
    analytics_rule_version: str
    temporal_run_id: UUID
    temporal_fingerprint: Sha256
    temporal_rule_version: str
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    spatial_rule_version: str
    zone_assignment_run_id: UUID
    zone_assignment_fingerprint: Sha256
    zone_assignment_rule_version: str
    economy_run_id: UUID | None = None
    economy_fingerprint: Sha256 | None = None
    economy_rule_version: str | None = None
    config: RoundFeatureConfig
    capabilities: dict[RoundFeatureType, FeatureTypeCapability]
    summary: RoundFeatureSummary
    features: tuple[RoundFeature, ...]
    warnings: tuple[str, ...] = ()


class RoundFeatureRunSummary(FeatureModel):
    feature_schema_version: str
    feature_rule_version: str
    feature_run_id: UUID
    feature_fingerprint: Sha256
    feature_config_hash: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    analytics_fingerprint: Sha256
    analytics_rule_version: str
    temporal_run_id: UUID
    temporal_fingerprint: Sha256
    temporal_rule_version: str
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    spatial_rule_version: str
    zone_assignment_run_id: UUID
    zone_assignment_fingerprint: Sha256
    zone_assignment_rule_version: str
    economy_run_id: UUID | None = None
    economy_fingerprint: Sha256 | None = None
    economy_rule_version: str | None = None
    config: RoundFeatureConfig
    capabilities: dict[RoundFeatureType, FeatureTypeCapability]
    summary: RoundFeatureSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...] = ()


class RoundFeatureRunRecord(FeatureModel):
    feature_run_id: UUID
    feature_fingerprint: Sha256
    match_id: UUID
    feature_schema_version: str
    feature_rule_version: str
    created_at: datetime
    compatible: bool
    selected_by_default: bool


class RoundFeatureSaveResult(FeatureModel):
    feature_run_id: UUID
    feature_fingerprint: Sha256
    status: FeatureComputeStatus
    row_counts: dict[str, int]


class RoundFeatureComputeResult(FeatureModel):
    feature_run_id: UUID
    feature_fingerprint: Sha256
    feature_schema_version: str
    feature_rule_version: str
    match_id: UUID
    status: FeatureComputeStatus
    summary: RoundFeatureSummary
    capabilities: dict[RoundFeatureType, FeatureTypeCapability]
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


class DeleteRoundFeaturesResult(FeatureModel):
    match_id: UUID
    deleted: bool
    deleted_runs: int = Field(ge=0)


__all__ = [
    "ROUND_FEATURE_RULE_VERSION",
    "ROUND_FEATURE_SCHEMA_VERSION",
    "DeleteRoundFeaturesResult",
    "FeatureAvailability",
    "FeatureComputeStatus",
    "FeaturePayload",
    "FeatureTypeCapability",
    "RoundFeature",
    "RoundFeatureComputeResult",
    "RoundFeatureConfig",
    "RoundFeatureRunRecord",
    "RoundFeatureRunSummary",
    "RoundFeatureSaveResult",
    "RoundFeatureState",
    "RoundFeatureSummary",
    "RoundFeatureType",
]
