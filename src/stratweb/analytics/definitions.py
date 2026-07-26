"""Shared deterministic definitions and arithmetic for analytics V1."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from stratweb.application.canonical_models import (
    CanonicalKill,
    CanonicalRound,
    EventPhase,
    PlayerTeamMembership,
)
from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side

from .models import AnalyticsConfig, MultikillCategory


@dataclass(frozen=True, slots=True)
class Participant:
    player_id: UUID
    team_id: UUID
    side: Side


@dataclass(frozen=True, slots=True)
class ClassifiedKill:
    event: CanonicalKill
    classification: str

    @property
    def is_valid_enemy(self) -> bool:
        return self.classification == "enemy"


def config_hash(config: AnalyticsConfig) -> str:
    return hashlib.sha256(canonical_json(config.model_dump(mode="json")).encode()).hexdigest()


def eligible_rounds(rounds: tuple[CanonicalRound, ...]) -> tuple[CanonicalRound, ...]:
    return tuple(
        sorted(
            (item for item in rounds if item.is_complete and not item.is_warmup),
            key=lambda item: (item.round_number, str(item.round_id)),
        )
    )


def participants_by_round(
    rounds: tuple[CanonicalRound, ...],
    memberships: tuple[PlayerTeamMembership, ...],
) -> tuple[dict[UUID, Participant], ...]:
    ordered = eligible_rounds(rounds)
    result: list[dict[UUID, Participant]] = []
    for index, round_item in enumerate(ordered):
        if round_item.start_tick is None:
            result.append({})
            continue
        next_start = ordered[index + 1].start_tick if index + 1 < len(ordered) else None
        observed_end = _round_end(round_item)
        end_tick = (
            observed_end
            if observed_end > round_item.start_tick
            else next_start - 1
            if next_start is not None
            else observed_end
        )
        candidates: dict[UUID, set[tuple[UUID, Side]]] = {}
        for membership in memberships:
            if membership.team_id is None:
                continue
            if membership.team_id == round_item.t_team_id:
                side = Side.T
            elif membership.team_id == round_item.ct_team_id:
                side = Side.CT
            else:
                continue
            if membership.valid_from_tick > end_tick:
                continue
            if (
                membership.valid_to_tick is not None
                and membership.valid_to_tick < round_item.start_tick
            ):
                continue
            candidates.setdefault(membership.player_id, set()).add((membership.team_id, side))
        result.append(
            {
                player_id: Participant(player_id, next(iter(values))[0], next(iter(values))[1])
                for player_id, values in candidates.items()
                if len(values) == 1
            }
        )
    return tuple(result)


def classify_kill(
    event: CanonicalKill,
    participants: dict[UUID, Participant],
) -> ClassifiedKill:
    victim = participants.get(event.victim_player_id) if event.victim_player_id else None
    attacker = participants.get(event.attacker_player_id) if event.attacker_player_id else None
    if victim is None:
        return ClassifiedKill(event, "invalid")
    if event.is_suicide is True or event.attacker_player_id == event.victim_player_id:
        return ClassifiedKill(event, "suicide")
    if attacker is None:
        return ClassifiedKill(event, "world")
    same_team = attacker.team_id == victim.team_id
    if event.is_teamkill is True or same_team:
        return ClassifiedKill(event, "teamkill")
    if (
        event.attacker_team_id is None
        or event.victim_team_id is None
        or event.attacker_team_id != attacker.team_id
        or event.victim_team_id != victim.team_id
        or event.attacker_team_id == event.victim_team_id
    ):
        return ClassifiedKill(event, "invalid")
    return ClassifiedKill(event, "enemy")


def ordered_round_kills(
    kills: tuple[CanonicalKill, ...],
    round_item: CanonicalRound,
    participants: dict[UUID, Participant],
) -> tuple[ClassifiedKill, ...]:
    return tuple(
        classify_kill(event, participants)
        for event in sorted(
            (
                event
                for event in kills
                if event.round_id == round_item.round_id
                and event.round_number == round_item.round_number
                and event.phase is EventPhase.LIVE
            ),
            key=lambda event: (event.tick, str(event.event_id)),
        )
    )


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def percentage(numerator: int, denominator: int) -> float | None:
    return numerator * 100.0 / denominator if denominator > 0 else None


def multikill_category(kills: int) -> MultikillCategory:
    if kills <= 0:
        return MultikillCategory.ZERO
    if kills == 1:
        return MultikillCategory.ONE
    if kills == 2:
        return MultikillCategory.TWO
    if kills == 3:
        return MultikillCategory.THREE
    if kills == 4:
        return MultikillCategory.FOUR
    if kills == 5:
        return MultikillCategory.FIVE
    return MultikillCategory.FIVE_PLUS


def side_for_team(round_item: CanonicalRound, team_id: UUID) -> Side | None:
    if team_id == round_item.t_team_id:
        return Side.T
    if team_id == round_item.ct_team_id:
        return Side.CT
    return None


def winner_team_id(round_item: CanonicalRound) -> UUID | None:
    if not round_item.outcome_status.is_available:
        return None
    if round_item.winner_side is Side.T:
        return round_item.t_team_id
    if round_item.winner_side is Side.CT:
        return round_item.ct_team_id
    return None


def _round_end(round_item: CanonicalRound) -> int:
    return (
        round_item.official_end_tick
        or round_item.end_tick
        or round_item.freeze_end_tick
        or round_item.start_tick
        or 0
    )
