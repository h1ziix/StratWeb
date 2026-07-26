"""Typed contracts for user-confirmed cross-match opponent workspaces."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

OPPONENT_SCHEMA_VERSION = "1.0.0"
OPPONENT_IDENTITY_RULE_VERSION = "steam_id_else_match_occurrence_v1"
OPPONENT_OVERLAP_RULE_VERSION = "candidate_known_steam_ids_v1"


class OpponentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpponentSelectionSource(StrEnum):
    USER_CONFIRMED = "user_confirmed"


class RosterIdentityStatus(StrEnum):
    STEAM_ID = "steam_id"
    OCCURRENCE_ONLY = "occurrence_only"


class RosterRole(StrEnum):
    CORE = "core"
    PARTIAL = "partial"
    UNRESOLVED_IDENTITY = "unresolved_identity"


class OverlapStrength(StrEnum):
    UNSCORED = "unscored"
    STRONG = "strong"
    POSSIBLE = "possible"
    WEAK = "weak"


class OpponentProfile(OpponentModel):
    profile_id: UUID
    display_name: str = Field(min_length=1, max_length=100)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class OpponentMatchSelection(OpponentModel):
    profile_id: UUID
    match_id: UUID
    team_id: UUID
    selection_source: OpponentSelectionSource
    created_at: AwareDatetime


class OpponentProfileSummary(OpponentModel):
    profile: OpponentProfile
    match_count: int = Field(ge=0)
    identified_player_count: int = Field(ge=0)
    unresolved_occurrence_count: int = Field(ge=0)
    map_names: tuple[str, ...] = ()


class OpponentRosterMember(OpponentModel):
    identity_key: str = Field(min_length=1)
    identity_status: RosterIdentityStatus
    steam_id: str | None = None
    current_name: str = Field(min_length=1)
    known_names: tuple[str, ...] = Field(min_length=1)
    match_ids: tuple[UUID, ...] = Field(min_length=1)
    appearance_count: int = Field(ge=1)
    selected_match_count: int = Field(ge=1)
    role: RosterRole


class SelectedOpponentMatch(OpponentModel):
    selection: OpponentMatchSelection
    map_name: str
    source_name: str
    round_count: int = Field(ge=0)
    team_name: str
    player_names: tuple[str, ...]
    identified_player_count: int = Field(ge=0)
    unresolved_player_count: int = Field(ge=0)


class CandidateTeam(OpponentModel):
    team_id: UUID
    team_name: str
    player_names: tuple[str, ...]
    steam_ids: tuple[str, ...]
    missing_steam_id_count: int = Field(ge=0)
    shared_steam_ids: tuple[str, ...]
    shared_player_names: tuple[str, ...]
    overlap_numerator: int = Field(ge=0)
    overlap_denominator: int = Field(ge=0)
    overlap_frequency: float | None = Field(default=None, ge=0, le=1)
    strength: OverlapStrength


class CandidateMatch(OpponentModel):
    match_id: UUID
    map_name: str
    source_name: str
    round_count: int = Field(ge=0)
    teams: tuple[CandidateTeam, ...]


class OpponentWorkspace(OpponentModel):
    opponent_schema_version: str = OPPONENT_SCHEMA_VERSION
    identity_rule_version: str = OPPONENT_IDENTITY_RULE_VERSION
    overlap_rule_version: str = OPPONENT_OVERLAP_RULE_VERSION
    profile: OpponentProfile
    selected_matches: tuple[SelectedOpponentMatch, ...]
    roster: tuple[OpponentRosterMember, ...]
    candidates: tuple[CandidateMatch, ...]
    warnings: tuple[str, ...] = ()


__all__ = [
    "CandidateMatch",
    "CandidateTeam",
    "OPPONENT_IDENTITY_RULE_VERSION",
    "OPPONENT_OVERLAP_RULE_VERSION",
    "OPPONENT_SCHEMA_VERSION",
    "OpponentMatchSelection",
    "OpponentProfile",
    "OpponentProfileSummary",
    "OpponentSelectionSource",
    "OpponentWorkspace",
    "OverlapStrength",
    "RosterIdentityStatus",
    "RosterRole",
    "SelectedOpponentMatch",
]
