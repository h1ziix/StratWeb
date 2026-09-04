from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from stratweb.domain.enums import Side
from stratweb.tactical_v2.engine import TacticalV2Engine
from stratweb.tactical_v2.models import (
    CTSetupRole,
    TacticalInsightType,
    TacticalMatchInput,
    TacticalPlayerSample,
    TacticalRoundInput,
    TacticalSourcePin,
    TacticalV2Config,
    TacticalV2Input,
)
from stratweb.tactical_v2.setups import (
    compute_ct_setups,
    ct_setup_profiles_from_insights,
)


def _id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"ct-setup-test:{value}")


def _source(match: str) -> TacticalSourcePin:
    return TacticalSourcePin(
        match_id=_id(f"match:{match}"),
        team_id=_id(f"team:{match}"),
        map_name="de_dust2",
        dataset_fingerprint="a" * 64,
        analytics_fingerprint="b" * 64,
        analytics_rule_version="analytics-v1",
        temporal_run_id=_id(f"temporal:{match}"),
        temporal_fingerprint="c" * 64,
        temporal_rule_version="temporal-v1",
        spatial_run_id=_id(f"spatial:{match}"),
        spatial_fingerprint="d" * 64,
        spatial_rule_version="spatial-v1",
        zone_assignment_run_id=_id(f"zones:{match}"),
        zone_assignment_fingerprint="e" * 64,
        zone_assignment_rule_version="zones-v1",
    )


def _sample(
    match: str,
    round_number: int,
    player: str,
    tick: int,
    zone: str,
    *,
    weapons: tuple[str, ...] | None = None,
) -> TacticalPlayerSample:
    return TacticalPlayerSample(
        snapshot_id=_id(f"snapshot:{match}:{round_number}:{player}:{tick}:{zone}"),
        player_id=_id(f"player:{match}:{player}"),
        steam_id=f"steam-{player}",
        player_name=player,
        tick=tick,
        x=float(tick),
        y=float(round_number),
        z=0.0,
        alive=True,
        side=Side.CT,
        zone_id=zone,
        zone_name=zone.replace("_", " ").title(),
        weapons=weapons,
    )


def _round(match: str, round_number: int) -> TacticalRoundInput:
    local_round = (round_number - 1) % 2 + 1
    base = 1000
    sniper_weapons = ("weapon_awp",) if round_number <= 3 else ("weapon_usp_silencer",)
    samples = [
        _sample(match, local_round, "A-anchor", base + 300, "bombsite_a"),
        _sample(match, local_round, "B-anchor", base + 300, "bombsite_b"),
        _sample(
            match,
            local_round,
            "Sniper",
            base + 300,
            "ct_mid",
            weapons=sniper_weapons,
        ),
    ]
    rotator_zone = "bombsite_a" if round_number <= 2 else "ct_spawn"
    samples.append(_sample(match, local_round, "Rotator", base + 200, rotator_zone))
    if round_number <= 2:
        samples.append(_sample(match, local_round, "Rotator", base + 900, "ct_mid"))
    selected = tuple(sorted({item.player_id for item in samples}, key=str))
    return TacticalRoundInput(
        match_id=_id(f"match:{match}"),
        round_id=_id(f"round:{match}:{local_round}"),
        round_number=local_round,
        side=Side.CT,
        is_warmup=False,
        is_complete=True,
        live_start_tick=base,
        effective_end_tick=4000,
        selected_player_ids=selected,
        opponent_player_ids=(),
        samples=tuple(samples),
        kills=(),
        damages=(),
        trades=(),
        utility=(),
    )


def _input() -> TacticalV2Input:
    matches = []
    for match, absolute_rounds in (("one", (1, 2)), ("two", (3, 4))):
        source = _source(match)
        matches.append(
            TacticalMatchInput(
                source=source,
                rounds=tuple(_round(match, number) for number in absolute_rounds),
            )
        )
    return TacticalV2Input(profile_id=_id("profile"), matches=tuple(matches))


def test_ct_setup_assigns_anchors_sniper_and_rotator_deterministically() -> None:
    data = _input()
    config = TacticalV2Config()

    first = compute_ct_setups(data.matches, config)
    second = compute_ct_setups(data.matches, config)

    assert first == second
    assert first.eligible_rounds == first.covered_rounds == 4
    assert len(first.profiles) == 1
    setup = first.profiles[0]
    assert setup.sample_rounds == setup.covered_rounds == 4

    a_anchor = setup.site_a_anchors[0]
    b_anchor = setup.site_b_anchors[0]
    sniper = setup.mid_players[0]
    rotator = setup.rotators[0]
    assert (a_anchor.player_name, a_anchor.frequency) == ("A-anchor", 1.0)
    assert (b_anchor.player_name, b_anchor.frequency) == ("B-anchor", 1.0)
    assert sniper.player_name == "Sniper"
    assert sniper.role is CTSetupRole.MID_SNIPER
    assert sniper.awp_frequency == 0.75
    assert rotator.player_name == "Rotator"
    assert (rotator.numerator, rotator.denominator, rotator.frequency) == (2, 4, 0.5)
    assert len(a_anchor.player_ids) == 2
    assert a_anchor.match_count == 2
    assert all(item.snapshot_ids for item in rotator.evidence_references)


def test_ct_setup_round_trips_through_persistable_tactical_insights() -> None:
    data = _input()
    run = TacticalV2Engine().compute(data)
    setup_insights = tuple(
        item for item in run.insights if item.insight_type is TacticalInsightType.CT_SETUP_ROLE
    )

    assert len(setup_insights) == 4
    assert (
        ct_setup_profiles_from_insights(setup_insights)
        == compute_ct_setups(data.matches, run.config).profiles
    )
    assert TacticalV2Engine().compute(data).tactical_fingerprint == run.tactical_fingerprint


def test_ct_setup_does_not_guess_unmapped_zones() -> None:
    source = _source("unknown")
    sample = _sample("unknown", 1, "Unknown", 1200, "mystery_zone")
    round_item = TacticalRoundInput(
        match_id=source.match_id,
        round_id=_id("round:unknown"),
        round_number=1,
        side=Side.CT,
        is_warmup=False,
        is_complete=True,
        live_start_tick=1000,
        selected_player_ids=(sample.player_id,),
        opponent_player_ids=(),
        samples=(sample,),
        kills=(),
        damages=(),
        trades=(),
        utility=(),
    )

    result = compute_ct_setups(
        (TacticalMatchInput(source=source, rounds=(round_item,)),), TacticalV2Config()
    )

    assert result.eligible_rounds == 1
    assert result.covered_rounds == 0
    assert result.profiles == ()
