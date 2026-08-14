from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid5

import duckdb
import pytest

from stratweb import cli
from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBMatchRepository,
    DuckDBTemporalRepository,
)
from stratweb.adapters.persistence.migrations import MIGRATIONS
from stratweb.analytics.models import AnalyticsConfig, TradeWindowConfig
from stratweb.application.analytics import ComputeMatchAnalyticsService
from stratweb.application.canonical_models import EventPhase
from stratweb.application.canonicalization import compute_dataset_fingerprint
from stratweb.application.temporal import ComputeTemporalStateService, TemporalQueryService
from stratweb.exceptions import TemporalNotFoundError
from stratweb.temporal.models import (
    BombState,
    DeathEffectStatus,
    TemporalAvailabilityStatus,
    TemporalComputeStatus,
    TemporalConversionStatus,
)


def test_temporal_repository_is_atomic_idempotent_and_queryable(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("temporal-persistence")
    database = tmp_path / "temporal.duckdb"
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    matches.save_match(dataset)
    service = ComputeTemporalStateService(matches, temporal)

    computed = service.compute(dataset.match.match_id)
    repeated = service.compute(dataset.match.match_id)
    replaced = service.compute(dataset.match.match_id, replace=True)

    assert computed.status is TemporalComputeStatus.COMPUTED
    assert repeated.status is TemporalComputeStatus.ALREADY_EXISTS
    assert replaced.status is TemporalComputeStatus.REPLACED
    assert computed.temporal_fingerprint == repeated.temporal_fingerprint
    assert computed.row_counts == repeated.row_counts == replaced.row_counts

    query = TemporalQueryService(DuckDBTemporalRepository(database))
    summary = query.get_match_temporal_summary(dataset.match.match_id)
    timeline = query.get_round_timeline(dataset.match.match_id, 1)
    events = query.get_round_events(dataset.match.match_id, 1)
    transitions = query.get_round_transitions(dataset.match.match_id, 1)
    participants = query.get_round_participants(dataset.match.match_id, 1)
    bomb = query.get_bomb_timeline(dataset.match.match_id, 1)
    before = query.get_snapshot_before_event(dataset.match.match_id, dataset.kills[0].event_id)
    after = query.get_snapshot_after_event(dataset.match.match_id, dataset.kills[0].event_id)
    final = query.get_final_snapshot(dataset.match.match_id, 1)

    assert summary.temporal_fingerprint == computed.temporal_fingerprint
    assert timeline == DuckDBTemporalRepository(database).get_round_timeline(
        dataset.match.match_id, 1
    )
    assert events == timeline.ordered_events
    assert transitions == timeline.state_transitions
    assert participants == timeline.participants
    assert bomb == timeline.bomb_transitions
    assert before.time.conversion_status is TemporalConversionStatus.UNAVAILABLE
    assert dataset.kills[0].victim_player_id in before.alive_players
    assert dataset.kills[0].victim_player_id in after.dead_players
    assert final.bomb_state is BombState.ROUND_ENDED_BEFORE_RESOLUTION
    with pytest.raises(TemporalNotFoundError, match="Temporal round not found"):
        query.get_round_timeline(dataset.match.match_id, 999)

    deleted = query.delete_temporal(dataset.match.match_id)
    assert deleted.deleted is True
    assert matches.match_exists(dataset.match.match_id)
    assert DuckDBTemporalRepository(database).get_summary(dataset.match.match_id) is None


def test_temporal_compute_cross_checks_stage5_without_using_it_as_state_source(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("temporal-cross-check")
    pre_live = dataset.kills[0].model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:pre-live-cross-check"),
            "tick": 105,
            "phase": EventPhase.FREEZE_TIME,
            "is_suicide": True,
        }
    )
    provisional = dataset.model_copy(
        update={"dataset_fingerprint": "0" * 64, "kills": (pre_live, *dataset.kills)}
    )
    dataset = provisional.model_copy(
        update={"dataset_fingerprint": compute_dataset_fingerprint(provisional)}
    )
    database = tmp_path / "cross-check.duckdb"
    matches = DuckDBMatchRepository(database)
    analytics = DuckDBAnalyticsRepository(database)
    temporal = DuckDBTemporalRepository(database)
    matches.save_match(dataset)
    ComputeMatchAnalyticsService(matches, analytics).compute(
        dataset.match.match_id,
        config=AnalyticsConfig(trade_window=TradeWindowConfig.ticks(320)),
    )

    result = ComputeTemporalStateService(matches, temporal, analytics_repository=analytics).compute(
        dataset.match.match_id
    )

    assert result.status is TemporalComputeStatus.COMPUTED
    assert TemporalQueryService(temporal).delete_temporal(dataset.match.match_id).deleted is True
    assert matches.match_exists(dataset.match.match_id)
    assert analytics.get_summary(dataset.match.match_id) is not None


