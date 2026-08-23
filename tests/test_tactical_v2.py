from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import duckdb
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
    DuckDBTacticalV2Repository,
)
from stratweb.adapters.persistence._tactical_v2_cascade import (
    delete_tactical_v2_for_matches,
)
from stratweb.application.opponent_models import (
    OpponentMatchSelection,
    OpponentProfile,
    OpponentSelectionSource,
)
from stratweb.domain.enums import Side
from stratweb.main import create_app
from stratweb.tactical_v2.engine import TacticalV2Engine
from stratweb.tactical_v2.models import (
    TacticalDamageSample,
    TacticalInsightType,
    TacticalKillSample,
    TacticalMatchInput,
    TacticalPlantSample,
    TacticalPlayerSample,
    TacticalRoundInput,
    TacticalSaveSignal,
    TacticalSourcePin,
    TacticalTradeSample,
    TacticalUtilitySample,
    TacticalV2Input,
)


def _id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"tactical-v2-test:{value}")


def _source() -> TacticalSourcePin:
    return TacticalSourcePin(
        match_id=_id("match"),
        team_id=_id("team"),
        map_name="de_mirage",
        dataset_fingerprint="a" * 64,
        analytics_fingerprint="b" * 64,
        analytics_rule_version="gameplay_analytics_v1",
        temporal_run_id=_id("temporal"),
        temporal_fingerprint="c" * 64,
        temporal_rule_version="temporal_round_state_v1.1",
        spatial_run_id=_id("spatial"),
        spatial_fingerprint="d" * 64,
        spatial_rule_version="1.3.0",
        zone_assignment_run_id=_id("zone"),
        zone_assignment_fingerprint="e" * 64,
        zone_assignment_rule_version="zone_assignment_v1",
        feature_run_id=_id("features"),
        feature_fingerprint="f" * 64,
        feature_rule_version="per_round_facts_v1",
    )


def _sample(
    round_number: int,
    player: str,
    tick: int,
    x: float,
    zone: str,
    side: Side,
) -> TacticalPlayerSample:
    return TacticalPlayerSample(
        snapshot_id=_id(f"snapshot:{round_number}:{player}:{tick}"),
        player_id=_id(player),
        tick=tick,
        x=x,
        y=float(round_number * 100),
        z=0.0,
        alive=True,
        side=side,
        zone_id=zone,
        zone_name=zone.title(),
    )


def _input() -> TacticalV2Input:
    source = _source()
    opening = _id("opening")
    trade_kill = _id("trade-kill")
    t_samples = tuple(
        _sample(1, player, tick, x, zone, Side.T)
        for tick, zone in ((1640, "spawn"), (2280, "mid"), (2920, "a_site"))
        for player, x in (("p1", 0.0), ("p2", 2000.0))
    )
    ct_samples = (
        _sample(2, "p1", 1640, 0.0, "a_site", Side.CT),
        _sample(2, "p2", 1640, 100.0, "a_site", Side.CT),
        _sample(2, "p1", 2280, 400.0, "connector", Side.CT),
        _sample(2, "p2", 2280, 500.0, "connector", Side.CT),
        _sample(2, "p1", 2920, 800.0, "b_site", Side.CT),
        _sample(2, "p2", 2920, 900.0, "b_site", Side.CT),
    )
    rounds = (
        TacticalRoundInput(
            match_id=source.match_id,
            round_id=_id("round:1"),
            round_number=1,
            side=Side.T,
            selected_team_won=True,
            is_warmup=False,
            is_complete=True,
            live_start_tick=1000,
            effective_end_tick=3500,
            selected_player_ids=(_id("p1"), _id("p2")),
            opponent_player_ids=(_id("o1"), _id("o2")),
            samples=t_samples,
            kills=(
                TacticalKillSample(
                    event_id=opening,
                    tick=1800,
                    attacker_player_id=_id("o1"),
                    victim_player_id=_id("p2"),
                    attacker_team_id=_id("enemy"),
                    victim_team_id=source.team_id,
                ),
                TacticalKillSample(
                    event_id=trade_kill,
                    tick=1830,
                    attacker_player_id=_id("p1"),
                    victim_player_id=_id("o1"),
                    attacker_team_id=source.team_id,
                    victim_team_id=_id("enemy"),
                ),
            ),
            damages=(
                TacticalDamageSample(
                    event_id=_id("he-damage"),
                    tick=2510,
                    attacker_player_id=_id("p1"),
                    victim_player_id=_id("o2"),
                    attacker_team_id=source.team_id,
                    victim_team_id=_id("enemy"),
                    weapon="hegrenade",
                    damage_health=48,
                ),
            ),
            trades=(
                TacticalTradeSample(
                    traded_kill_event_id=trade_kill,
                    original_kill_event_id=opening,
                    tick_delta=30,
                    team_id=source.team_id,
                ),
            ),
            utility=(
                TacticalUtilitySample(
                    effect_id=_id("he-effect"),
                    projectile_id=_id("he-projectile"),
                    owner_player_id=_id("p1"),
                    owner_team_id=source.team_id,
                    effect_type="he",
                    start_tick=2500,
                    end_tick=2500,
                    center_x=10.0,
                    center_y=10.0,
                    center_z=0.0,
                ),
            ),
            plant=TacticalPlantSample(
                event_id=_id("plant"), tick=3000, site="A", player_id=_id("p1")
            ),
        ),
        TacticalRoundInput(
            match_id=source.match_id,
            round_id=_id("round:2"),
            round_number=2,
            side=Side.CT,
            selected_team_won=False,
            is_warmup=False,
            is_complete=True,
            live_start_tick=1000,
            effective_end_tick=3600,
            selected_player_ids=(_id("p1"), _id("p2")),
            opponent_player_ids=(_id("o1"), _id("o2")),
            samples=ct_samples,
            kills=(),
            damages=(
                TacticalDamageSample(
                    event_id=_id("contact"),
                    tick=1700,
                    attacker_player_id=_id("o1"),
                    victim_player_id=_id("p1"),
                    attacker_team_id=_id("enemy"),
                    victim_team_id=source.team_id,
                    weapon="ak47",
                    damage_health=10,
                ),
            ),
            trades=(),
            utility=(),
            save_availability="available",
            save_signal=TacticalSaveSignal(
                feature_id=_id("save"), saved=True, tick_start=3200, tick_end=3600
            ),
        ),
    )
    return TacticalV2Input(
        profile_id=_id("profile"), matches=(TacticalMatchInput(source=source, rounds=rounds),)
    )


