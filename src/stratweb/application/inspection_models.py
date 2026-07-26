"""Versioned Pydantic contract for a safe local demo inspection."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue

INSPECTION_SCHEMA_VERSION = "1.1.0"


class InspectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InspectionStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class InspectedFile(InspectionModel):
    original_name: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ParserSummary(InspectionModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    available_game_events: tuple[str, ...]


class PlayerSummary(InspectionModel):
    name: str | None = None
    steam_id: str | None = None
    team: str | None = None


class TeamSummary(InspectionModel):
    name: str = Field(min_length=1)
    player_count: int = Field(ge=0)
    steam_ids: tuple[str, ...]


class MatchSummary(InspectionModel):
    map_name: str | None = None
    server_name: str | None = None
    client_name: str | None = None
    demo_type: str | None = None
    playback_ticks: int | None = Field(default=None, ge=0)
    playback_time: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    estimated_round_count: int | None = Field(default=None, ge=0)
    estimated_round_count_source: str | None = None
    round_count_candidates: dict[str, int]
    player_count: int = Field(ge=0)
    players: tuple[PlayerSummary, ...]
    teams: tuple[TeamSummary, ...]


class ColumnSummary(InspectionModel):
    name: str = Field(min_length=1)
    dtype: str = Field(min_length=1)


class EventSummary(InspectionModel):
    available: bool
    parsed: bool
    row_count: int = Field(ge=0)
    columns: tuple[str, ...]
    column_schema: tuple[ColumnSummary, ...]
    error: str | None = None


class CanonicalEventSummary(InspectionModel):
    """Deduplicated inspection summary for one canonical event family."""

    count: int = Field(ge=0)
    selected_source_event: str | None = None
    available_source_events: tuple[str, ...]
    source_row_counts: dict[str, int]


class DemoInspectionReport(InspectionModel):
    schema_version: str = INSPECTION_SCHEMA_VERSION
    status: InspectionStatus
    file: InspectedFile
    parser: ParserSummary
    header: dict[str, JsonValue]
    match: MatchSummary
    events: dict[str, EventSummary]
    canonical_events: dict[str, CanonicalEventSummary]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
