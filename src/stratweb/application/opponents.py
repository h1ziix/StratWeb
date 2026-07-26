"""Deterministic opponent workspace composition over user-confirmed match teams."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from stratweb.application.canonical_models import CanonicalPlayer, CanonicalTeam
from stratweb.application.opponent_models import (
    CandidateMatch,
    CandidateTeam,
    OpponentMatchSelection,
    OpponentProfile,
    OpponentProfileSummary,
    OpponentRosterMember,
    OpponentSelectionSource,
    OpponentWorkspace,
    OverlapStrength,
    RosterIdentityStatus,
    RosterRole,
    SelectedOpponentMatch,
)
from stratweb.application.persistence_models import MatchQueryFilters, StoredMatch
from stratweb.exceptions import (
    MatchNotFoundError,
    OpponentConflictError,
    OpponentNotFoundError,
    OpponentSelectionError,
)
from stratweb.ports import MatchRepository, OpponentRepository


@dataclass(slots=True)
class _RosterAccumulator:
    identity_key: str
    identity_status: RosterIdentityStatus
    steam_id: str | None
    known_names: set[str] = field(default_factory=set)
    match_ids: set[UUID] = field(default_factory=set)
    latest_name_key: tuple[datetime, str] | None = None


class OpponentWorkspaceService:
    """Keep inferred overlap separate from explicit persisted team selection."""

    def __init__(self, opponents: OpponentRepository, matches: MatchRepository) -> None:
        self._opponents = opponents
        self._matches = matches

    def create_profile(self, display_name: str) -> OpponentProfile:
        normalized = " ".join(display_name.split())
        if not normalized:
            raise OpponentSelectionError("Opponent name cannot be empty.")
        if len(normalized) > 100:
            raise OpponentSelectionError("Opponent name cannot exceed 100 characters.")
        if any(
            profile.display_name.casefold() == normalized.casefold()
            for profile in self._opponents.list_profiles()
        ):
            raise OpponentConflictError(f"Opponent profile {normalized!r} already exists.")
        now = datetime.now(UTC)
        profile = OpponentProfile(
            profile_id=uuid4(),
            display_name=normalized,
            created_at=now,
            updated_at=now,
        )
        self._opponents.create_profile(profile)
        return profile

    def list_profiles(self) -> tuple[OpponentProfileSummary, ...]:
        result: list[OpponentProfileSummary] = []
        for profile in self._opponents.list_profiles():
            selections = self._opponents.list_selections(profile.profile_id)
            roster = self._roster(selections)
            maps = tuple(
                sorted(
                    {
                        stored.map_name or "Unknown map"
                        for selection in selections
                        if (stored := self._matches.get_match(selection.match_id)) is not None
                    }
                )
            )
            result.append(
                OpponentProfileSummary(
                    profile=profile,
                    match_count=len(selections),
                    identified_player_count=sum(
                        item.identity_status is RosterIdentityStatus.STEAM_ID for item in roster
                    ),
                    unresolved_occurrence_count=sum(
                        item.identity_status is RosterIdentityStatus.OCCURRENCE_ONLY
                        for item in roster
                    ),
                    map_names=maps,
                )
            )
        return tuple(result)

    def get_workspace(self, profile_id: UUID) -> OpponentWorkspace:
        profile = self._require_profile(profile_id)
        selections = self._opponents.list_selections(profile_id)
        roster = self._roster(selections)
        selected = tuple(self._selected_match(item) for item in selections)
        selected_ids = {item.match_id for item in selections}
        confirmed_steam_ids = {
            item.steam_id
            for item in roster
            if item.identity_status is RosterIdentityStatus.STEAM_ID
            and item.steam_id is not None
        }
        candidates = tuple(
            self._candidate_match(match, confirmed_steam_ids)
            for match in self._matches.list_matches(MatchQueryFilters(limit=10_000))
            if match.match_id not in selected_ids
        )
        warnings: list[str] = []
        if not selections:
            warnings.append(
                "No match team is confirmed. Roster overlap remains unscored until the first "
                "manual selection."
            )
        unresolved = sum(
            item.identity_status is RosterIdentityStatus.OCCURRENCE_ONLY for item in roster
        )
        if unresolved:
            warnings.append(
                f"{unresolved} player occurrence(s) have no Steam ID and were not merged by "
                "nickname."
            )
        return OpponentWorkspace(
            profile=profile,
            selected_matches=selected,
            roster=roster,
            candidates=candidates,
            warnings=tuple(warnings),
        )

    def assign_match(
        self,
        profile_id: UUID,
        match_id: UUID,
        team_id: UUID,
    ) -> OpponentMatchSelection:
        self._require_profile(profile_id)
        if self._matches.get_match(match_id) is None:
            raise MatchNotFoundError(f"Match not found: {match_id}")
        if team_id not in {team.team_id for team in self._matches.get_teams(match_id)}:
            raise OpponentSelectionError(
                "Selected physical team does not belong to the requested match."
            )
        selection = OpponentMatchSelection(
            profile_id=profile_id,
            match_id=match_id,
            team_id=team_id,
            selection_source=OpponentSelectionSource.USER_CONFIRMED,
            created_at=datetime.now(UTC),
        )
        self._opponents.save_selection(selection)
        return selection

    def remove_match(self, profile_id: UUID, match_id: UUID) -> bool:
        self._require_profile(profile_id)
        return self._opponents.remove_selection(profile_id, match_id)

    def _require_profile(self, profile_id: UUID) -> OpponentProfile:
        profile = self._opponents.get_profile(profile_id)
        if profile is None:
            raise OpponentNotFoundError(f"Opponent profile not found: {profile_id}")
        return profile

    def _roster(
        self, selections: tuple[OpponentMatchSelection, ...]
    ) -> tuple[OpponentRosterMember, ...]:
        accumulators: dict[str, _RosterAccumulator] = {}
        for selection in selections:
            stored = self._matches.get_match(selection.match_id)
            if stored is None:
                continue
            for player in self._team_players(selection.match_id, selection.team_id):
                if player.steam_id is not None:
                    identity_key = f"steam:{player.steam_id}"
                    status = RosterIdentityStatus.STEAM_ID
                else:
                    identity_key = f"occurrence:{selection.match_id}:{player.player_id}"
                    status = RosterIdentityStatus.OCCURRENCE_ONLY
                accumulator = accumulators.setdefault(
                    identity_key,
                    _RosterAccumulator(
                        identity_key=identity_key,
                        identity_status=status,
                        steam_id=player.steam_id,
                    ),
                )
                accumulator.match_ids.add(selection.match_id)
                accumulator.known_names.update(player.known_names)
                name_key = (selection.created_at, player.current_name)
                if accumulator.latest_name_key is None or name_key > accumulator.latest_name_key:
                    accumulator.latest_name_key = name_key
        selected_count = len(selections)
        result: list[OpponentRosterMember] = []
        for accumulator in accumulators.values():
            appearances = len(accumulator.match_ids)
            if accumulator.identity_status is RosterIdentityStatus.OCCURRENCE_ONLY:
                role = RosterRole.UNRESOLVED_IDENTITY
            elif appearances == selected_count:
                role = RosterRole.CORE
            else:
                role = RosterRole.PARTIAL
            current_name = (
                accumulator.latest_name_key[1]
                if accumulator.latest_name_key is not None
                else "Unknown player"
            )
            result.append(
                OpponentRosterMember(
                    identity_key=accumulator.identity_key,
                    identity_status=accumulator.identity_status,
                    steam_id=accumulator.steam_id,
                    current_name=current_name,
                    known_names=tuple(sorted(accumulator.known_names)) or (current_name,),
                    match_ids=tuple(sorted(accumulator.match_ids, key=str)),
                    appearance_count=appearances,
                    selected_match_count=selected_count,
                    role=role,
                )
            )
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.identity_status is RosterIdentityStatus.OCCURRENCE_ONLY,
                    -item.appearance_count,
                    item.current_name.casefold(),
                    item.identity_key,
                ),
            )
        )

    def _selected_match(self, selection: OpponentMatchSelection) -> SelectedOpponentMatch:
        stored = self._matches.get_match(selection.match_id)
        if stored is None:
            raise MatchNotFoundError(f"Match not found: {selection.match_id}")
        team = self._team(selection.match_id, selection.team_id)
        players = self._team_players(selection.match_id, selection.team_id)
        return SelectedOpponentMatch(
            selection=selection,
            map_name=stored.map_name or "Unknown map",
            source_name=stored.source_original_name or stored.server_name or "Completed demo",
            round_count=stored.round_count,
            team_name=_team_name(team),
            player_names=tuple(player.current_name for player in players),
            identified_player_count=sum(player.steam_id is not None for player in players),
            unresolved_player_count=sum(player.steam_id is None for player in players),
        )

    def _candidate_match(
        self,
        stored: StoredMatch,
        confirmed_steam_ids: set[str],
    ) -> CandidateMatch:
        return CandidateMatch(
            match_id=stored.match_id,
            map_name=stored.map_name or "Unknown map",
            source_name=stored.source_original_name or stored.server_name or "Completed demo",
            round_count=stored.round_count,
            teams=tuple(
                self._candidate_team(stored.match_id, team, confirmed_steam_ids)
                for team in self._matches.get_teams(stored.match_id)
            ),
        )

    def _candidate_team(
        self,
        match_id: UUID,
        team: CanonicalTeam,
        confirmed_steam_ids: set[str],
    ) -> CandidateTeam:
        players = self._team_players(match_id, team.team_id)
        steam_to_name = {
            player.steam_id: player.current_name
            for player in players
            if player.steam_id is not None
        }
        steam_ids = set(steam_to_name)
        shared = steam_ids & confirmed_steam_ids
        denominator = len(steam_ids)
        frequency = len(shared) / denominator if denominator else None
        if not confirmed_steam_ids:
            strength = OverlapStrength.UNSCORED
        elif len(shared) >= 3 and frequency is not None and frequency >= 0.6:
            strength = OverlapStrength.STRONG
        elif len(shared) >= 2:
            strength = OverlapStrength.POSSIBLE
        else:
            strength = OverlapStrength.WEAK
        return CandidateTeam(
            team_id=team.team_id,
            team_name=_team_name(team),
            player_names=tuple(player.current_name for player in players),
            steam_ids=tuple(sorted(steam_ids)),
            missing_steam_id_count=sum(player.steam_id is None for player in players),
            shared_steam_ids=tuple(sorted(shared)),
            shared_player_names=tuple(sorted(steam_to_name[item] for item in shared)),
            overlap_numerator=len(shared),
            overlap_denominator=denominator,
            overlap_frequency=frequency,
            strength=strength,
        )

    def _team_players(self, match_id: UUID, team_id: UUID) -> tuple[CanonicalPlayer, ...]:
        players = {player.player_id: player for player in self._matches.get_players(match_id)}
        team = self._team(match_id, team_id)
        player_ids = set(team.starting_player_ids)
        player_ids.update(
            membership.player_id
            for membership in self._matches.get_memberships(match_id)
            if membership.team_id == team_id
        )
        return tuple(
            sorted(
                (players[player_id] for player_id in player_ids if player_id in players),
                key=lambda player: (player.current_name.casefold(), str(player.player_id)),
            )
        )

    def _team(self, match_id: UUID, team_id: UUID) -> CanonicalTeam:
        for team in self._matches.get_teams(match_id):
            if team.team_id == team_id:
                return team
        raise OpponentSelectionError("Selected physical team is unavailable.")


def _team_name(team: CanonicalTeam) -> str:
    return team.display_name or team.internal_name


__all__ = ["OpponentWorkspaceService"]
