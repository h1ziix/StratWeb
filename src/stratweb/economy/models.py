"""Versioned contracts for freeze-end economy and equipment evidence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.domain.enums import Side

ECONOMY_SCHEMA_VERSION = "1.0.0"
ECONOMY_RULE_VERSION = "freeze_end_team_buy_v1"
ECONOMY_ITEM_CATEGORY_VERSION = "inventory_names_v1"
ECONOMY_VALUE_POLICY_VERSION = "demoparser2_current_equip_value_v1"


class EconomyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING_FROM_SOURCE = "missing_from_source"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


T = TypeVar("T")


class EvidenceValue(EconomyModel, Generic[T]):
    """One value together with its explicit provenance and coverage."""

    value: T | None = None
    availability: EvidenceAvailability
    source: str | None = None
    population: int = Field(default=1, ge=0)
    available_count: int = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_evidence(self) -> EvidenceValue[T]:
        if self.available_count > self.population:
            raise ValueError("available_count cannot exceed population")
        if self.availability is EvidenceAvailability.AVAILABLE:
            if self.value is None or not self.source or self.population == 0:
                raise ValueError("available evidence requires value, source and population")
            if self.available_count != self.population:
                raise ValueError("available evidence requires complete coverage")
        elif self.availability is EvidenceAvailability.PARTIAL:
            if self.value is None or not self.source:
                raise ValueError("partial evidence requires a known partial value and source")
            if not 0 < self.available_count < self.population:
                raise ValueError("partial evidence requires partial coverage")
        elif self.value is not None:
            raise ValueError("unavailable evidence cannot expose a value")
        return self


class BuyType(StrEnum):
    PISTOL = "pistol"
    ECO = "eco"
    FORCE = "force"
    SEMI = "semi"
    FULL = "full"
    UNKNOWN = "unknown"


class EconomyComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class EconomyConfig(EconomyModel):
    """Visible product policy; thresholds apply to a complete five-player team."""

    expected_team_size: int = Field(default=5, ge=1, le=10)
    full_min_equipment_value: int = Field(default=20_000, ge=0)
    eco_max_equipment_value: int = Field(default=7_500, ge=0)
    eco_max_cash_spent: int = Field(default=5_000, ge=0)
    force_min_cash_spent: int = Field(default=10_000, ge=0)
    exclude_warmup: bool = True
    exclude_incomplete_rounds: bool = True
    require_freeze_end_tick: bool = True
    require_complete_roster: bool = True
    require_complete_equipment_value: bool = True

    @model_validator(mode="after")
    def validate_thresholds(self) -> EconomyConfig:
        if self.eco_max_equipment_value >= self.full_min_equipment_value:
            raise ValueError("eco equipment ceiling must be below full-buy threshold")
        if self.eco_max_cash_spent >= self.force_min_cash_spent:
            raise ValueError("eco spend ceiling must be below force-buy threshold")
        return self


class EconomySourceSample(EconomyModel):
    tick: int = Field(ge=0)
    steam_id: str | None = None
    player_name: str | None = None
    current_equip_value: int | None = Field(default=None, ge=0)
    round_start_equip_value: int | None = Field(default=None, ge=0)
    cash_spent_this_round: int | None = Field(default=None, ge=0)
    balance: int | None = Field(default=None, ge=0)
    inventory: tuple[str, ...] | None = None
    inventory_item_ids: tuple[int, ...] | None = None
    armor_value: int | None = Field(default=None, ge=0)
    has_helmet: bool | None = None
    has_defuser: bool | None = None
    team_num: int | None = None
    total_rounds_played: int | None = Field(default=None, ge=0)
    invalid_fields: tuple[str, ...] = ()


class EconomyExtraction(EconomyModel):
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    source_demo_sha256: Sha256
    requested_ticks: tuple[int, ...]
    samples: tuple[EconomySourceSample, ...]
    requested_fields: tuple[str, ...]
    source_columns: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class PlayerEquipmentSnapshot(EconomyModel):
    player_snapshot_id: UUID
    economy_run_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    freeze_end_tick: int | None = Field(default=None, ge=0)
    participant_id: UUID
    steam_id: str | None = None
    player_name: str
    team_id: UUID | None = None
    team_source: str
    side: Side
    side_source: str
    source_team_number: EvidenceValue[int]
    equipment_value: EvidenceValue[int]
    round_start_equipment_value: EvidenceValue[int]
    cash_spent: EvidenceValue[int]
    balance: EvidenceValue[int]
    inventory: EvidenceValue[tuple[str, ...]]
    inventory_item_ids: EvidenceValue[tuple[int, ...]]
    weapons: EvidenceValue[tuple[str, ...]]
    utility: EvidenceValue[tuple[str, ...]]
    armor_value: EvidenceValue[int]
    has_helmet: EvidenceValue[bool]
    has_defuser: EvidenceValue[bool]
    total_rounds_played: EvidenceValue[int]
    eligible: bool
    exclusion_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class TeamEconomySnapshot(EconomyModel):
    team_snapshot_id: UUID
    economy_run_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    freeze_end_tick: int | None = Field(default=None, ge=0)
    team_id: UUID | None = None
    team_source: str
    side: Side
    side_source: str
    player_count: int = Field(ge=0)
    equipment_value: EvidenceValue[int]
    round_start_equipment_value: EvidenceValue[int]
    cash_spent: EvidenceValue[int]
    balance: EvidenceValue[int]
    weapons: EvidenceValue[tuple[str, ...]]
    utility: EvidenceValue[tuple[str, ...]]
    armor_value: EvidenceValue[int]
    helmet_count: EvidenceValue[int]
    defuse_kit_count: EvidenceValue[int]
    total_rounds_played: EvidenceValue[int]
    score_for_before: EvidenceValue[int]
    score_against_before: EvidenceValue[int]
    is_overtime: EvidenceValue[bool]
    buy_type: BuyType
    classification_availability: EvidenceAvailability
    classification_source: str | None = None
    eligible: bool
    exclusion_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_classification(self) -> TeamEconomySnapshot:
        if self.buy_type is BuyType.UNKNOWN:
            if self.classification_availability is EvidenceAvailability.AVAILABLE:
                raise ValueError("unknown buy cannot be marked available")
        elif (
            self.classification_availability is not EvidenceAvailability.AVAILABLE
            or not self.classification_source
            or not self.eligible
        ):
            raise ValueError("classified buy requires eligible, available provenance")
        return self


class EconomyCapability(EconomyModel):
    team_rounds: int = Field(ge=0)
    eligible_team_rounds: int = Field(ge=0)
    classified_team_rounds: int = Field(ge=0)
    unknown_team_rounds: int = Field(ge=0)
    excluded_team_rounds: int = Field(ge=0)
    coverage: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> EconomyCapability:
        if self.classified_team_rounds + self.unknown_team_rounds != self.team_rounds:
            raise ValueError("economy capability counts must equal team_rounds")
        if self.excluded_team_rounds > self.unknown_team_rounds:
            raise ValueError("excluded team rounds must be unknown")
        if self.classified_team_rounds > self.eligible_team_rounds:
            raise ValueError("classified team rounds cannot exceed eligible team rounds")
        expected = (
            self.classified_team_rounds / self.eligible_team_rounds
            if self.eligible_team_rounds
            else None
        )
        if expected is None and self.coverage is not None:
            raise ValueError("coverage is unavailable without eligible team rounds")
        if expected is not None and (
            self.coverage is None or abs(self.coverage - expected) > 1e-12
        ):
            raise ValueError("coverage must equal classified / eligible")
        return self


class EconomySummary(EconomyModel):
    rounds: int = Field(ge=0)
    player_snapshots: int = Field(ge=0)
    team_snapshots: int = Field(ge=0)
    buy_type_counts: dict[BuyType, int]
    side_buy_type_counts: dict[str, int]


class EconomyState(EconomyModel):
    economy_schema_version: str = ECONOMY_SCHEMA_VERSION
    economy_rule_version: str = ECONOMY_RULE_VERSION
    item_category_version: str = ECONOMY_ITEM_CATEGORY_VERSION
    value_policy_version: str = ECONOMY_VALUE_POLICY_VERSION
    economy_run_id: UUID
    economy_fingerprint: Sha256
    economy_config_hash: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    source_demo_sha256: Sha256
    parser_name: str
    parser_version: str
    config: EconomyConfig
    capability: EconomyCapability
    summary: EconomySummary
    source_columns: tuple[str, ...]
    player_snapshots: tuple[PlayerEquipmentSnapshot, ...]
    team_snapshots: tuple[TeamEconomySnapshot, ...]
    warnings: tuple[str, ...] = ()


class EconomyRunSummary(EconomyModel):
    economy_run_id: UUID
    economy_fingerprint: Sha256
    economy_schema_version: str
    economy_rule_version: str
    item_category_version: str
    value_policy_version: str
    economy_config_hash: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    source_demo_sha256: Sha256
    parser_name: str
    parser_version: str
    config: EconomyConfig
    capability: EconomyCapability
    summary: EconomySummary
    source_columns: tuple[str, ...]
    row_counts: dict[str, int]
    warnings: tuple[str, ...]


class EconomyRunRecord(EconomyModel):
    economy_run_id: UUID
    economy_fingerprint: Sha256
    match_id: UUID
    economy_schema_version: str
    economy_rule_version: str
    parser_name: str
    parser_version: str
    created_at: datetime
    compatible: bool
    selected_by_default: bool


class EconomySaveResult(EconomyModel):
    economy_run_id: UUID
    economy_fingerprint: Sha256
    status: EconomyComputeStatus
    row_counts: dict[str, int]


class EconomyComputeResult(EconomyModel):
    economy_run_id: UUID
    economy_fingerprint: Sha256
    economy_schema_version: str
    economy_rule_version: str
    match_id: UUID
    status: EconomyComputeStatus
    capability: EconomyCapability
    summary: EconomySummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    database_path: Path


class DeleteEconomyResult(EconomyModel):
    match_id: UUID
    deleted: bool
    deleted_runs: int = Field(ge=0)


__all__ = [
    "ECONOMY_ITEM_CATEGORY_VERSION",
    "ECONOMY_RULE_VERSION",
    "ECONOMY_SCHEMA_VERSION",
    "ECONOMY_VALUE_POLICY_VERSION",
    "BuyType",
    "DeleteEconomyResult",
    "EconomyCapability",
    "EconomyComputeResult",
    "EconomyComputeStatus",
    "EconomyConfig",
    "EconomyExtraction",
    "EconomyRunRecord",
    "EconomyRunSummary",
    "EconomySaveResult",
    "EconomySourceSample",
    "EconomyState",
    "EconomySummary",
    "EvidenceAvailability",
    "EvidenceValue",
    "PlayerEquipmentSnapshot",
    "TeamEconomySnapshot",
]
