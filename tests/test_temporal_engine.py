from __future__ import annotations

from typing import Any
from uuid import uuid5

import pytest
from pydantic import ValidationError

from stratweb.application.canonical_models import (
    CanonicalMatchDataset,
    CanonicalPlayer,
    EventPhase,
)
from stratweb.domain.enums import Side
from stratweb.exceptions import TemporalConfigurationError
from stratweb.temporal.engine import TemporalEngine
from stratweb.temporal.models import (
    BombState,
    DeathEffectStatus,
    FinalStateStatus,
    IntermediateStateStatus,
    ParticipationStatus,
    PlayerLifeStatus,
    RoundPhase,
    SimultaneousOrderingStatus,
    SnapshotStateStatus,
    TemporalAvailabilityStatus,
    TemporalConfig,
    TemporalConversionStatus,
    TemporalDeathClassification,
    TemporalEventKind,
    TemporalMatchInput,
    TemporalOrderingStatus,
)
from stratweb.temporal.snapshots import SnapshotBuilder


def _input(dataset: CanonicalMatchDataset) -> TemporalMatchInput:
    return TemporalMatchInput(
        match_id=dataset.match.match_id,
        dataset_fingerprint=dataset.dataset_fingerprint,
        teams=dataset.teams,
        players=dataset.players,
        memberships=dataset.player_team_memberships,
        rounds=dataset.rounds,
        kills=dataset.kills,
        damages=dataset.damages,
        shots=dataset.shots,
        grenades=dataset.grenades,
        bomb_events=dataset.bomb_events,
    )


