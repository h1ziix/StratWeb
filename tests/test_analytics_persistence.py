from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from stratweb import cli
from stratweb.adapters.persistence import DuckDBAnalyticsRepository, DuckDBMatchRepository
from stratweb.adapters.persistence.migrations import MIGRATIONS
from stratweb.analytics.models import (
    AnalyticsComputeStatus,
    AnalyticsConfig,
    TimeConversionStatus,
    TradeWindowConfig,
    TradeWindowMode,
)
from stratweb.application.analytics import AnalyticsQueryService, ComputeMatchAnalyticsService


def test_analytics_repository_is_atomic_idempotent_queryable_and_separate(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("analytics-persistence")
    database = tmp_path / "analytics.duckdb"
    matches = DuckDBMatchRepository(database)
    analytics = DuckDBAnalyticsRepository(database)
    matches.save_match(dataset)
    service = ComputeMatchAnalyticsService(matches, analytics)

    computed = service.compute(
        dataset.match.match_id,
        config=AnalyticsConfig(trade_window=TradeWindowConfig.ticks(100)),
    )
    repeated = service.compute(
        dataset.match.match_id,
        config=AnalyticsConfig(trade_window=TradeWindowConfig.ticks(100)),
    )
    replaced = service.compute(
        dataset.match.match_id,
        config=AnalyticsConfig(trade_window=TradeWindowConfig.ticks(100)),
        replace=True,
    )

    assert computed.status is AnalyticsComputeStatus.COMPUTED
    assert repeated.status is AnalyticsComputeStatus.ALREADY_EXISTS
    assert replaced.status is AnalyticsComputeStatus.REPLACED
    assert len({computed.analytics_fingerprint, repeated.analytics_fingerprint}) == 1
    assert computed.row_counts == repeated.row_counts == replaced.row_counts

    reopened = AnalyticsQueryService(DuckDBAnalyticsRepository(database))
    summary = reopened.get_analytics_summary(dataset.match.match_id)
    players = reopened.list_player_stats(dataset.match.match_id)
    teams = reopened.list_team_stats(dataset.match.match_id)
    round_one = reopened.get_round_analytics(dataset.match.match_id, 1)
    assert summary.analytics_fingerprint == computed.analytics_fingerprint
    assert len(players) == 2
    assert len(teams) == 2
    assert len(round_one.player_rounds) == 2
    assert len(reopened.list_opening_duels(dataset.match.match_id)) == 1
    assert reopened.list_trade_events(dataset.match.match_id) == ()
    assert len(reopened.get_man_advantage_timeline(dataset.match.match_id, 1)) == 1

    deleted = reopened.delete_analytics(dataset.match.match_id)
    assert deleted.deleted is True
    assert deleted.analytics_fingerprint == computed.analytics_fingerprint
    assert matches.match_exists(dataset.match.match_id)
    assert DuckDBAnalyticsRepository(database).get_summary(dataset.match.match_id) is None


def test_analytics_cli_json_contract(
    tmp_path: Path, canonical_dataset_factory: Any, capsys: Any
) -> None:
    dataset = canonical_dataset_factory("analytics-cli")
    database = tmp_path / "analytics-cli.duckdb"
    DuckDBMatchRepository(database).save_match(dataset)
    match_id = str(dataset.match.match_id)

    compute = [
        "analytics",
        "compute",
        match_id,
        "--db",
        str(database),
    ]
    assert cli.main(compute) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "computed"
    assert first["config"]["trade_window"] == {
        "mode": "ticks",
        "requested_ticks": 320,
        "requested_seconds": None,
        "resolved_ticks": 320,
        "tickrate": None,
        "tickrate_source": None,
        "resolution_source": "explicit_ticks",
    }
    assert first["availability"]["trade_metrics"]["status"] == "available"
    assert cli.main(compute) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_exists"

    commands = (
        ("show",),
        ("players",),
        ("player", str(dataset.players[0].player_id)),
        ("teams",),
        ("round", "1"),
        ("openings",),
        ("trades", "--round", "1"),
        ("advantage", "1"),
    )
    for command in commands:
        args = ["analytics", command[0], match_id, *command[1:], "--db", str(database)]
        assert cli.main(args) == 0
        assert json.loads(capsys.readouterr().out) is not None

    assert cli.main(["analytics", "delete", match_id, "--yes", "--db", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] is True
    assert DuckDBMatchRepository(database).match_exists(dataset.match.match_id)


def test_migration_004_preserves_and_marks_legacy_ambiguous_runs(tmp_path: Path) -> None:
    database = tmp_path / "legacy-analytics.duckdb"
    assert DuckDBMatchRepository(database, migrations=MIGRATIONS[:3]).initialize() == (1, 2, 3)
    match_id = "00000000-0000-0000-0000-000000000501"
    fingerprint = "a" * 64
    capability = {
        "status": "available",
        "reasons": [],
        "population": 1,
        "covered": 1,
    }
    availability = {
        name: capability
        for name in (
            "combat_metrics",
            "opening_metrics",
            "trade_metrics",
            "win_conversion_metrics",
            "bomb_metrics",
            "score_metrics",
            "advantage_metrics",
        )
    }
    old_config = {
        "trade_window_seconds": 5.0,
        "trade_window_ticks": 320,
        "tickrate": None,
    }
    old_summary = {
        "rounds": 1,
        "players": 2,
        "teams": 2,
        "valid_enemy_kills": 2,
        "excluded_teamkills": 0,
        "excluded_suicides": 0,
        "excluded_world_kills": 0,
        "opening_duels": 1,
        "trade_events": 1,
        "trade_window_seconds": 5.0,
        "trade_window_ticks": 320,
        "rounds_with_plant": 0,
        "winner_covered_rounds": 1,
    }
    ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(502, 511)]
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO analytics_runs (
                analytics_fingerprint, match_id, dataset_fingerprint,
                analytics_schema_version, analytics_rule_version, analytics_config_hash,
                config, availability, summary, row_counts, warnings
            ) VALUES (?, ?, ?, '1.0.0', '1.0.0', ?, ?, ?, ?, '{}', '[]')
            """,
            [
                fingerprint,
                match_id,
                "b" * 64,
                "c" * 64,
                json.dumps(old_config),
                json.dumps(availability),
                json.dumps(old_summary),
            ],
        )
        connection.execute(
            """
            INSERT INTO trade_events VALUES (
                ?, ?, ?, 1, ?, ?, ?, ?, ?, 64, 1.0, ?, 'T'
            )
            """,
            [fingerprint, match_id, *ids[:7]],
        )

    repository = DuckDBAnalyticsRepository(database)
    assert repository.initialize() == (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)
    summary = repository.get_summary(UUID(match_id))

    assert summary is not None
    assert summary.config.trade_window.mode is TradeWindowMode.LEGACY_AMBIGUOUS
    assert summary.summary.trade_window_resolved_ticks is None
    assert summary.availability.trade_metrics.status.value == "partial"
    assert summary.availability.kast_metrics.trade_window_mode is TradeWindowMode.LEGACY_AMBIGUOUS
    trade = repository.list_trade_events(UUID(match_id))[0]
    assert trade.seconds_delta is None
    assert trade.seconds_delta_status is TimeConversionStatus.LEGACY_AMBIGUOUS
    assert trade.seconds_delta_source is None
    with duckdb.connect(str(database), read_only=True) as connection:
        run_row = connection.execute(
            "SELECT config, trade_window_mode FROM analytics_runs"
        ).fetchone()
        trade_row = connection.execute("SELECT seconds_delta FROM trade_events").fetchone()
    assert run_row is not None
    assert trade_row is not None
    persisted_config, mode = run_row
    persisted_seconds = trade_row[0]
    assert json.loads(persisted_config) == old_config
    assert mode == "legacy_ambiguous"
    assert persisted_seconds == 1.0
