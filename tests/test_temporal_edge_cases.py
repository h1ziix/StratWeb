from __future__ import annotations

from typing import Any
from uuid import uuid5

import pytest

from stratweb.application.canonical_models import (
    CanonicalMatchDataset,
    CanonicalPlayer,
    EventPhase,
    PlayerTeamMembership,
)
from stratweb.domain.enums import Side
from stratweb.temporal.engine import TemporalEngine
from stratweb.temporal.models import (
    BombState,
    ParticipationStatus,
    PlayerLifeStatus,
    TemporalDeathClassification,
    TemporalMatchInput,
    TemporalOrderingStatus,
    TemporalTransitionStatus,
)
from stratweb.temporal.snapshots import SnapshotBuilder
from stratweb.temporal.validation import TemporalValidator


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


def _roster_input(
    dataset: CanonicalMatchDataset, *, missing_membership: bool
) -> TemporalMatchInput:
    players = list(dataset.players)
    memberships = list(dataset.player_team_memberships)
    for index in range(8):
        player_id = uuid5(dataset.match.match_id, f"roster-player:{index}")
        team = dataset.teams[index // 4]
        side = Side.T if index < 4 else Side.CT
        players.append(
            CanonicalPlayer(
                player_id=player_id,
                steam_id=str(76561198000100000 + index),
                current_name=f"Roster {index}",
                known_names=(f"Roster {index}",),
            )
        )
        if not (missing_membership and index == 7):
            memberships.append(
                PlayerTeamMembership(
                    player_id=player_id,
                    team_id=team.team_id,
                    side=side,
                    valid_from_tick=100,
                    source="fixture:round_roster",
                    confidence=1,
                )
            )
    return _input(dataset).model_copy(
        update={"players": tuple(players), "memberships": tuple(memberships)}
    )


@pytest.mark.parametrize(("missing_membership", "expected"), [(False, 10), (True, 9)])
def test_participant_rosters_support_5v5_and_4v5_without_assumption(
    canonical_dataset_factory: Any,
    missing_membership: bool,
    expected: int,
) -> None:
    dataset = canonical_dataset_factory(f"temporal-roster-{expected}")
    timeline = (
        TemporalEngine()
        .compute(_roster_input(dataset, missing_membership=missing_membership))
        .timelines[0]
    )

    participating = tuple(
        item
        for item in timeline.participants
        if item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
    )
    assert len(participating) == expected
    assert sum(item.side is Side.T for item in participating) == 5
    assert sum(item.side is Side.CT for item in participating) == expected - 5


def test_substitution_is_derived_per_round_from_membership(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-substitution")
    first = dataset.rounds[0]
    second = first.model_copy(
        update={
            "round_id": uuid5(dataset.match.match_id, "round:2"),
            "round_number": 2,
            "start_tick": 300,
            "freeze_end_tick": 310,
            "end_tick": 390,
            "official_end_tick": 400,
        }
    )
    replaced = dataset.players[1]
    replacement_id = uuid5(dataset.match.match_id, "player:replacement")
    replacement = CanonicalPlayer(
        player_id=replacement_id,
        steam_id="76561198000199999",
        current_name="Replacement",
        known_names=("Replacement",),
    )
    memberships = (
        dataset.player_team_memberships[0],
        dataset.player_team_memberships[1].model_copy(update={"valid_to_tick": 200}),
        PlayerTeamMembership(
            player_id=replacement_id,
            team_id=dataset.teams[1].team_id,
            side=Side.CT,
            valid_from_tick=300,
            source="fixture:substitution",
            confidence=1,
        ),
    )
    result = TemporalEngine().compute(
        _input(dataset).model_copy(
            update={
                "players": (*dataset.players, replacement),
                "memberships": memberships,
                "rounds": (first, second),
            }
        )
    )
    first_states = {item.player_id: item for item in result.timelines[0].participants}
    second_states = {item.player_id: item for item in result.timelines[1].participants}

    assert first_states[replaced.player_id].initial_alive_status is PlayerLifeStatus.ALIVE
    assert (
        first_states[replacement_id].participation_status is ParticipationStatus.NOT_PARTICIPATING
    )
    assert (
        second_states[replaced.player_id].participation_status
        is ParticipationStatus.NOT_PARTICIPATING
    )
    assert second_states[replacement_id].initial_alive_status is PlayerLifeStatus.ALIVE


def test_unknown_player_id_is_retained_as_event_observed_partial_participant(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-unknown-player")
    unknown_id = uuid5(dataset.match.match_id, "player:unknown")
    shot = dataset.shots[0].model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "shot:unknown"),
            "player_id": unknown_id,
        }
    )
    timeline = (
        TemporalEngine()
        .compute(_input(dataset).model_copy(update={"shots": (*dataset.shots, shot)}))
        .timelines[0]
    )
    state = next(item for item in timeline.participants if item.player_id == unknown_id)

    assert state.participation_status is ParticipationStatus.EVENT_OBSERVED
    assert state.initial_alive_status is PlayerLifeStatus.UNKNOWN


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({}, TemporalDeathClassification.ENEMY),
        ({"is_teamkill": True}, TemporalDeathClassification.TEAMKILL),
        ({"is_suicide": True}, TemporalDeathClassification.SUICIDE),
        (
            {"attacker_player_id": None, "attacker_team_id": None},
            TemporalDeathClassification.WORLD,
        ),
    ],
)
def test_death_classifications_all_move_the_victim_to_dead(
    canonical_dataset_factory: Any,
    updates: dict[str, object],
    expected: TemporalDeathClassification,
) -> None:
    dataset = canonical_dataset_factory(f"temporal-death-{expected.value}")
    kill = dataset.kills[0].model_copy(update=updates)
    timeline = (
        TemporalEngine().compute(_input(dataset).model_copy(update={"kills": (kill,)})).timelines[0]
    )

    assert timeline.life_transitions[0].death_classification is expected
    assert timeline.life_transitions[0].after is PlayerLifeStatus.DEAD