def test_normal_round_builds_phases_participants_life_and_final_state(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-normal")
    result = TemporalEngine().compute(_input(dataset))
    timeline = result.timelines[0]

    assert [item.phase for item in timeline.phase_intervals] == [
        RoundPhase.FREEZE_TIME,
        RoundPhase.LIVE,
        RoundPhase.POST_ROUND,
        RoundPhase.ENDED,
    ]
    participating = [
        item
        for item in timeline.participants
        if item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
    ]
    assert len(participating) == 2
    assert all(
        item.participation_status is ParticipationStatus.INFERRED_FROM_MEMBERSHIP
        for item in participating
    )
    assert len(timeline.life_transitions) == 1
    assert timeline.life_transitions[0].death_classification is TemporalDeathClassification.ENEMY
    assert timeline.final_bomb_state is BombState.ROUND_ENDED_BEFORE_RESOLUTION
    assert result.summary.rounds == 1
    assert (
        result.summary.availability.seconds_timeline.status
        is TemporalAvailabilityStatus.UNAVAILABLE
    )


def test_ticks_are_authoritative_and_seconds_are_null_without_tickrate(
    canonical_dataset_factory: Any,
) -> None:
    result = TemporalEngine().compute(_input(canonical_dataset_factory("temporal-ticks")))
    event_time = result.timelines[0].ordered_events[0].time

    assert event_time.tick == 100
    assert event_time.seconds is None
    assert event_time.tickrate is None
    assert event_time.conversion_source is None
    assert event_time.conversion_status is TemporalConversionStatus.UNAVAILABLE


def test_tick_zero_is_a_proven_value_not_missing_data(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-zero-tick")
    round_item = dataset.rounds[0].model_copy(
        update={
            "start_tick": 0,
            "freeze_end_tick": 0,
            "end_tick": 0,
            "official_end_tick": 0,
        }
    )
    memberships = tuple(
        item.model_copy(update={"valid_from_tick": 0}) for item in dataset.player_team_memberships
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(
            update={
                "rounds": (round_item,),
                "memberships": memberships,
                "kills": (),
                "damages": (),
                "shots": (),
                "grenades": (),
                "bomb_events": (),
            }
        )
    )
    timeline = result.timelines[0]

    assert timeline.effective_end_tick == 0
    assert SnapshotBuilder().final(timeline, result.config).time.tick == 0


def test_proven_tickrate_enables_deterministic_seconds(
    canonical_dataset_factory: Any,
) -> None:
    config = TemporalConfig(tickrate=64, tickrate_source="canonical:test_tickrate")
    first = TemporalEngine().compute(_input(canonical_dataset_factory("temporal-seconds")), config)
    second = TemporalEngine().compute(_input(canonical_dataset_factory("temporal-seconds")), config)
    event_time = first.timelines[0].ordered_events[0].time

    assert event_time.seconds == 100 / 64
    assert event_time.conversion_status is TemporalConversionStatus.AVAILABLE
    assert first.temporal_fingerprint == second.temporal_fingerprint
    assert (
        first.summary.availability.seconds_timeline.status is TemporalAvailabilityStatus.AVAILABLE
    )


def test_conflicting_tickrate_is_rejected(canonical_dataset_factory: Any) -> None:
    config = TemporalConfig(
        tickrate=64,
        tickrate_source="canonical:a",
        conflicting_tickrate_sources=("canonical:b",),
    )
    with pytest.raises(TemporalConfigurationError, match="conflicting tickrate"):
        TemporalEngine().compute(_input(canonical_dataset_factory("temporal-conflict")), config)


def test_untrusted_tickrate_source_is_rejected() -> None:
    with pytest.raises(ValidationError, match="proven canonical evidence"):
        TemporalConfig(tickrate=64, tickrate_source="user:assumed")


def test_event_order_is_cross_family_and_insertion_independent(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-order")
    same_tick = 115
    changed = _input(dataset).model_copy(
        update={
            "shots": tuple(item.model_copy(update={"tick": same_tick}) for item in dataset.shots),
            "damages": tuple(reversed(dataset.damages)),
            "kills": tuple(reversed(dataset.kills)),
        }
    )
    result = TemporalEngine().compute(changed)
    kinds = [
        item.kind for item in result.timelines[0].ordered_events if item.time.tick == same_tick
    ]
    repeat = TemporalEngine().compute(
        changed.model_copy(
            update={
                "shots": tuple(reversed(changed.shots)),
                "damages": tuple(reversed(changed.damages)),
            }
        )
    )

    assert kinds == [TemporalEventKind.DAMAGE, TemporalEventKind.SHOT]
    assert result.temporal_fingerprint == repeat.temporal_fingerprint


def test_simultaneous_deaths_are_stable_but_explicitly_ambiguous(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-simultaneous")
    original = dataset.kills[0]
    second = original.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:simultaneous"),
            "attacker_player_id": original.victim_player_id,
            "victim_player_id": original.attacker_player_id,
            "attacker_team_id": original.victim_team_id,
            "victim_team_id": original.attacker_team_id,
            "attacker_side": Side.CT,
            "victim_side": Side.T,
        }
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(update={"kills": (second, original)})
    )
    deaths = [
        item for item in result.timelines[0].ordered_events if item.kind is TemporalEventKind.DEATH
    ]

    assert len({item.simultaneous_group_id for item in deaths}) == 1
    assert all(
        item.ordering_status is TemporalOrderingStatus.SIMULTANEOUS_AMBIGUOUS for item in deaths
    )
    assert result.summary.ambiguity_groups == 1
    group = result.timelines[0].simultaneous_groups[0]
    assert group.ordering_status is SimultaneousOrderingStatus.AMBIGUOUS_ORDER
    assert group.intermediate_state_status is IntermediateStateStatus.AMBIGUOUS
    assert group.final_state_status is FinalStateStatus.DETERMINISTIC
    assert group.post_group_snapshot_deterministic is True
    assert result.summary.availability.alive_state.status is TemporalAvailabilityStatus.AVAILABLE
    assert result.summary.availability.per_event_state.status is TemporalAvailabilityStatus.PARTIAL
    assert result.summary.availability.final_state.status is TemporalAvailabilityStatus.AVAILABLE

    builder = SnapshotBuilder()
    before_group = builder.before_tick_group(result.timelines[0], group.group_id, result.config)
    after_group = builder.after_tick_group(result.timelines[0], group.group_id, result.config)
    before_event = builder.before_event(result.timelines[0], deaths[0].event_id, result.config)
    after_event = builder.after_event(result.timelines[0], deaths[0].event_id, result.config)
    assert len(before_group.alive_players) == 2
    assert len(after_group.dead_players) == 2
    assert after_group.state_status is SnapshotStateStatus.AVAILABLE
    assert before_event.state_status is SnapshotStateStatus.AMBIGUOUS
    assert after_event.state_status is SnapshotStateStatus.AMBIGUOUS
    assert before_event.possible_states == group.possible_intermediate_states
    assert (
        builder.at_tick(result.timelines[0], 119, result.config).alive_players
        == before_group.alive_players
    )
    assert (
        builder.at_tick(result.timelines[0], 120, result.config).dead_players
        == after_group.dead_players
    )


def test_same_tick_duplicate_victim_is_a_true_conflict(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-same-tick-duplicate")
    original = dataset.kills[0]
    duplicate = original.model_copy(
        update={"event_id": uuid5(dataset.match.match_id, "kill:same-tick-duplicate")}
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(update={"kills": (duplicate, original)})
    )
    group = result.timelines[0].simultaneous_groups[0]

    assert group.ordering_status is SimultaneousOrderingStatus.CONFLICTING
    assert group.final_state_status is FinalStateStatus.CONFLICTING
    assert result.summary.availability.alive_state.status is TemporalAvailabilityStatus.UNRESOLVED
    assert (
        SnapshotBuilder().at_tick(result.timelines[0], 120, result.config).state_status
        is SnapshotStateStatus.UNAVAILABLE
    )


def test_final_conflict_does_not_leak_into_an_independent_later_round(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-conflict-round-local")
    original = dataset.kills[0]
    duplicate = original.model_copy(
        update={"event_id": uuid5(dataset.match.match_id, "kill:round-local-conflict")}
    )
    second_round = dataset.rounds[0].model_copy(
        update={
            "round_id": uuid5(dataset.match.match_id, "round:2"),
            "round_number": 2,
            "start_tick": 300,
            "freeze_end_tick": 310,
            "end_tick": 390,
            "official_end_tick": 400,
        }
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(
            update={
                "rounds": (*dataset.rounds, second_round),
                "kills": (original, duplicate),
            }
        )
    )

    assert (
        result.timelines[0].availability.alive_state.status is TemporalAvailabilityStatus.UNRESOLVED
    )
    assert (
        result.timelines[1].availability.alive_state.status is TemporalAvailabilityStatus.AVAILABLE
    )


def test_victim_dead_before_same_tick_group_is_conflicting(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-dead-before-group")
    original = dataset.kills[0]
    earlier = original.model_copy(
        update={"event_id": uuid5(dataset.match.match_id, "kill:earlier"), "tick": 115}
    )
    other = original.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:other-victim"),
            "attacker_player_id": original.victim_player_id,
            "victim_player_id": original.attacker_player_id,
            "attacker_team_id": original.victim_team_id,
            "victim_team_id": original.attacker_team_id,
        }
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(update={"kills": (earlier, original, other)})
    )

    assert (
        result.timelines[0].simultaneous_groups[0].final_state_status
        is FinalStateStatus.CONFLICTING
    )


def test_three_commutative_same_team_deaths_are_insertion_independent(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-three-commutative")
    original = dataset.kills[0]
    victim_ids = [uuid5(dataset.match.match_id, f"player:extra:{index}") for index in (1, 2)]
    extras = tuple(
        CanonicalPlayer(
            player_id=player_id,
            steam_id=f"76561198000000{index:03d}",
            current_name=f"Extra {index}",
            known_names=(f"Extra {index}",),
        )
        for index, player_id in enumerate(victim_ids, start=1)
    )
    memberships = (
        *dataset.player_team_memberships,
        *(
            dataset.player_team_memberships[1].model_copy(update={"player_id": player_id})
            for player_id in victim_ids
        ),
    )
    kills = (
        original,
        *(
            original.model_copy(
                update={
                    "event_id": uuid5(dataset.match.match_id, f"kill:extra:{index}"),
                    "victim_player_id": player_id,
                }
            )
            for index, player_id in enumerate(victim_ids, start=1)
        ),
    )
    data = _input(dataset).model_copy(
        update={
            "players": (*dataset.players, *extras),
            "memberships": memberships,
            "kills": kills,
        }
    )
    first = TemporalEngine().compute(data)
    second = TemporalEngine().compute(data.model_copy(update={"kills": tuple(reversed(kills))}))
    group = first.timelines[0].simultaneous_groups[0]

    assert group.event_count == 3
    assert group.final_state_status is FinalStateStatus.DETERMINISTIC
    assert len(group.post_group_state.dead_players if group.post_group_state else ()) == 3
    assert first.temporal_fingerprint == second.temporal_fingerprint


def test_victimless_death_is_retained_without_life_effect(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-victimless")
    victimless = dataset.kills[0].model_copy(
        update={"victim_player_id": None, "victim_team_id": None, "victim_side": Side.UNKNOWN}
    )
    result = TemporalEngine().compute(_input(dataset).model_copy(update={"kills": (victimless,)}))
    timeline = result.timelines[0]
    death = next(item for item in timeline.ordered_events if item.kind is TemporalEventKind.DEATH)

    assert death.death_effect_status is DeathEffectStatus.UNAVAILABLE
    assert timeline.life_transitions == ()
    assert len(SnapshotBuilder().final(timeline, result.config).alive_players) == 2
    assert timeline.availability.alive_state.status is TemporalAvailabilityStatus.PARTIAL
    assert result.summary.death_events_without_victim == 1
    assert any("death_effect_unavailable" in warning for warning in result.warnings)


def test_same_tick_bomb_effects_distinguish_independence_and_conflict(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-same-tick-bomb")
    plant = dataset.bomb_events[0].model_copy(update={"tick": 120})
    independent = TemporalEngine().compute(
        _input(dataset).model_copy(update={"bomb_events": (plant,)})
    )
    assert (
        independent.timelines[0].simultaneous_groups[0].final_state_status
        is FinalStateStatus.DETERMINISTIC
    )

    defuse = plant.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "bomb:same-tick-defuse"),
            "event_type": "defused",
            "source_event": "bomb_defused",
        }
    )
    ambiguous = TemporalEngine().compute(
        _input(dataset).model_copy(update={"kills": (), "bomb_events": (plant, defuse)})
    )
    assert (
        ambiguous.timelines[0].simultaneous_groups[0].final_state_status
        is FinalStateStatus.AMBIGUOUS
    )

    explode = defuse.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "bomb:same-tick-explode"),
            "event_type": "exploded",
            "source_event": "bomb_exploded",
        }
    )
    conflicting = TemporalEngine().compute(
        _input(dataset).model_copy(update={"kills": (), "bomb_events": (defuse, explode)})
    )
    assert (
        conflicting.timelines[0].simultaneous_groups[0].final_state_status
        is FinalStateStatus.CONFLICTING
    )


