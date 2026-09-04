from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import duckdb
import pytest
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import (
    DuckDBAnalystNoteRepository,
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
    DuckDBTacticalV2Repository,
)
from stratweb.adapters.persistence._tactical_v2_cascade import (
    delete_tactical_v2_for_matches,
)
from stratweb.application.analyst_notes import normalize_analyst_note
from stratweb.application.opponent_models import (
    OpponentMatchSelection,
    OpponentProfile,
    OpponentSelectionSource,
)
from stratweb.domain.enums import Side
from stratweb.features.models import ROUND_FEATURE_SCHEMA_VERSION
from stratweb.main import create_app
from stratweb.tactical_v2.engine import TacticalV2Engine
from stratweb.tactical_v2.models import (
    TacticalBlindSample,
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
from stratweb.web.tactical_evidence_presenter import (
    TACTICAL_EVIDENCE_PAGE_SIZE,
    build_tactical_evidence_page,
)
from stratweb.web.tactical_v2_presenter import (
    TACTICAL_V2_PAGE_SIZE,
    TacticalV2Filters,
    build_tactical_insight_card,
    build_tactical_v2_page,
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


def test_utility_roi_tracks_team_flash_predeath_inventory_and_smoke_clock() -> None:
    source = _source()
    round_item = TacticalRoundInput(
        match_id=source.match_id,
        round_id=_id("utility-round"),
        round_number=1,
        side=Side.T,
        selected_team_won=False,
        is_warmup=False,
        is_complete=True,
        live_start_tick=100,
        effective_end_tick=300,
        selected_player_ids=(_id("p1"), _id("p2")),
        opponent_player_ids=(_id("o1"),),
        samples=(
            TacticalPlayerSample(
                snapshot_id=_id("predeath-inventory"),
                player_id=_id("p1"),
                player_name="Alpha",
                tick=190,
                x=0.0,
                y=0.0,
                z=0.0,
                alive=True,
                side=Side.T,
                utility_inventory=("flashbang", "smoke"),
            ),
        ),
        kills=(
            TacticalKillSample(
                event_id=_id("utility-death"),
                tick=200,
                victim_player_id=_id("p1"),
                victim_team_id=source.team_id,
                attacker_player_id=_id("o1"),
                attacker_team_id=_id("enemy"),
                game_time=30.0,
            ),
        ),
        damages=(
            TacticalDamageSample(
                event_id=_id("post-smoke-contact"),
                tick=140,
                attacker_player_id=_id("o1"),
                victim_player_id=_id("p1"),
                attacker_team_id=_id("enemy"),
                victim_team_id=source.team_id,
                weapon="ak47",
                damage_health=10,
                game_time=22.0,
            ),
        ),
        blinds=(
            TacticalBlindSample(
                event_id=_id("team-blind"),
                tick=120,
                attacker_player_id=_id("p1"),
                victim_player_id=_id("p2"),
                attacker_team_id=source.team_id,
                victim_team_id=source.team_id,
                duration_seconds=2.5,
                entity_id=7,
                game_time=18.0,
            ),
            TacticalBlindSample(
                event_id=_id("enemy-blind"),
                tick=120,
                attacker_player_id=_id("p1"),
                victim_player_id=_id("o1"),
                attacker_team_id=source.team_id,
                victim_team_id=_id("enemy"),
                duration_seconds=1.0,
                entity_id=7,
                game_time=18.0,
            ),
        ),
        trades=(),
        utility=(
            TacticalUtilitySample(
                effect_id=_id("flash-effect"),
                projectile_id=_id("flash-projectile"),
                source_entity_id=7,
                owner_player_id=_id("p1"),
                owner_team_id=source.team_id,
                effect_type="flash",
                start_tick=120,
                end_tick=120,
            ),
            TacticalUtilitySample(
                effect_id=_id("smoke-effect"),
                projectile_id=_id("smoke-projectile"),
                source_entity_id=8,
                owner_player_id=_id("p1"),
                owner_team_id=source.team_id,
                effect_type="smoke",
                start_tick=130,
                end_tick=230,
                game_time=20.0,
                round_start_time=5.0,
            ),
            TacticalUtilitySample(
                effect_id=_id("he-no-effect"),
                projectile_id=_id("he-no-effect-projectile"),
                source_entity_id=9,
                owner_player_id=_id("p1"),
                owner_team_id=source.team_id,
                effect_type="he",
                start_tick=150,
                end_tick=150,
            ),
        ),
    )
    data = TacticalV2Input(
        profile_id=_id("utility-profile"),
        matches=(
            TacticalMatchInput(
                source=source,
                rounds=(round_item,),
                blind_events_available=True,
                damage_events_available=True,
            ),
        ),
    )

    state = TacticalV2Engine().compute(data)

    team_flash = next(
        item for item in state.insights if item.insight_type is TacticalInsightType.TEAM_FLASH
    )
    assert (team_flash.numerator, team_flash.denominator) == (1, 1)
    assert team_flash.metrics["team_blind_seconds_total"] == 2.5
    assert team_flash.metrics["enemy_blind_seconds_total"] == 1.0

    carried = next(
        item
        for item in state.insights
        if item.insight_type is TacticalInsightType.UTILITY_LOSS and item.key == "carried_on_death"
    )
    assert (carried.numerator, carried.denominator) == (1, 1)
    assert carried.metrics["utility_items_total"] == 2.0
    assert carried.metrics["estimated_utility_value_total"] == 500.0

    no_effect = next(
        item
        for item in state.insights
        if item.insight_type is TacticalInsightType.UTILITY_LOSS
        and item.key == "no_direct_effect:he"
    )
    assert (no_effect.numerator, no_effect.denominator) == (1, 1)

    smoke = next(
        item for item in state.insights if item.insight_type is TacticalInsightType.SMOKE_TIMING
    )
    assert smoke.key == "start:15"
    assert smoke.metrics["smoke_start_seconds_median"] == 15.0
    assert smoke.metrics["contact_window_seconds_median"] == 2.0
    page = build_tactical_v2_page(
        state.profile_id,
        state.tactical_run_id,
        state.insights,
        filters=TacticalV2Filters(),
        page=1,
    )
    assert {card.source.insight_type for card in page.utility_cards} == {
        TacticalInsightType.TEAM_FLASH,
        TacticalInsightType.UTILITY_LOSS,
        TacticalInsightType.SMOKE_TIMING,
    }
    duplicate_loss = next(
        item for item in state.insights if item.insight_type is TacticalInsightType.UTILITY_LOSS
    ).model_copy(
        update={
            "insight_id": _id("dominant-utility-loss"),
            "numerator": 100,
            "denominator": 100,
            "sample_size": 100,
            "frequency": 1.0,
        }
    )
    balanced_page = build_tactical_v2_page(
        state.profile_id,
        state.tactical_run_id,
        (*state.insights, duplicate_loss),
        filters=TacticalV2Filters(),
        page=1,
    )
    assert {card.source.insight_type for card in balanced_page.utility_cards} == {
        TacticalInsightType.TEAM_FLASH,
        TacticalInsightType.UTILITY_LOSS,
        TacticalInsightType.SMOKE_TIMING,
    }


def test_tactical_v2_product_view_filters_without_changing_insights() -> None:
    state = TacticalV2Engine().compute(_input())
    original = state.insights
    view = build_tactical_v2_page(
        state.profile_id,
        state.tactical_run_id,
        state.insights,
        filters=TacticalV2Filters(),
        page=1,
    )
    filtered = build_tactical_v2_page(
        state.profile_id,
        state.tactical_run_id,
        state.insights,
        filters=TacticalV2Filters(
            insight_type=TacticalInsightType.ENTRY_STRUCTURE,
            side=Side.T,
        ),
        page=1,
    )

    assert state.insights == original
    assert view.curated
    assert len(view.cards) < min(TACTICAL_V2_PAGE_SIZE, len(state.insights))
    assert len(view.cards) <= len(TacticalInsightType)
    assert len(view.highlights) <= 3
    assert len(
        {(card.source.insight_type, card.source.map_name, card.source.side) for card in view.cards}
    ) == len(view.cards)
    assert view.total_count == len(state.insights)
    assert not filtered.curated
    assert filtered.filtered_count > 0
    assert all(
        card.source.insight_type is TacticalInsightType.ENTRY_STRUCTURE
        and card.source.side is Side.T
        for card in filtered.cards
    )
    assert all("site:" not in str(card.title_values) for card in view.cards)
    assert all(card.frequency_band_key.startswith("tactical.frequency.") for card in view.cards)
    rotation = next(
        card
        for card in view.cards
        if card.source.insight_type is TacticalInsightType.ROTATION_TRANSITION
    )
    assert rotation.title_key == "tactical.card.title.rotation_transition"


def test_plain_language_frequency_and_reliability_bands_are_deterministic() -> None:
    source = TacticalV2Engine().compute(_input()).insights[0]
    cases = (
        (20, 20, 1.0, "tactical.frequency.every_time"),
        (19, 20, 0.95, "tactical.frequency.almost_always"),
        (10, 20, 0.5, "tactical.frequency.often"),
        (5, 20, 0.25, "tactical.frequency.sometimes"),
        (1, 20, 0.05, "tactical.frequency.rarely"),
        (0, 20, 0.0, "tactical.frequency.not_seen"),
    )
    for numerator, denominator, frequency, expected in cases:
        card = build_tactical_insight_card(
            source.model_copy(
                update={
                    "numerator": numerator,
                    "denominator": denominator,
                    "sample_size": denominator,
                    "frequency": frequency,
                }
            )
        )
        assert card.frequency_band_key == expected
        assert card.reliability_key == "tactical.reliability.one_match"


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
                ROUND_FEATURE_SCHEMA_VERSION,
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
    assert (
        repository.get_insight(
            _id("profile"),
            state.insights[0].insight_id,
            tactical_run_id=state.tactical_run_id,
        )
        == state.insights[0]
    )
    assert (
        repository.get_insight(
            _id("profile"),
            _id("missing-insight"),
            tactical_run_id=state.tactical_run_id,
        )
        is None
    )
    evidence_fixture = tuple(
        state.insights[0].evidence_references[0].model_copy(update={"round_number": number})
        for number in range(1, TACTICAL_EVIDENCE_PAGE_SIZE + 2)
    )
    evidence_view = build_tactical_evidence_page(
        summary,
        state.insights[0],
        evidence_fixture,
        page=2,
    )
    assert evidence_view.page == 2
    assert len(evidence_view.items) == 1
    assert evidence_view.previous_href is not None
    assert evidence_view.next_href is None
    spatial_source = evidence_fixture[0].model_copy(
        update={
            "tick_start": 12345,
            "tick_end": 12345,
            "snapshot_ids": (_id("evidence-snapshot"),),
        }
    )
    spatial_view = build_tactical_evidence_page(
        summary,
        state.insights[0],
        (spatial_source,),
        page=1,
    )
    assert spatial_view.items[0].spatial_href is not None
    assert "mode=smooth" in spatial_view.items[0].spatial_href
    assert "mode=exact" not in spatial_view.items[0].spatial_href

    opponents = DuckDBOpponentRepository(database)
    opponents.save_selection(
        OpponentMatchSelection(
            profile_id=_id("profile"),
            match_id=_id("selected-without-features"),
            team_id=_id("selected-without-features-team"),
            selection_source=OpponentSelectionSource.USER_CONFIRMED,
            created_at=datetime.now(UTC),
        )
    )
    # A selected match that has not reached Stage 8.4 must not hide a valid
    # partial Tactical V2 run built from the profile's processed matches.
    assert repository.get_summary(_id("profile")) is not None
    assert repository.list_runs(_id("profile"))[0].selected_by_default

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
        api_url = f"/api/opponents/{_id('profile')}/tactical-v2/summary"
        api_before_locale_change = client.get(api_url)
        assert api_before_locale_change.status_code == 200
        page = client.get(f"/ui/opponents/{_id('profile')}/tactical-v2")
        assert page.status_code == 200
        assert "Тактический обзор" in page.text
        assert "Как команда использует гранаты" in page.text
        assert "Что важно заметить" in page.text
        assert "Пока используйте это как подсказку" in page.text
        assert "Почему система так решила" in page.text
        assert "За атаку" in page.text or "За защиту" in page.text
        assert "Часто наблюдаемый сектор карты (" not in page.text
        assert "T + CT" not in page.text
        assert "-&gt;" not in page.text
        assert 'name="type"' in page.text
        assert "site:A|" not in page.text
        selected_insight = state.insights[0]
        assert f"/tactical-v2/insights/{selected_insight.insight_id}/evidence" in page.text
        evidence_page = client.get(
            f"/ui/opponents/{_id('profile')}/tactical-v2/insights/"
            f"{selected_insight.insight_id}/evidence",
            params={"run_id": state.tactical_run_id, "lang": "ru"},
        )
        assert evidence_page.status_code == 200
        assert "Доказательства" in evidence_page.text
        assert "Как это выглядит в выборке" in evidence_page.text
        assert (
            "Посмотреть эпизод на 2D-карте" in evidence_page.text
            or "Посмотреть, как прошёл раунд" in evidence_page.text
            or "Открыть матч" in evidence_page.text
        )
        assert "Другие способы проверить эпизод" in evidence_page.text
        assert f"run_id={_id('temporal')}" in evidence_page.text
        assert f"/ui/matches/{_id('match')}#rounds" in evidence_page.text
        assert "Личная заметка аналитика" in evidence_page.text
        assert "никогда не считается доказательством" in evidence_page.text
        note_url = (
            f"/ui/opponents/{_id('profile')}/tactical-v2/insights/"
            f"{selected_insight.insight_id}/note"
        )
        saved_note = client.post(
            note_url,
            params={"run_id": state.tactical_run_id},
            data={"body": "  Проверить выход A ещё раз.\r\nСравнить тайминг.  "},
            headers={"accept": "text/html"},
        )
        assert saved_note.status_code == 200
        assert "Заметка сохранена локально." in saved_note.text
        assert "Проверить выход A ещё раз.\nСравнить тайминг." in saved_note.text
        blocked_note = client.post(
            note_url,
            params={"run_id": state.tactical_run_id},
            data={"body": "cross-site"},
            headers={"origin": "https://example.invalid"},
        )
        assert blocked_note.status_code == 403
        invalid_note = client.post(
            note_url,
            params={"run_id": state.tactical_run_id},
            data={"body": "   "},
            headers={"accept": "text/html"},
        )
        assert invalid_note.status_code == 422
        assert "Заметку не удалось сохранить" in invalid_note.text
        deleted_note = client.post(
            f"{note_url}/delete",
            params={"run_id": state.tactical_run_id},
            headers={"accept": "text/html"},
        )
        assert deleted_note.status_code == 200
        assert "Заметка удалена." in deleted_note.text
        event_insight = next(
            item
            for item in state.insights
            if any(reference.event_ids for reference in item.evidence_references)
        )
        event_page = client.get(
            f"/ui/opponents/{_id('profile')}/tactical-v2/insights/"
            f"{event_insight.insight_id}/evidence",
            params={"run_id": state.tactical_run_id, "lang": "en"},
        )
        assert event_page.status_code == 200
        assert "Observation evidence" in event_page.text
        assert "Доказательства" not in event_page.text
        assert "/events/" in event_page.text
        missing_evidence = client.get(
            f"/ui/opponents/{_id('profile')}/tactical-v2/insights/"
            f"{_id('missing-insight')}/evidence",
            params={"run_id": state.tactical_run_id},
        )
        assert missing_evidence.status_code == 404
        assert "Observation not found" in missing_evidence.text
        english = client.get(
            f"/ui/opponents/{_id('profile')}/tactical-v2",
            params={"lang": "en"},
        )
        assert english.status_code == 200
        assert '<html lang="en"' in english.text
        assert "Tactical overview" in english.text
        assert "What is worth noticing" in english.text
        assert "Treat these as preparation hints for now" in english.text
        assert "Тактический обзор" not in english.text
        assert "stratweb_locale=en" in english.headers["set-cookie"]
        persisted_locale = client.get(f"/ui/opponents/{_id('profile')}/tactical-v2")
        assert "Tactical overview" in persisted_locale.text
        unsupported = client.get(
            f"/ui/opponents/{_id('profile')}/tactical-v2",
            params={"lang": "es"},
        )
        assert "Tactical overview" in unsupported.text
        assert "set-cookie" not in unsupported.headers
        assert client.get(api_url).json() == api_before_locale_change.json()
        filtered = client.get(
            f"/ui/opponents/{_id('profile')}/tactical-v2",
            params={"type": "entry_structure", "side": "T"},
        )
        assert filtered.status_code == 200
        assert 'value="entry_structure" selected' in filtered.text
        assert 'value="T" selected' in filtered.text
        assert (
            client.get(
                f"/ui/opponents/{_id('profile')}/tactical-v2",
                params={"type": "not-a-type"},
            ).status_code
            == 422
        )

    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE tactical_v2_runs SET tactical_rule_version = 'legacy_fixture'")
    assert repository.get_summary(_id("profile")) is None
    runs = repository.list_runs(_id("profile"))
    assert len(runs) == 1
    assert not runs[0].compatible
    assert not runs[0].selected_by_default

    with duckdb.connect(str(database)) as connection:
        DuckDBAnalystNoteRepository(database).save(
            _id("profile"),
            state.tactical_run_id,
            state.insights[0].insight_id,
            "Удалить вместе с run",
        )
        delete_tactical_v2_for_matches(connection, [state.source_pins[0].match_id])
        assert connection.execute("SELECT count(*) FROM tactical_v2_runs").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM analyst_notes").fetchone() == (0,)


def test_analyst_note_normalization_rejects_unknown_or_empty_content() -> None:
    assert normalize_analyst_note(" one\r\ntwo ") == "one\ntwo"
    with pytest.raises(ValueError):
        normalize_analyst_note("   ")
    with pytest.raises(ValueError):
        normalize_analyst_note("unknown\x00content")