def test_tactical_v2_is_deterministic_and_covers_independent_families() -> None:
    engine = TacticalV2Engine()
    first = engine.compute(_input())
    second = engine.compute(_input())
    warning_variant = engine.compute(_input().model_copy(update={"warnings": ("fixture",)}))

    assert first == second
    assert warning_variant.tactical_fingerprint != first.tactical_fingerprint
    kinds = {item.insight_type for item in first.insights}
    assert TacticalInsightType.PATH_CLUSTER in kinds
    assert TacticalInsightType.EXECUTE_PACKAGE in kinds
    assert TacticalInsightType.UTILITY_OUTCOME in kinds
    assert TacticalInsightType.SPACING_PROFILE in kinds
    assert TacticalInsightType.ENTRY_STRUCTURE in kinds
    assert TacticalInsightType.TRADE_STRUCTURE in kinds
    assert TacticalInsightType.ROTATION_TRANSITION in kinds
    assert TacticalInsightType.CLUTCH_BEHAVIOR in kinds
    assert TacticalInsightType.SAVE_BEHAVIOR in kinds
    assert TacticalInsightType.HEATMAP_CELL in kinds
    assert all(item.evidence_references for item in first.insights)
    assert all(item.small_sample_warning for item in first.insights)

    utility = next(
        item for item in first.insights if item.insight_type is TacticalInsightType.UTILITY_OUTCOME
    )
    assert utility.availability.value == "partial"
    assert utility.numerator == utility.denominator == 1
    assert utility.metrics["damage_health_total"] == 48.0