def test_stage5_cross_check_uses_post_group_not_arbitrary_intermediate_state(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("temporal-stage5-same-tick")
    original = dataset.kills[0]
    cross_kill = original.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:stage5-cross"),
            "attacker_player_id": original.victim_player_id,
            "victim_player_id": original.attacker_player_id,
            "attacker_team_id": original.victim_team_id,
            "victim_team_id": original.attacker_team_id,
        }
    )
    provisional = dataset.model_copy(
        update={"dataset_fingerprint": "0" * 64, "kills": (cross_kill, original)}
    )
    dataset = provisional.model_copy(
        update={"dataset_fingerprint": compute_dataset_fingerprint(provisional)}
    )
    database = tmp_path / "stage5-post-group.duckdb"
    matches = DuckDBMatchRepository(database)
    analytics = DuckDBAnalyticsRepository(database)
    temporal = DuckDBTemporalRepository(database)
    matches.save_match(dataset)
    ComputeMatchAnalyticsService(matches, analytics).compute(
        dataset.match.match_id,
        config=AnalyticsConfig(trade_window=TradeWindowConfig.ticks(320)),
    )

    result = ComputeTemporalStateService(matches, temporal, analytics_repository=analytics).compute(
        dataset.match.match_id
    )
    group = temporal.list_simultaneous_groups(dataset.match.match_id, 1)[0]
    opening = analytics.list_opening_duels(dataset.match.match_id)[0]

    assert result.status is TemporalComputeStatus.COMPUTED
    assert opening.event_id in group.ordered_event_ids
    assert group.post_group_snapshot_deterministic is True


def test_simultaneous_group_and_death_effect_status_round_trip(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("temporal-group-persistence")
    original = dataset.kills[0]
    second = original.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:group-persistence"),
            "attacker_player_id": original.victim_player_id,
            "victim_player_id": original.attacker_player_id,
            "attacker_team_id": original.victim_team_id,
            "victim_team_id": original.attacker_team_id,
        }
    )
    provisional = dataset.model_copy(
        update={"dataset_fingerprint": "0" * 64, "kills": (second, original)}
    )
    dataset = provisional.model_copy(
        update={"dataset_fingerprint": compute_dataset_fingerprint(provisional)}
    )
    database = tmp_path / "group-roundtrip.duckdb"
    matches = DuckDBMatchRepository(database)
    repository = DuckDBTemporalRepository(database)
    matches.save_match(dataset)
    ComputeTemporalStateService(matches, repository).compute(dataset.match.match_id)
    groups = repository.list_simultaneous_groups(dataset.match.match_id, 1)

    assert len(groups) == 1
    assert (
        repository.get_simultaneous_group(dataset.match.match_id, groups[0].group_id) == groups[0]
    )
    events = repository.list_round_events(dataset.match.match_id, 1)
    assert all(
        event.death_effect_status is DeathEffectStatus.APPLIED
        for event in events
        if event.event_type == "death"
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT death_effect_status FROM temporal_events "
            "WHERE event_type='death' ORDER BY event_id"
        ).fetchall() == [("applied",), ("applied",)]