def test_death_before_live_is_partial_and_warned(canonical_dataset_factory: Any) -> None:
    dataset = canonical_dataset_factory("temporal-death-before-live")
    kill = dataset.kills[0].model_copy(update={"tick": 105, "phase": EventPhase.FREEZE_TIME})
    timeline = (
        TemporalEngine().compute(_input(dataset).model_copy(update={"kills": (kill,)})).timelines[0]
    )

    assert timeline.life_transitions[0].status is TemporalTransitionStatus.PARTIAL
    assert any(item.code == "death_before_live_start" for item in timeline.validation_issues)


def test_unknown_participant_death_is_preserved_with_partial_life_coverage(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-unknown-victim")
    unknown_id = uuid5(dataset.match.match_id, "player:unknown-victim")
    kill = dataset.kills[0].model_copy(
        update={
            "victim_player_id": unknown_id,
            "victim_team_id": dataset.teams[1].team_id,
            "victim_side": Side.CT,
        }
    )
    timeline = (
        TemporalEngine().compute(_input(dataset).model_copy(update={"kills": (kill,)})).timelines[0]
    )

    transition = timeline.life_transitions[0]
    assert transition.player_id == unknown_id
    assert transition.before is PlayerLifeStatus.UNKNOWN
    assert transition.after is PlayerLifeStatus.DEAD
    assert transition.status is TemporalTransitionStatus.PARTIAL


def test_round_without_deaths_keeps_proven_participants_alive(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-no-deaths")
    result = TemporalEngine().compute(_input(dataset).model_copy(update={"kills": ()}))
    timeline = result.timelines[0]
    final = SnapshotBuilder().final(timeline, result.config)

    assert timeline.life_transitions == ()
    assert len(final.alive_players) == 2
    assert final.dead_players == ()


@pytest.mark.parametrize("terminal_type", ["defused", "exploded"])
def test_bomb_terminal_before_plant_is_unresolved(
    canonical_dataset_factory: Any,
    terminal_type: str,
) -> None:
    dataset = canonical_dataset_factory(f"temporal-{terminal_type}-before-plant")
    terminal = dataset.bomb_events[0].model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, f"bomb:{terminal_type}"),
            "tick": 130,
            "event_type": terminal_type,
            "source_event": f"bomb_{terminal_type}",
        }
    )
    timeline = (
        TemporalEngine()
        .compute(_input(dataset).model_copy(update={"bomb_events": (terminal,)}))
        .timelines[0]
    )

    assert timeline.final_bomb_state is BombState.UNRESOLVED
    assert timeline.bomb_transitions[0].status is TemporalTransitionStatus.UNRESOLVED
    assert any(item.code == "bomb_state_conflict" for item in timeline.validation_issues)


