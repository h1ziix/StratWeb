from __future__ import annotations

import os
from pathlib import Path

import pytest

from stratweb.adapters.parsers import Demoparser2Adapter
from stratweb.adapters.persistence import DuckDBAnalyticsRepository, DuckDBMatchRepository
from stratweb.analytics.definitions import (
    eligible_rounds,
    ordered_round_kills,
    participants_by_round,
)
from stratweb.analytics.models import (
    AnalyticsAvailability,
    AnalyticsComputeStatus,
    AnalyticsConfig,
    TradeWindowConfig,
)
from stratweb.application.analytics import AnalyticsQueryService, ComputeMatchAnalyticsService
from stratweb.application.canonicalization import CanonicalizationService
from stratweb.application.persistence import ImportCanonicalMatchService


@pytest.mark.integration
def test_faceit_gameplay_analytics_round_trip(tmp_path: Path) -> None:
    configured_path = os.environ.get("STRATWEB_TEST_DEMO")
    if not configured_path:
        pytest.skip("STRATWEB_TEST_DEMO is not set")

    dataset = CanonicalizationService(Demoparser2Adapter()).normalize(Path(configured_path))
    database = tmp_path / "faceit-analytics.duckdb"
    matches = DuckDBMatchRepository(database)
    analytics = DuckDBAnalyticsRepository(database)
    ImportCanonicalMatchService(matches).import_dataset(
        dataset, source_original_name=Path(configured_path).name
    )
    service = ComputeMatchAnalyticsService(matches, analytics)
    config = AnalyticsConfig(trade_window=TradeWindowConfig.ticks(320))

    computed = service.compute(dataset.match.match_id, config=config)
    repeated = service.compute(dataset.match.match_id, config=config)

    assert computed.status is AnalyticsComputeStatus.COMPUTED
    assert repeated.status is AnalyticsComputeStatus.ALREADY_EXISTS
    assert computed.analytics_fingerprint == repeated.analytics_fingerprint
    assert computed.row_counts == repeated.row_counts

    query = AnalyticsQueryService(DuckDBAnalyticsRepository(database))
    summary = query.get_analytics_summary(dataset.match.match_id)
    players = query.list_player_stats(dataset.match.match_id)
    teams = query.list_team_stats(dataset.match.match_id)
    round_one = query.get_round_analytics(dataset.match.match_id, 1)
    rounds = eligible_rounds(dataset.rounds)
    participants = participants_by_round(rounds, dataset.player_team_memberships)
    independently_classified = sum(
        sum(
            item.is_valid_enemy
            for item in ordered_round_kills(dataset.kills, round_item, round_participants)
        )
        for round_item, round_participants in zip(rounds, participants, strict=True)
    )

    assert summary.summary.rounds == len(rounds)
    assert summary.summary.players == 10
    assert len(players) == 10
    assert len(teams) == 2
    assert summary.summary.valid_enemy_kills == independently_classified
    assert sum(item.kills for item in players) == independently_classified
    assert summary.summary.opening_duels == len(query.list_opening_duels(dataset.match.match_id))
    assert summary.availability.win_conversion_metrics.status is AnalyticsAvailability.AVAILABLE
    assert summary.availability.score_metrics.status is AnalyticsAvailability.AVAILABLE
    assert len(round_one.player_rounds) == 10
    assert round_one.opening_duel is not None
    overtime = next((item for item in dataset.rounds if item.is_overtime), None)
    if overtime is not None:
        assert query.get_round_analytics(dataset.match.match_id, overtime.round_number)

    reopened = DuckDBAnalyticsRepository(database)
    assert reopened.get_summary(dataset.match.match_id) == summary
    assert query.delete_analytics(dataset.match.match_id).deleted is True
    assert matches.match_exists(dataset.match.match_id)
    assert reopened.get_summary(dataset.match.match_id) is None
