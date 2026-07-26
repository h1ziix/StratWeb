from __future__ import annotations

import os
from pathlib import Path

import pytest

from stratweb.adapters.parsers import Demoparser2Adapter
from stratweb.adapters.persistence import DuckDBMatchRepository
from stratweb.application.canonical_models import (
    CapabilityCoverageStatus,
    DataAvailability,
    RoundOutcomeStatus,
)
from stratweb.application.canonicalization import CanonicalizationService
from stratweb.application.persistence import ImportCanonicalMatchService, MatchQueryService
from stratweb.application.persistence_models import ImportStatus


@pytest.mark.integration
def test_faceit_fixture_round_trip_through_temporary_duckdb(tmp_path: Path) -> None:
    configured_path = os.environ.get("STRATWEB_TEST_DEMO")
    if not configured_path:
        pytest.skip("STRATWEB_TEST_DEMO is not set")

    dataset = CanonicalizationService(Demoparser2Adapter()).normalize(Path(configured_path))
    repository = DuckDBMatchRepository(tmp_path / "faceit.duckdb")
    importer = ImportCanonicalMatchService(repository)

    imported = importer.import_dataset(
        dataset,
        source_original_name=Path(configured_path).name,
    )
    repeated = importer.import_dataset(dataset)
    query = MatchQueryService(repository)
    summary = query.get_summary(dataset.match.match_id)
    rounds = query.get_rounds(dataset.match.match_id)
    round_one = query.get_round_events(dataset.match.match_id, 1)

    assert imported.status is ImportStatus.IMPORTED
    assert repeated.status is ImportStatus.ALREADY_EXISTS
    assert summary.match.map_name == dataset.match.map_name
    assert summary.round_outcome.status is CapabilityCoverageStatus.AVAILABLE
    assert summary.round_outcome.available_rounds == len(dataset.rounds)
    assert summary.round_outcome.can_compute_win_metrics is True
    assert all(item.outcome_status is RoundOutcomeStatus.SOURCE_EVENT for item in rounds)
    assert all(item.winner_side is not None for item in rounds)
    assert all(item.score_status is DataAvailability.AVAILABLE for item in rounds)
    assert all(item.end_reason_status is DataAvailability.AVAILABLE for item in rounds)
    assert dataset.validation_report.has_fatal_errors is False
    assert summary.row_counts == {
        "matches": 1,
        "teams": len(dataset.teams),
        "players": len(dataset.players),
        "memberships": len(dataset.player_team_memberships),
        "rounds": len(dataset.rounds),
        "kills": len(dataset.kills),
        "damages": len(dataset.damages),
        "shots": len(dataset.shots),
        "grenades": len(dataset.grenades),
        "bomb_events": len(dataset.bomb_events),
        "validation_issues": len(dataset.validation_report.issues),
        "normalization_metadata": 1,
    }
    assert round_one.match_id == dataset.match.match_id
    assert round_one.kills

    assert query.delete_match(dataset.match.match_id) is True
    assert all(count == 0 for count in repository.get_table_counts(dataset.match.match_id).values())
