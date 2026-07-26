"""Deterministic direct-trade matching."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from stratweb.application.canonical_models import CanonicalKill, CanonicalRound

from .definitions import ClassifiedKill, Participant
from .models import AnalyticsConfig, TimeConversionStatus, TradeEvent, TradeWindowMode


@dataclass(frozen=True, slots=True)
class TradeRoundResult:
    opportunities: tuple[UUID, ...]
    opportunity_teams: dict[UUID, UUID]
    closed_originals: frozenset[UUID]
    events: tuple[TradeEvent, ...]


def trades_for_round(
    round_item: CanonicalRound,
    kills: tuple[ClassifiedKill, ...],
    participants: dict[UUID, Participant],
    config: AnalyticsConfig,
) -> TradeRoundResult:
    first_death: dict[UUID, UUID] = {}
    for item in kills:
        victim_id = item.event.victim_player_id
        if victim_id in participants and victim_id is not None:
            first_death.setdefault(victim_id, item.event.event_id)
    valid = tuple(
        item.event
        for item in kills
        if item.is_valid_enemy
        and item.event.victim_player_id is not None
        and first_death.get(item.event.victim_player_id) == item.event.event_id
    )
    opportunity_ids = tuple(item.event_id for item in valid)
    opportunity_teams = {
        item.event_id: item.victim_team_id for item in valid if item.victim_team_id is not None
    }
    window = config.resolved_trade_window_ticks
    if window is None:
        return TradeRoundResult(opportunity_ids, opportunity_teams, frozenset(), ())

    closed: set[UUID] = set()
    used_trade_kills: set[UUID] = set()
    events: list[TradeEvent] = []
    for trade_kill in valid:
        if trade_kill.event_id in used_trade_kills:
            continue
        candidates = [
            original
            for original in valid
            if original.event_id not in closed
            and original.event_id != trade_kill.event_id
            and _ordered_before(original, trade_kill)
            and trade_kill.tick - original.tick <= window
            and original.attacker_player_id == trade_kill.victim_player_id
            and original.victim_team_id == trade_kill.attacker_team_id
            and original.attacker_team_id == trade_kill.victim_team_id
        ]
        if not candidates:
            continue
        original = max(candidates, key=lambda item: (item.tick, str(item.event_id)))
        if (
            trade_kill.attacker_player_id is None
            or original.victim_player_id is None
            or original.attacker_player_id is None
        ):
            continue
        trader = participants.get(trade_kill.attacker_player_id)
        if trader is None:
            continue
        delta = trade_kill.tick - original.tick
        seconds_available = config.trade_window.mode is TradeWindowMode.SECONDS
        seconds_delta = (
            delta / config.trade_window.tickrate
            if seconds_available and config.trade_window.tickrate is not None
            else None
        )
        events.append(
            TradeEvent(
                match_id=round_item.match_id,
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                traded_kill_event_id=trade_kill.event_id,
                original_kill_event_id=original.event_id,
                trader_player_id=trade_kill.attacker_player_id,
                traded_player_id=original.victim_player_id,
                traded_enemy_player_id=original.attacker_player_id,
                tick_delta=delta,
                seconds_delta=seconds_delta,
                seconds_delta_status=(
                    TimeConversionStatus.AVAILABLE
                    if seconds_available
                    else TimeConversionStatus.UNAVAILABLE
                ),
                seconds_delta_source=(
                    config.trade_window.tickrate_source if seconds_available else None
                ),
                team_id=trader.team_id,
                side=trader.side,
            )
        )
        closed.add(original.event_id)
        used_trade_kills.add(trade_kill.event_id)
    return TradeRoundResult(
        opportunities=opportunity_ids,
        opportunity_teams=opportunity_teams,
        closed_originals=frozenset(closed),
        events=tuple(events),
    )


def _ordered_before(first: CanonicalKill, second: CanonicalKill) -> bool:
    return (first.tick, str(first.event_id)) < (
        second.tick,
        str(second.event_id),
    )
