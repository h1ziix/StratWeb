from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from stratweb.domain.enums import Side
from stratweb.tactical_v2.engine import TacticalV2Engine
from stratweb.tactical_v2.models import (
    TacticalDamageSample,
    TacticalInsightType,
    TacticalMatchInput,
    TacticalPlantSample,
    TacticalPlayerSample,
    TacticalRoundInput,
    TacticalShotSample,
    TacticalSourcePin,
    TacticalV2Input,
)
from stratweb.tactical_v2.pace import compute_depth_facts, source_tick_seconds


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, "pace-test:" + name)


def sample(player: str, seconds: float, zone: str, side: Side = Side.T) -> TacticalPlayerSample:
    return TacticalPlayerSample(
        snapshot_id=uid(f"{player}:{seconds}:{zone}"),
        player_id=uid(player),
        steam_id=player,
        player_name=player,
        tick=1000 + int(seconds * 64),
        x=0.0,
        y=0.0,
        z=0.0,
        side=side,
        alive=True,
        zone_id=zone,
        zone_name=zone,
    )


def round_data(contact_seconds: float = 20) -> TacticalRoundInput:
    events = tuple(
        TacticalDamageSample(
            event_id=uid(f"damage:{seconds}"),
            tick=1000 + int(seconds * 64),
            game_time=100.0 + seconds,
            attacker_player_id=uid("p1"),
            victim_player_id=uid("enemy"),
            attacker_team_id=uid("team"),
            victim_team_id=uid("other"),
            weapon="ak47",
            damage_health=10,
        )
        for seconds in (contact_seconds, contact_seconds + 2)
    )
    return TacticalRoundInput(
        match_id=uid("match"),
        round_id=uid("round"),
        round_number=1,
        side=Side.T,
        is_warmup=False,
        is_complete=True,
        live_start_tick=1000,
        effective_end_tick=10000,
        selected_player_ids=(uid("p1"), uid("p2")),
        opponent_player_ids=(uid("enemy"),),
        samples=(sample("p1", contact_seconds, "bombsite_a"),),
        kills=(),
        damages=events,
        trades=(),
        utility=(),
    )


def data(item: TacticalRoundInput, map_name: str = "de_mirage") -> TacticalV2Input:
    source = TacticalSourcePin(
        match_id=item.match_id,
        team_id=uid("team"),
        map_name=map_name,
        dataset_fingerprint="a" * 64,
        analytics_fingerprint="b" * 64,
        analytics_rule_version="v1",
        temporal_run_id=uid("temporal"),
        temporal_fingerprint="c" * 64,
        temporal_rule_version="v1",
        spatial_run_id=uid("spatial"),
        spatial_fingerprint="d" * 64,
        spatial_rule_version="v1",
        zone_assignment_run_id=uid("zones"),
        zone_assignment_fingerprint="e" * 64,
        zone_assignment_rule_version="v1",
    )
    return TacticalV2Input(
        profile_id=uid("profile"), matches=(TacticalMatchInput(source=source, rounds=(item,)),)
    )


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (24.984375, "fast_hit"),
        (25.0, "mid_contact"),
        (60.0, "mid_contact"),
        (60.015625, "late_execute"),
    ],
)
def test_pace_boundaries_use_live_start_and_real_clock(seconds: float, expected: str) -> None:
    facts = compute_depth_facts(data(round_data(seconds)).matches)
    assert (
        next(item for item in facts if item.kind is TacticalInsightType.ATTACK_PACE).key == expected
    )


def test_early_mid_duel_is_not_declared_a_rush() -> None:
    item = round_data().model_copy(update={"samples": (sample("p1", 20.0, "top_mid"),)})
    assert compute_depth_facts(data(item).matches)[0].key == "early_contact"


def test_control_requires_two_players_observed_before_contact_not_future_or_spawn() -> None:
    item = round_data(35).model_copy(
        update={"samples": (sample("p1", 35.0, "top_mid"), sample("p2", 35.0, "ramp"))}
    )
    assert compute_depth_facts(data(item).matches)[0].key == "default_to_split"
    for samples in (
        (sample("p1", 35.0, "top_mid"), sample("p2", 36.0, "ramp")),
        (sample("p1", 35.0, "t_spawn"), sample("p2", 35.0, "ct_spawn")),
    ):
        assert (
            compute_depth_facts(data(item.model_copy(update={"samples": samples})).matches)[0].key
            == "mid_contact"
        )


@pytest.mark.parametrize(
    "change", [{"is_warmup": True}, {"is_complete": False}, {"live_start_tick": None}]
)
def test_excludes_unusable_rounds(change: dict[str, object]) -> None:
    assert not compute_depth_facts(data(round_data().model_copy(update=change)).matches)


def test_clock_missing_or_conflicting_is_not_replaced_by_64_tick_guess() -> None:
    item = round_data()
    assert source_tick_seconds(item) == 1 / 64
    for events in (
        (item.damages[0],),
        tuple(e.model_copy(update={"game_time": None}) for e in item.damages),
    ):
        assert not compute_depth_facts(data(item.model_copy(update={"damages": events})).matches)
    bad = item.damages[0].model_copy(update={"event_id": uid("conflict"), "game_time": 500.0})
    assert source_tick_seconds(item.model_copy(update={"damages": (*item.damages, bad)})) is None