def test_bomb_plant_preserves_unknown_actor_team_and_unmapped_site(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-bomb-raw")
    plant = dataset.bomb_events[0].model_copy(
        update={"player_id": None, "team_id": None, "side": Side.UNKNOWN, "site_raw": "mystery"}
    )
    transition = (
        TemporalEngine()
        .compute(_input(dataset).model_copy(update={"bomb_events": (plant,)}))
        .timelines[0]
        .bomb_transitions[0]
    )

    assert transition.actor_player_id is None
    assert transition.physical_team_id is None
    assert transition.side is Side.UNKNOWN
    assert transition.site_raw == "mystery"


def test_same_tick_plant_and_defuse_are_marked_ambiguous(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-same-tick-bomb")
    plant = dataset.bomb_events[0]
    defuse = plant.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "bomb:defuse"),
            "event_type": "defused",
            "source_event": "bomb_defused",
        }
    )
    timeline = (
        TemporalEngine()
        .compute(_input(dataset).model_copy(update={"bomb_events": (defuse, plant)}))
        .timelines[0]
    )
    state_events = [
        item
        for item in timeline.ordered_events
        if item.event_type in {"bomb:planted", "bomb:defused"}
    ]

    assert len({item.simultaneous_group_id for item in state_events}) == 1
    assert all(
        item.ordering_status is TemporalOrderingStatus.SIMULTANEOUS_AMBIGUOUS
        for item in state_events
    )


def test_snapshot_does_not_inherit_ambiguity_from_future_tick(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-future-ambiguity")
    first = dataset.kills[0].model_copy(update={"tick": 160})
    second = first.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:future-second"),
            "attacker_player_id": first.victim_player_id,
            "victim_player_id": first.attacker_player_id,
        }
    )
    result = TemporalEngine().compute(_input(dataset).model_copy(update={"kills": (first, second)}))
    builder = SnapshotBuilder()

    assert builder.at_tick(result.timelines[0], 120, result.config).ambiguity_flags == ()
    assert builder.at_tick(result.timelines[0], 160, result.config).ambiguity_flags == (
        "simultaneous_event_order",
    )
    with pytest.raises(ValueError, match="after effective round end"):
        builder.at_tick(result.timelines[0], 201, result.config)


def test_invalid_boundaries_and_duplicate_event_ids_are_fatal_validation(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-structural-validation")
    invalid_round = dataset.rounds[0].model_copy(update={"freeze_end_tick": 90})
    duplicated_shot = dataset.shots[0].model_copy(update={"event_id": dataset.damages[0].event_id})
    timeline = (
        TemporalEngine()
        .compute(
            _input(dataset).model_copy(
                update={"rounds": (invalid_round,), "shots": (duplicated_shot,)}
            )
        )
        .timelines[0]
    )
    fatal_codes = {item.code for item in timeline.validation_issues if item.is_fatal}

    assert "invalid_phase_interval" in fatal_codes
    assert "duplicate_temporal_event_id" in fatal_codes


def test_conflicting_team_side_evidence_is_explicitly_unresolved(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-identity-conflict")
    shot = dataset.shots[0].model_copy(
        update={"team_id": dataset.teams[1].team_id, "side": Side.CT}
    )
    timeline = (
        TemporalEngine().compute(_input(dataset).model_copy(update={"shots": (shot,)})).timelines[0]
    )
    actor = next(item for item in timeline.participants if item.player_id == shot.player_id)

    assert actor.participation_status is ParticipationStatus.UNRESOLVED
    assert actor.physical_team_id == dataset.teams[0].team_id
    assert actor.side is Side.T
    assert timeline.availability.participant_state.status.value == "unresolved"
    assert any(item.code == "participant_identity_conflict" for item in timeline.validation_issues)


def test_validator_detects_impossible_life_transition_and_final_mismatch(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("temporal-validator-state")
    result = TemporalEngine().compute(_input(dataset))
    timeline = result.timelines[0]
    impossible = timeline.life_transitions[0].model_copy(update={"before": PlayerLifeStatus.DEAD})
    broken = timeline.model_copy(update={"life_transitions": (impossible,)})
    final = SnapshotBuilder().final(timeline, result.config)
    victim_id = timeline.life_transitions[0].player_id
    mismatched_final = final.model_copy(
        update={
            "alive_players": (*final.alive_players, victim_id),
            "dead_players": (),
        }
    )

    transition_codes = {item.code for item in TemporalValidator().validate(broken)}
    final_codes = {item.code for item in TemporalValidator().validate(timeline, mismatched_final)}
    assert "impossible_life_transition" in transition_codes
    assert "final_life_state_mismatch" in final_codes