def test_round_end_same_tick_as_bomb_resolution_has_deterministic_post_group(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-bomb-round-end-group")
    plant = dataset.bomb_events[0]
    end_tick = dataset.rounds[0].end_tick
    assert end_tick is not None
    defuse = plant.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "bomb:defuse-at-round-end"),
            "tick": end_tick,
            "event_type": "defused",
            "source_event": "bomb_defused",
        }
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(update={"bomb_events": (plant, defuse)})
    )
    group = next(item for item in result.timelines[0].simultaneous_groups if item.tick == end_tick)

    assert group.final_state_status is FinalStateStatus.DETERMINISTIC
    assert group.post_group_snapshot_deterministic is True
    assert result.timelines[0].final_bomb_state is BombState.DEFUSED


def test_snapshots_before_and_after_death_are_reproducible(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-snapshot")
    result = TemporalEngine().compute(_input(dataset))
    timeline = result.timelines[0]
    victim_id = dataset.kills[0].victim_player_id
    assert victim_id is not None
    builder = SnapshotBuilder()

    start = builder.at_tick(timeline, 100, result.config)
    before = builder.before_event(timeline, dataset.kills[0].event_id, result.config)
    after = builder.after_event(timeline, dataset.kills[0].event_id, result.config)
    arbitrary = builder.at_tick(timeline, 121, result.config)
    final = builder.final(timeline, result.config)

    assert start.phase is RoundPhase.FREEZE_TIME
    assert victim_id in before.alive_players
    assert victim_id in after.dead_players
    assert arbitrary == builder.at_tick(timeline, 121, result.config)
    assert final.bomb_state is BombState.ROUND_ENDED_BEFORE_RESOLUTION
    with pytest.raises(ValueError, match="before round start"):
        builder.at_tick(timeline, 99, result.config)


@pytest.mark.parametrize(
    ("terminal_type", "expected"),
    [("defused", BombState.DEFUSED), ("exploded", BombState.EXPLODED)],
)
def test_bomb_plant_terminal_sequences(
    canonical_dataset_factory: Any,
    terminal_type: str,
    expected: BombState,
) -> None:
    dataset = canonical_dataset_factory(f"temporal-bomb-{terminal_type}")
    plant = dataset.bomb_events[0]
    terminal = plant.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, f"bomb:{terminal_type}"),
            "tick": 160,
            "event_type": terminal_type,
            "source_event": f"bomb_{terminal_type}",
            "side": Side.CT if terminal_type == "defused" else Side.T,
        }
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(update={"bomb_events": (terminal, plant)})
    )

    assert result.timelines[0].final_bomb_state is expected


