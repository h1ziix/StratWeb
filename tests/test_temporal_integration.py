from __future__ import annotations

import os
from pathlib import Path

import pytest

from stratweb.adapters.parsers import Demoparser2Adapter
from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBMatchRepository,
    DuckDBTemporalRepository,
)
from stratweb.analytics.models import AnalyticsConfig, TradeWindowConfig
from stratweb.application.analytics import ComputeMatchAnalyticsService
from stratweb.application.canonicalization import CanonicalizationService
from stratweb.application.persistence import ImportCanonicalMatchService
from stratweb.application.temporal import ComputeTemporalStateService, TemporalQueryService
from stratweb.temporal.models import (
    TemporalAvailabilityStatus,
    TemporalComputeStatus,
    TemporalConversionStatus,
    TemporalDeathClassification,
)
from stratweb.temporal.ordering import temporal_event_key


@pytest.mark.integration
def test_faceit_temporal_round_trip(tmp_path: Path) -> None:
    configured_path = os.environ.get("STRATWEB_TEST_DEMO")
    if not configured_path:
        pytest.skip("STRATWEB_TEST_DEMO is not set")

    demo = Path(configured_path)
    dataset = CanonicalizationService(Demoparser2Adapter()).normalize(demo)
    database = tmp_path / "faceit-temporal.duckdb"
    matches = DuckDBMatchRepository(database)
    analytics = DuckDBAnalyticsRepository(database)
    temporal = DuckDBTemporalRepository(database)
    ImportCanonicalMatchService(matches).import_dataset(dataset, source_original_name=demo.name)
    ComputeMatchAnalyticsService(matches, analytics).compute(
        dataset.match.match_id,
        config=AnalyticsConfig(trade_window=TradeWindowConfig.ticks(320)),
    )
    service = ComputeTemporalStateService(matches, temporal, analytics_repository=analytics)

    computed = service.compute(dataset.match.match_id)
    repeated = service.compute(dataset.match.match_id)

    assert computed.status is TemporalComputeStatus.COMPUTED
    assert repeated.status is TemporalComputeStatus.ALREADY_EXISTS
    assert computed.temporal_fingerprint == repeated.temporal_fingerprint
    assert computed.row_counts == repeated.row_counts
    assert computed.row_counts["round_timelines"] == len(dataset.rounds)
    assert (
        computed.capability_summary.seconds_timeline.status
        is TemporalAvailabilityStatus.UNAVAILABLE
    )

    query = TemporalQueryService(DuckDBTemporalRepository(database))
    summary = query.get_match_temporal_summary(dataset.match.match_id)
    round_one = query.get_round_timeline(dataset.match.match_id, 1)
    last_round_number = max(item.round_number for item in dataset.rounds)
    last_round = query.get_round_timeline(dataset.match.match_id, last_round_number)
    round_one_events = query.get_round_events(dataset.match.match_id, 1)
    final_one = query.get_final_snapshot(dataset.match.match_id, 1)
    final_last = query.get_final_snapshot(dataset.match.match_id, last_round_number)
    opening = next(
        item
        for item in round_one.life_transitions
        if item.death_classification is TemporalDeathClassification.ENEMY
    )
    stage5_opening = next(
        item
        for item in analytics.list_opening_duels(dataset.match.match_id)
        if item.round_number == 1
    )
    stage5_advantage = analytics.get_man_advantage_timeline(dataset.match.match_id, 1)

    assert summary.summary.rounds == len(dataset.rounds)
    assert round_one_events == tuple(sorted(round_one_events, key=temporal_event_key))
    assert opening.event_id == stage5_opening.event_id
    if not any(
        item.time.tick < (round_one.live_start_tick or 0) for item in round_one.life_transitions
    ):
        assert final_one.t_alive == stage5_advantage[-1].t_alive_after
        assert final_one.ct_alive == stage5_advantage[-1].ct_alive_after
    assert final_last.time.tick == last_round.effective_end_tick
    assert final_last.time.conversion_status is TemporalConversionStatus.UNAVAILABLE
    assert summary.summary.availability.bomb_state.status in {
        TemporalAvailabilityStatus.PARTIAL,
        TemporalAvailabilityStatus.UNAVAILABLE,
    }

    reopened = DuckDBTemporalRepository(database)
    assert reopened.get_summary(dataset.match.match_id) == summary
    assert query.delete_temporal(dataset.match.match_id).deleted is True
    assert matches.match_exists(dataset.match.match_id)
    assert analytics.get_summary(dataset.match.match_id) is not None
    assert reopened.get_summary(dataset.match.match_id) is None
