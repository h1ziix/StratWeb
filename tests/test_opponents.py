from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pytest
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
)
from stratweb.application.canonical_models import (
    CanonicalMatchDataset,
    CanonicalPlayer,
    PlayerTeamMembership,
)
from stratweb.application.opponent_models import (
    OpponentSelectionSource,
    OverlapStrength,
    RosterIdentityStatus,
    RosterRole,
)
from stratweb.application.opponents import OpponentWorkspaceService
from stratweb.domain.enums import Side
from stratweb.exceptions import OpponentConflictError, OpponentSelectionError
from stratweb.main import create_app


def _expanded_team_dataset(
    dataset: CanonicalMatchDataset,
    *,
    alias_suffix: str,
    include_substitute: bool,
) -> CanonicalMatchDataset:
    match_id = dataset.match.match_id
    team = dataset.teams[0]
    additions = [
        CanonicalPlayer(
            player_id=uuid5(match_id, "opponent:shared-two"),
            steam_id="76561198000000003",
            current_name=f"SharedTwo{alias_suffix}",
            known_names=(f"SharedTwo{alias_suffix}",),
        ),
        CanonicalPlayer(
            player_id=uuid5(match_id, "opponent:shared-three"),
            steam_id="76561198000000004",
            current_name="SharedThree",
            known_names=("SharedThree",),
        ),
        CanonicalPlayer(
            player_id=uuid5(match_id, "opponent:unknown"),
            steam_id=None,
            current_name="SameNickname",
            known_names=("SameNickname",),
            warnings=("steam_id_missing",),
        ),
    ]
    if include_substitute:
        additions.append(
            CanonicalPlayer(
                player_id=uuid5(match_id, "opponent:substitute"),
                steam_id="76561198000000005",
                current_name="Substitute",
                known_names=("Substitute",),
            )
        )
    memberships = tuple(
        PlayerTeamMembership(
            player_id=player.player_id,
            team_id=team.team_id,
            side=Side.T,
            valid_from_tick=100,
            source="fixture:opponent",
            confidence=1,
        )
        for player in additions
    )
    expanded_team = team.model_copy(
        update={
            "starting_player_ids": (
                *team.starting_player_ids,
                *(player.player_id for player in additions),
            )
        }
    )
    return dataset.model_copy(
        update={
            "players": (*dataset.players, *additions),
            "teams": (expanded_team, dataset.teams[1]),
            "player_team_memberships": (*dataset.player_team_memberships, *memberships),
        }
    )


def _service(database: Path) -> OpponentWorkspaceService:
    return OpponentWorkspaceService(
        DuckDBOpponentRepository(database),
        DuckDBMatchRepository(database),
    )


