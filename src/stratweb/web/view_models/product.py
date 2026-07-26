"""Strict view contracts; no HTML is built in these models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ViewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HealthItemView(ViewModel):
    label: str
    status: str
    detail: str
    href: str | None = None


class TeamScoreView(ViewModel):
    team_id: UUID
    name: str
    score: int | None = Field(default=None, ge=0)


class MatchLibraryItemView(ViewModel):
    match_id: UUID
    short_id: str
    map_name: str
    source_name: str
    imported_at: datetime
    round_count: int = Field(ge=0)
    teams: tuple[TeamScoreView, ...]
    score_available: bool
    canonical_status: str
    analytics_status: str
    temporal_status: str
    spatial_status: str
    warning_count: int = Field(ge=0)


class RoundStripItemView(ViewModel):
    round_number: int = Field(ge=1)
    winner: str
    score: str
    complete: bool
    map_href: str | None = None
    timeline_href: str | None = None


class PlayerSummaryView(ViewModel):
    player_id: UUID
    name: str
    kills: int | None = Field(default=None, ge=0)
    deaths: int | None = Field(default=None, ge=0)
    assists: int | None = Field(default=None, ge=0)
    adr: float | None = Field(default=None, ge=0)


class MatchOverviewView(ViewModel):
    match: MatchLibraryItemView
    rounds: tuple[RoundStripItemView, ...]
    players: tuple[PlayerSummaryView, ...]
    health: tuple[HealthItemView, ...]
    opening_duels: int = Field(ge=0)
    trades: int = Field(ge=0)
    plants: int = Field(ge=0)
    defuses: int = Field(ge=0)
    developer_details: dict[str, str]