def _persist_sources(database: Path) -> None:
    source = _source()
    now = datetime.now(UTC)
    opponents = DuckDBOpponentRepository(database)
    opponents.create_profile(
        OpponentProfile(
            profile_id=_id("profile"),
            display_name="Tactical fixture",
            created_at=now,
            updated_at=now,
        )
    )
    opponents.save_selection(
        OpponentMatchSelection(
            profile_id=_id("profile"),
            match_id=source.match_id,
            team_id=source.team_id,
            selection_source=OpponentSelectionSource.USER_CONFIRMED,
            created_at=now,
        )
    )
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "INSERT INTO analytics_runs (analytics_fingerprint, match_id, dataset_fingerprint, "
            "analytics_schema_version, analytics_rule_version, analytics_config_hash, config, "
            "availability, summary, row_counts, warnings) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                source.analytics_fingerprint,
                source.match_id,
                source.dataset_fingerprint,
                "1",
                source.analytics_rule_version,
                "2" * 64,
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
            ],
        )
        connection.execute(
            "INSERT INTO temporal_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
            [
                source.temporal_run_id,
                source.temporal_fingerprint,
                source.match_id,
                source.dataset_fingerprint,
                "1",
                source.temporal_rule_version,
                "3" * 64,
                "{}",
                "{}",
                "{}",
                "[]",
            ],
        )
        connection.execute(
            """
            INSERT INTO spatial_runs (
                spatial_run_id, spatial_fingerprint, match_id, dataset_fingerprint,
                temporal_run_id, temporal_fingerprint, source_demo_sha256, parser_name,
                parser_version, spatial_schema_version, spatial_rule_version,
                spatial_config_hash, config, map_model, capabilities, summary, row_counts,
                warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                source.spatial_run_id,
                source.spatial_fingerprint,
                source.match_id,
                source.dataset_fingerprint,
                source.temporal_run_id,
                source.temporal_fingerprint,
                "1" * 64,
                "fixture",
                "1",
                "1",
                source.spatial_rule_version,
                "4" * 64,
                "{}",
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
            ],
        )
        connection.execute(
            """
            INSERT INTO zone_assignment_runs (
                zone_assignment_run_id, zone_assignment_fingerprint,
                zone_assignment_schema_version, zone_assignment_rule_version,
                zone_assignment_config_hash, match_id, dataset_fingerprint, spatial_run_id,
                spatial_fingerprint, spatial_schema_version, spatial_rule_version,
                zone_set_key, config, capability, summary, row_counts, warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                source.zone_assignment_run_id,
                source.zone_assignment_fingerprint,
                "1",
                source.zone_assignment_rule_version,
                "5" * 64,
                source.match_id,
                source.dataset_fingerprint,
                source.spatial_run_id,
                source.spatial_fingerprint,
                "1",
                source.spatial_rule_version,
                "fixture",
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
            ],
        )
        connection.execute(
            """
            INSERT INTO round_feature_runs (
                feature_run_id, feature_fingerprint, feature_schema_version,
                feature_rule_version, feature_config_hash, match_id, dataset_fingerprint,
                analytics_fingerprint, analytics_rule_version,
                temporal_run_id, temporal_fingerprint, temporal_rule_version,
                spatial_run_id, spatial_fingerprint, spatial_rule_version,
                zone_assignment_run_id, zone_assignment_fingerprint,
                zone_assignment_rule_version, config, capabilities, summary, row_counts, warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                source.feature_run_id,
                source.feature_fingerprint,
                "1",
                source.feature_rule_version,
                "6" * 64,
                source.match_id,
                source.dataset_fingerprint,
                source.analytics_fingerprint,
                source.analytics_rule_version,
                source.temporal_run_id,
                source.temporal_fingerprint,
                source.temporal_rule_version,
                source.spatial_run_id,
                source.spatial_fingerprint,
                source.spatial_rule_version,
                source.zone_assignment_run_id,
                source.zone_assignment_fingerprint,
                source.zone_assignment_rule_version,
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
            ],
        )


def test_tactical_v2_persistence_api_and_match_cascade(tmp_path: Path) -> None:
    database = tmp_path / "tactical.duckdb"
    DuckDBMatchRepository(database).initialize()
    _persist_sources(database)
    state = TacticalV2Engine().compute(_input())
    repository = DuckDBTacticalV2Repository(database)

    saved = repository.save(state)
    repeated = repository.save(state)
    summary = repository.get_summary(_id("profile"))
    insights = repository.list_insights(_id("profile"))

    assert saved.row_counts["tactical_v2_insights"] == len(state.insights)
    assert repeated.status.value == "already_exists"
    assert summary is not None
    assert summary.source_pins == state.source_pins
    assert insights == tuple(
        sorted(
            state.insights,
            key=lambda item: (
                -item.frequency,
                -item.denominator,
                item.insight_type.value,
                item.key,
            ),
        )
    )

    opponents = DuckDBOpponentRepository(database)
    opponents.save_selection(
        OpponentMatchSelection(
            profile_id=_id("profile"),
            match_id=state.source_pins[0].match_id,
            team_id=_id("different-team"),
            selection_source=OpponentSelectionSource.USER_CONFIRMED,
            created_at=datetime.now(UTC),
        )
    )
    assert repository.get_summary(_id("profile")) is None
    opponents.save_selection(
        OpponentMatchSelection(
            profile_id=_id("profile"),
            match_id=state.source_pins[0].match_id,
            team_id=state.source_pins[0].team_id,
            selection_source=OpponentSelectionSource.USER_CONFIRMED,
            created_at=datetime.now(UTC),
        )
    )
    assert repository.get_summary(_id("profile")) is not None

    with TestClient(create_app(database)) as client:
        assert client.get(f"/api/opponents/{_id('profile')}/tactical-v2/summary").status_code == 200
        page = client.get(f"/ui/opponents/{_id('profile')}/tactical-v2")
        assert page.status_code == 200
        assert "Тактические сигналы V2" in page.text
        assert "1/1" in page.text

    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE tactical_v2_runs SET tactical_rule_version = 'legacy_fixture'")
    assert repository.get_summary(_id("profile")) is None
    runs = repository.list_runs(_id("profile"))
    assert len(runs) == 1
    assert not runs[0].compatible
    assert not runs[0].selected_by_default

    with duckdb.connect(str(database)) as connection:
        delete_tactical_v2_for_matches(connection, [state.source_pins[0].match_id])
        assert connection.execute("SELECT count(*) FROM tactical_v2_runs").fetchone() == (0,)