def test_opponent_repository_profile_selection_round_trip(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    database = tmp_path / "opponents.duckdb"
    dataset = canonical_dataset_factory("opponent-repository")
    matches = DuckDBMatchRepository(database)
    matches.save_match(dataset)
    service = _service(database)
    profile = service.create_profile("Opponent One")

    selection = service.assign_match(
        profile.profile_id,
        dataset.match.match_id,
        dataset.teams[0].team_id,
    )

    repository = DuckDBOpponentRepository(database)
    persisted_profile = repository.get_profile(profile.profile_id)
    assert persisted_profile is not None
    assert persisted_profile.display_name == profile.display_name
    assert persisted_profile.updated_at >= profile.updated_at
    assert repository.list_selections(profile.profile_id) == (selection,)
    assert repository.remove_selection(profile.profile_id, dataset.match.match_id)
    assert repository.list_selections(profile.profile_id) == ()
    service.assign_match(profile.profile_id, dataset.match.match_id, dataset.teams[0].team_id)
    assert matches.delete_match(dataset.match.match_id)
    assert repository.list_selections(profile.profile_id) == ()
    assert repository.get_profile(profile.profile_id) is not None


def test_workspace_uses_steam_overlap_and_keeps_missing_ids_separate(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    database = tmp_path / "overlap.duckdb"
    first = _expanded_team_dataset(
        canonical_dataset_factory("opponent-overlap-one"),
        alias_suffix="Old",
        include_substitute=False,
    )
    second = _expanded_team_dataset(
        canonical_dataset_factory("opponent-overlap-two"),
        alias_suffix="New",
        include_substitute=True,
    )
    matches = DuckDBMatchRepository(database)
    matches.save_match(first, source_original_name="one.dem")
    matches.save_match(second, source_original_name="two.dem")
    service = _service(database)
    profile = service.create_profile("Evidence Team")

    empty = service.get_workspace(profile.profile_id)
    assert all(
        team.strength is OverlapStrength.UNSCORED
        for match in empty.candidates
        for team in match.teams
    )

    service.assign_match(profile.profile_id, first.match.match_id, first.teams[0].team_id)
    one_match = service.get_workspace(profile.profile_id)
    second_candidate = next(
        item for item in one_match.candidates if item.match_id == second.match.match_id
    )
    suggested = next(
        item for item in second_candidate.teams if item.team_id == second.teams[0].team_id
    )
    assert suggested.strength is OverlapStrength.STRONG
    assert suggested.overlap_numerator == 3
    assert suggested.overlap_denominator == 4
    assert suggested.overlap_frequency == 0.75

    service.assign_match(profile.profile_id, second.match.match_id, second.teams[0].team_id)
    combined = service.get_workspace(profile.profile_id)
    steam_members = {
        item.steam_id: item
        for item in combined.roster
        if item.identity_status is RosterIdentityStatus.STEAM_ID
    }
    occurrence_members = tuple(
        item
        for item in combined.roster
        if item.identity_status is RosterIdentityStatus.OCCURRENCE_ONLY
    )

    assert steam_members["76561198000000001"].role is RosterRole.CORE
    assert steam_members["76561198000000003"].role is RosterRole.CORE
    assert steam_members["76561198000000004"].role is RosterRole.CORE
    assert steam_members["76561198000000005"].role is RosterRole.PARTIAL
    assert steam_members["76561198000000003"].current_name == "SharedTwoNew"
    assert len(occurrence_members) == 2
    assert {item.current_name for item in occurrence_members} == {"SameNickname"}
    assert all(item.role is RosterRole.UNRESOLVED_IDENTITY for item in occurrence_members)
    assert any("were not merged by nickname" in warning for warning in combined.warnings)


def test_profile_validation_and_team_membership_are_explicit(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    database = tmp_path / "validation.duckdb"
    dataset = canonical_dataset_factory("opponent-validation")
    DuckDBMatchRepository(database).save_match(dataset)
    service = _service(database)
    profile = service.create_profile("Named Team")

    with pytest.raises(OpponentConflictError):
        service.create_profile("  named   team ")
    with pytest.raises(OpponentSelectionError):
        service.assign_match(profile.profile_id, dataset.match.match_id, UUID(int=0))


def test_opponent_ui_create_confirm_and_remove_flow(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    database = tmp_path / "opponent-ui.duckdb"
    dataset = canonical_dataset_factory("opponent-ui")
    DuckDBMatchRepository(database).save_match(dataset, source_original_name="faceit.dem")

    with TestClient(create_app(database)) as client:
        library = client.get("/ui/opponents")
        created = client.post(
            "/api/opponents",
            data={"display_name": "UI Opponent"},
            headers={"Accept": "application/json"},
        )
        profile_id = created.json()["profile_id"]
        assigned = client.post(
            f"/api/opponents/{profile_id}/matches",
            data={
                "match_id": str(dataset.match.match_id),
                "team_id": str(dataset.teams[0].team_id),
            },
            headers={"Accept": "application/json"},
        )
        workspace = client.get(f"/ui/opponents/{profile_id}")
        api_workspace = client.get(f"/api/opponents/{profile_id}")
        removed = client.post(
            f"/api/opponents/{profile_id}/matches/{dataset.match.match_id}/remove",
            headers={"Accept": "application/json"},
        )

    assert library.status_code == 200
    assert "Opponent workspaces" in library.text
    assert created.status_code == 201
    assert assigned.status_code == 200
    assert workspace.status_code == 200
    assert "UI Opponent" in workspace.text
    assert "faceit.dem" in workspace.text
    assert "Alpha" in workspace.text
    assert api_workspace.json()["selected_matches"][0]["selection"]["selection_source"] == (
        OpponentSelectionSource.USER_CONFIRMED.value
    )
    assert removed.status_code == 200
    assert removed.json()["removed"] is True


def test_opponent_mutations_reject_cross_site_origin(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "origin.duckdb")) as client:
        response = client.post(
            "/api/opponents",
            data={"display_name": "Injected profile"},
            headers={"Accept": "application/json", "Origin": "https://attacker.example"},
        )
        profiles = client.get("/api/opponents")

    assert response.status_code == 403
    assert profiles.json() == []
