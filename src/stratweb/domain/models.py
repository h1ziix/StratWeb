"""Parser-independent canonical entities for ingestion, analysis and reporting.

The models describe semantic contracts. DuckDB adapters may flatten nested values
such as coordinates, but parser-specific column names must not leak into this module.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from stratweb.domain.enums import BombAction, DemoStatus, GrenadeAction, Side
from stratweb.findings.models import AnalysisFinding, AnalysisRun, EvidenceReference

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SteamId = Annotated[str, Field(pattern=r"^[0-9]+$", min_length=1, max_length=32)]
Coordinate = Annotated[float, Field(allow_inf_nan=False)]


class DomainModel(BaseModel):
    """Base class that rejects accidental schema drift."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DemoFile(DomainModel):
    id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    internal_filename: str = Field(pattern=r"^[0-9a-f]{32}\.dem$")
    storage_key: str = Field(min_length=1)
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    status: DemoStatus = DemoStatus.UPLOADED
    parser_name: str | None = None
    parser_version: str | None = None
    parse_attempts: int = Field(default=0, ge=0)
    parse_error_code: str | None = None
    parse_error_message: str | None = None
    created_at: AwareDatetime
    parsed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> DemoFile:
        if self.status in {DemoStatus.PARSING, DemoStatus.PARSED}:
            if not self.parser_name or not self.parser_version:
                raise ValueError("parser_name and parser_version are required once parsing starts")
        if self.status is DemoStatus.PARSED and self.parsed_at is None:
            raise ValueError("parsed_at is required for parsed demos")
        if self.status is DemoStatus.FAILED:
            if not self.parse_error_code or not self.parse_error_message:
                raise ValueError("failed demos require a stable error code and message")
        return self


class Match(DomainModel):
    id: UUID
    demo_file_id: UUID
    map_name: str = Field(min_length=1)
    server_name: str | None = None
    tick_rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    is_complete: bool
    exclusion_reason: str | None = None
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    normalized_schema_version: str = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_completeness(self) -> Match:
        if not self.is_complete and not self.exclusion_reason:
            raise ValueError("incomplete matches require exclusion_reason")
        return self


class Team(DomainModel):
    """A team appearance inside one match; cross-match identity is resolved separately."""

    id: UUID
    match_id: UUID
    name: str = Field(min_length=1)
    external_team_id: str | None = None
    source_slot: int | None = Field(default=None, ge=0)


class Player(DomainModel):
    """A player appearance inside one match; Steam ID is optional for bots/unknowns."""

    id: UUID
    match_id: UUID
    team_id: UUID | None = None
    steam_id: SteamId | None = None
    name: str = Field(min_length=1)
    is_bot: bool = False


class Round(DomainModel):
    id: UUID
    match_id: UUID
    round_number: int = Field(ge=1)
    start_tick: int = Field(ge=0)
    freeze_end_tick: int | None = Field(default=None, ge=0)
    end_tick: int | None = Field(default=None, ge=0)
    official_end_tick: int | None = Field(default=None, ge=0)
    t_team_id: UUID | None = None
    ct_team_id: UUID | None = None
    winner_team_id: UUID | None = None
    winner_side: Side = Side.UNKNOWN
    end_reason: str | None = None
    is_warmup: bool = False
    is_complete: bool = False
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def validate_boundaries(self) -> Round:
        ordered_ticks = [
            tick
            for tick in (
                self.start_tick,
                self.freeze_end_tick,
                self.end_tick,
                self.official_end_tick,
            )
            if tick is not None
        ]
        if ordered_ticks != sorted(ordered_ticks):
            raise ValueError("round tick boundaries must be monotonically increasing")
        if self.is_complete and self.end_tick is None:
            raise ValueError("complete rounds require end_tick")
        if (self.is_warmup or not self.is_complete) and not self.exclusion_reason:
            raise ValueError("warmup and incomplete rounds require exclusion_reason")
        return self


class PlayerRound(DomainModel):
    id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    player_id: UUID
    player_steam_id: SteamId | None = None
    team_id: UUID | None = None
    side: Side
    start_equipment_value: int | None = Field(default=None, ge=0)
    equipment_value_freeze_end: int | None = Field(default=None, ge=0)
    money_spent: int | None = Field(default=None, ge=0)
    kills: int = Field(default=0, ge=0)
    deaths: int = Field(default=0, ge=0)
    assists: int = Field(default=0, ge=0)
    damage: int = Field(default=0, ge=0)
    survived: bool | None = None
    traded: bool | None = None


class GameEvent(DomainModel):
    """Fields common to canonical event rows.

    ``player_steam_id``, ``team_id``, ``team_name`` and ``side`` describe the
    primary actor (attacker, shooter, thrower, bomb actor or sampled player).
    """

    id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    game_time: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    player_steam_id: SteamId | None = None
    team_id: UUID | None = None
    team_name: str | None = None
    side: Side = Side.UNKNOWN
    x: Coordinate | None = None
    y: Coordinate | None = None
    z: Coordinate | None = None


class Kill(GameEvent):
    victim_steam_id: SteamId | None = None
    victim_team_id: UUID | None = None
    victim_side: Side = Side.UNKNOWN
    assister_steam_id: SteamId | None = None
    weapon: str | None = None
    is_headshot: bool | None = None
    is_wallbang: bool | None = None
    penetrated_objects: int | None = Field(default=None, ge=0)
    victim_x: Coordinate | None = None
    victim_y: Coordinate | None = None
    victim_z: Coordinate | None = None


class Damage(GameEvent):
    victim_steam_id: SteamId | None = None
    victim_team_id: UUID | None = None
    victim_side: Side = Side.UNKNOWN
    weapon: str | None = None
    hitgroup: str | None = None
    health_damage: int = Field(ge=0)
    armor_damage: int | None = Field(default=None, ge=0)
    victim_health_after: int | None = Field(default=None, ge=0)
    victim_x: Coordinate | None = None
    victim_y: Coordinate | None = None
    victim_z: Coordinate | None = None


class Shot(GameEvent):
    weapon: str | None = None
    weapon_id: int | None = Field(default=None, ge=0)
    is_primary_fire: bool | None = None


class Grenade(GameEvent):
    grenade_type: str = Field(min_length=1)
    action: GrenadeAction | None = None
    grenade_entity_id: int | None = Field(default=None, ge=0)
    is_trajectory_sample: bool = False


class Smoke(GameEvent):
    grenade_entity_id: int | None = Field(default=None, ge=0)
    end_tick: int | None = Field(default=None, ge=0)


class Inferno(GameEvent):
    grenade_entity_id: int | None = Field(default=None, ge=0)
    end_tick: int | None = Field(default=None, ge=0)


class BombEvent(GameEvent):
    action: BombAction
    bombsite: str | None = None


class PositionSample(GameEvent):
    pitch: float | None = Field(default=None, allow_inf_nan=False)
    yaw: float | None = Field(default=None, allow_inf_nan=False)
    velocity_x: float | None = Field(default=None, allow_inf_nan=False)
    velocity_y: float | None = Field(default=None, allow_inf_nan=False)
    velocity_z: float | None = Field(default=None, allow_inf_nan=False)
    is_alive: bool | None = None


__all__ = [
    "AnalysisFinding",
    "AnalysisRun",
    "BombEvent",
    "Damage",
    "DemoFile",
    "EvidenceReference",
    "Grenade",
    "Inferno",
    "Kill",
    "Match",
    "Player",
    "PlayerRound",
    "PositionSample",
    "Round",
    "Shot",
    "Smoke",
    "Team",
]