def test_split_requires_parallel_distinct_players_and_known_plant_site() -> None:
    item = round_data(35).model_copy(
        update={
            "plant": TacticalPlantSample(event_id=uid("plant"), tick=3560, site="A"),
            "samples": (sample("p1", 35.0, "conector"), sample("p2", 36.0, "ramp")),
        }
    )
    routes = [
        fact
        for fact in compute_depth_facts(data(item).matches)
        if fact.kind is TacticalInsightType.SITE_HIT
    ]
    assert routes[0].key == "a_connector_ramp"
    assert uid("plant") in routes[0].evidence.event_ids
    assert len(routes[0].evidence.snapshot_ids) == 2
    solo = item.model_copy(
        update={"samples": (sample("p1", 35.0, "conector"), sample("p1", 36.0, "ramp"))}
    )
    assert all(fact.key != "a_connector_ramp" for fact in compute_depth_facts(data(solo).matches))
    assert all(
        fact.kind is not TacticalInsightType.SITE_HIT
        for fact in compute_depth_facts(data(item, "de_nuke").matches)
    )
    unknown = item.model_copy(update={"plant": item.plant.model_copy(update={"site": None})})
    assert all(
        fact.kind is not TacticalInsightType.SITE_HIT
        for fact in compute_depth_facts(data(unknown).matches)
    )


def test_awp_requires_actual_weapon_event_and_recent_zone_not_buy_inventory() -> None:
    item = round_data(10).model_copy(
        update={
            "side": Side.CT,
            "samples": (
                sample("p1", 10.0, "window", Side.CT).model_copy(update={"weapons": ("awp",)}),
            ),
        }
    )
    assert not any(
        f.kind is TacticalInsightType.AWP_OPENING for f in compute_depth_facts(data(item).matches)
    )
    item = item.model_copy(
        update={
            "damages": tuple(
                event.model_copy(update={"weapon": "weapon_awp"}) for event in item.damages
            )
        }
    )
    facts = compute_depth_facts(data(item).matches)
    assert facts[0].kind is TacticalInsightType.AWP_OPENING
    assert facts[0].key.endswith("|window")
    nuke = item.model_copy(update={"samples": (sample("p1", 10.0, "ramp", Side.CT),)})
    assert compute_depth_facts(data(nuke, "de_nuke").matches)[0].label.endswith("ramp")
    stale = item.model_copy(update={"samples": (sample("p1", 8.0, "window", Side.CT),)})
    assert not compute_depth_facts(data(stale).matches)


def test_awp_shot_with_no_hit_still_has_evidence_and_no_invented_duel() -> None:
    item = round_data(20).model_copy(
        update={
            "samples": (sample("p1", 10.0, "window"),),
            "shots": (
                TacticalShotSample(
                    event_id=uid("shot"),
                    tick=1640,
                    game_time=110.0,
                    player_id=uid("p1"),
                    weapon="awp",
                ),
            ),
        }
    )
    facts = [
        f
        for f in compute_depth_facts(data(item).matches)
        if f.kind is TacticalInsightType.AWP_OPENING
    ]
    assert len(facts) == 1 and uid("shot") in facts[0].evidence.event_ids
    knife = TacticalShotSample(
        event_id=uid("knife"),
        tick=1320,
        game_time=105.0,
        player_id=uid("p1"),
        weapon="weapon_knife_t",
    )
    with_knife = item.model_copy(update={"shots": (knife, *item.shots)})
    assert any(
        f.kind is TacticalInsightType.AWP_OPENING
        for f in compute_depth_facts(data(with_knife).matches)
    )


def test_engine_ratios_determinism_and_unknown_rounds_are_not_negatives() -> None:
    first = round_data(20)
    second = round_data(65).model_copy(update={"round_number": 2, "round_id": uid("round2")})
    unknown = round_data(30).model_copy(update={"round_number": 3, "live_start_tick": None})
    original = data(first)
    inputs = original.model_copy(
        update={
            "matches": (
                original.matches[0].model_copy(update={"rounds": (first, second, unknown)}),
            )
        }
    )
    run = TacticalV2Engine().compute(inputs)
    reversed_input = inputs.model_copy(
        update={
            "matches": (inputs.matches[0].model_copy(update={"rounds": (unknown, second, first)}),)
        }
    )
    assert (
        run.tactical_fingerprint == TacticalV2Engine().compute(reversed_input).tactical_fingerprint
    )
    pace = [i for i in run.insights if i.insight_type is TacticalInsightType.ATTACK_PACE]
    assert len(pace) == 2
    assert all(i.numerator == 1 and i.denominator == 2 and i.frequency == 0.5 for i in pace)
    assert run.capabilities[TacticalInsightType.ATTACK_PACE].covered_units == 2