def test_legacy_temporal_payload_defaults_do_not_claim_group_semantics(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("temporal-legacy-read")
    database = tmp_path / "legacy-read.duckdb"
    matches = DuckDBMatchRepository(database)
    matches.save_match(dataset)
    repository = DuckDBTemporalRepository(database)
    state = ComputeTemporalStateService(matches, repository)._engine.compute(  # noqa: SLF001
        ComputeTemporalStateService(matches, repository)._load_input(dataset.match.match_id)  # noqa: SLF001
    )
    summary = state.summary.model_dump(mode="json")
    for field in (
        "ambiguous_order_groups",
        "ambiguous_intermediate_groups",
        "ambiguous_final_groups",
        "conflicting_groups",
        "death_events_without_victim",
    ):
        summary.pop(field)
    for field in (
        "tick_group_state",
        "per_event_state",
        "intermediate_ordering",
        "final_alive_state",
    ):
        summary["availability"].pop(field)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO temporal_runs (
                temporal_run_id, temporal_fingerprint, match_id, dataset_fingerprint,
                temporal_schema_version, temporal_rule_version, temporal_config_hash,
                config, summary, row_counts, warnings
            ) VALUES (?, ?, ?, ?, '1.0.0', '1.0.0', ?, ?, ?, '{}', '[]')
            """,
            [
                state.temporal_run_id,
                "e" * 64,
                state.match_id,
                state.dataset_fingerprint,
                state.temporal_config_hash,
                json.dumps(state.config.model_dump(mode="json")),
                json.dumps(summary),
            ],
        )
    loaded = repository.get_summary(dataset.match.match_id)

    assert loaded is not None
    assert loaded.temporal_rule_version == "1.0.0"
    assert (
        loaded.summary.availability.tick_group_state.status
        is TemporalAvailabilityStatus.UNAVAILABLE
    )
    assert loaded.summary.availability.tick_group_state.reasons[0].value == "legacy_semantics"


def test_temporal_cli_json_contract(
    tmp_path: Path, canonical_dataset_factory: Any, capsys: Any
) -> None:
    dataset = canonical_dataset_factory("temporal-cli")
    database = tmp_path / "temporal-cli.duckdb"
    DuckDBMatchRepository(database).save_match(dataset)
    match_id = str(dataset.match.match_id)

    compute = ["temporal", "compute", match_id, "--db", str(database)]
    assert cli.main(compute) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "computed"
    assert first["config"] == {
        "tickrate": None,
        "tickrate_source": None,
        "conflicting_tickrate_sources": [],
    }
    assert first["capability_summary"]["seconds_timeline"]["status"] == "unavailable"
    assert cli.main(compute) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_exists"

    commands = (
        ("show",),
        ("round", "1"),
        ("events", "1"),
        ("transitions", "1"),
        ("participants", "1"),
        ("snapshot", "1", "--tick", "120"),
        ("before-event", str(dataset.kills[0].event_id)),
        ("after-event", str(dataset.kills[0].event_id)),
        ("final", "1"),
        ("bomb", "1"),
        ("groups",),
    )
    for command in commands:
        args = ["temporal", command[0], match_id, *command[1:], "--db", str(database)]
        assert cli.main(args) == 0
        assert json.loads(capsys.readouterr().out) is not None

    assert cli.main(["temporal", "delete", match_id, "--yes", "--db", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] is True
    assert DuckDBMatchRepository(database).match_exists(dataset.match.match_id)


def test_migration_005_preserves_canonical_and_analytics_rows(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("temporal-migration")
    database = tmp_path / "migration-005.duckdb"
    old = DuckDBMatchRepository(database, migrations=MIGRATIONS[:4])
    old.save_match(dataset)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO analytics_runs (
                analytics_fingerprint, match_id, dataset_fingerprint,
                analytics_schema_version, analytics_rule_version, analytics_config_hash,
                config, availability, summary, row_counts, warnings,
                trade_window_mode, trade_window_requested_ticks,
                trade_window_resolved_ticks, trade_window_resolution_source
            ) VALUES (?, ?, ?, '1.1.0', '1.1.0', ?, '{}', '{}', '{}', '{}', '[]',
                'ticks', 320, 320, 'explicit_ticks')
            """,
            ["a" * 64, dataset.match.match_id, dataset.dataset_fingerprint, "b" * 64],
        )

    assert DuckDBMatchRepository(database).initialize() == (
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        canonical_count = connection.execute("SELECT count(1) FROM matches").fetchone()
        analytics_count = connection.execute("SELECT count(1) FROM analytics_runs").fetchone()
        temporal_tables = connection.execute(
            "SELECT count(1) FROM information_schema.tables WHERE table_name='temporal_runs'"
        ).fetchone()
        group_tables = connection.execute(
            "SELECT count(1) FROM information_schema.tables "
            "WHERE table_name='temporal_simultaneous_groups'"
        ).fetchone()
    assert canonical_count == (1,)
    assert analytics_count == (1,)
    assert temporal_tables == (1,)
    assert group_tables == (1,)