def test_invalid_and_conflicting_bomb_sequences_are_unresolved(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-bomb-conflict")
    plant = dataset.bomb_events[0]
    defuse = plant.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "bomb:defuse"),
            "tick": 130,
            "event_type": "defused",
            "source_event": "bomb_defused",
        }
    )
    explode = defuse.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "bomb:explode"),
            "event_type": "exploded",
            "source_event": "bomb_exploded",
        }
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(update={"bomb_events": (defuse, explode, plant)})
    )
    timeline = result.timelines[0]

    assert timeline.final_bomb_state is BombState.UNRESOLVED
    assert any(item.code == "bomb_state_conflict" for item in timeline.validation_issues)
    terminal_events = [
        item
        for item in timeline.ordered_events
        if item.event_type in {"bomb:defused", "bomb:exploded"}
    ]
    assert all(
        item.ordering_status is TemporalOrderingStatus.SIMULTANEOUS_AMBIGUOUS
        for item in terminal_events
    )


def test_missing_freeze_end_and_incomplete_round_are_partial(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-partial")
    incomplete = dataset.rounds[0].model_copy(
        update={
            "freeze_end_tick": None,
            "end_tick": None,
            "official_end_tick": None,
            "is_complete": False,
            "end_source": None,
        }
    )
    timeline = (
        TemporalEngine()
        .compute(_input(dataset).model_copy(update={"rounds": (incomplete,)}))
        .timelines[0]
    )

    assert timeline.live_start_tick is None
    assert timeline.phase_intervals[0].phase is RoundPhase.UNKNOWN
    assert timeline.availability.phase_timeline.status is TemporalAvailabilityStatus.UNAVAILABLE
    assert timeline.availability.final_state.status is TemporalAvailabilityStatus.UNAVAILABLE


def test_fallback_end_is_preserved_and_authoritatively_inferred(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-fallback")
    fallback = dataset.rounds[0].model_copy(
        update={
            "official_end_tick": None,
            "end_source": "fallback:cs_win_panel_match",
        }
    )
    timeline = (
        TemporalEngine()
        .compute(_input(dataset).model_copy(update={"rounds": (fallback,)}))
        .timelines[0]
    )

    assert timeline.end_source == "fallback:cs_win_panel_match"
    assert any(item.kind is TemporalEventKind.FALLBACK_END for item in timeline.ordered_events)
    assert timeline.phase_intervals[-1].phase is RoundPhase.ENDED


def test_event_observation_does_not_invent_initial_alive_state(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-event-participant")
    result = TemporalEngine().compute(_input(dataset).model_copy(update={"memberships": ()}))
    states = result.timelines[0].participants

    assert len(states) == 2
    assert all(item.participation_status is ParticipationStatus.EVENT_OBSERVED for item in states)
    assert all(item.initial_alive_status is PlayerLifeStatus.UNKNOWN for item in states)
    assert (
        result.timelines[0].availability.alive_state.status
        is TemporalAvailabilityStatus.UNAVAILABLE
    )


def test_player_without_evidence_is_not_participating(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-nonparticipant")
    extra_id = uuid5(dataset.match.match_id, "player:bench")
    extra = CanonicalPlayer(
        player_id=extra_id,
        steam_id="76561198000000999",
        current_name="Bench",
        known_names=("Bench",),
    )
    timeline = (
        TemporalEngine()
        .compute(_input(dataset).model_copy(update={"players": (*dataset.players, extra)}))
        .timelines[0]
    )
    bench = next(item for item in timeline.participants if item.player_id == extra_id)

    assert bench.participation_status is ParticipationStatus.NOT_PARTICIPATING
    assert bench.initial_alive_status is PlayerLifeStatus.NOT_PARTICIPATING


def test_duplicate_death_is_anomaly_and_not_respawn(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-duplicate-death")
    original = dataset.kills[0]
    duplicate = original.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:duplicate"),
            "tick": 125,
        }
    )
    timeline = (
        TemporalEngine()
        .compute(_input(dataset).model_copy(update={"kills": (duplicate, original)}))
        .timelines[0]
    )

    assert timeline.life_transitions[-1].before is PlayerLifeStatus.DEAD
    assert (
        timeline.life_transitions[-1].death_classification is TemporalDeathClassification.REPEATED
    )
    assert any(
        item.code == "duplicate_death_without_respawn" for item in timeline.validation_issues
    )


def test_out_of_range_death_does_not_change_final_life_state(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-out-of-range")
    late = dataset.kills[0].model_copy(update={"tick": 201, "phase": EventPhase.POST_ROUND})
    timeline = (
        TemporalEngine().compute(_input(dataset).model_copy(update={"kills": (late,)})).timelines[0]
    )
    victim = late.victim_player_id
    assert victim is not None

    assert timeline.ordered_events[-1].ordering_status is TemporalOrderingStatus.OUT_OF_RANGE
    assert timeline.life_transitions == ()
    final = SnapshotBuilder().final(timeline, TemporalConfig())
    assert victim in final.alive_players
    assert any(item.code == "out_of_range_temporal_events" for item in timeline.validation_issues)


def test_config_or_canonical_fingerprint_change_changes_temporal_fingerprint(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-fingerprint")
    data = _input(dataset)
    base = TemporalEngine().compute(data)
    config_changed = TemporalEngine().compute(
        data, TemporalConfig(tickrate=64, tickrate_source="canonical:test")
    )
    canonical_changed = TemporalEngine().compute(
        data.model_copy(update={"dataset_fingerprint": "f" * 64})
    )

    assert base.temporal_fingerprint != config_changed.temporal_fingerprint
    assert base.temporal_fingerprint != canonical_changed.temporal_fingerprint
