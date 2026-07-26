"""Opening-duel extraction from valid enemy kills."""

from __future__ import annotations

from uuid import UUID

from stratweb.application.canonical_models import CanonicalRound

from .definitions import ClassifiedKill, Participant, winner_team_id
from .models import AnalyticsConfig, OpeningDuel, TradeWindowMode


def opening_duel_for_round(
    round_item: CanonicalRound,
    kills: tuple[ClassifiedKill, ...],
    participants: dict[UUID, Participant],
    config: AnalyticsConfig,
) -> OpeningDuel | None:
    first = next((item.event for item in kills if item.is_valid_enemy), None)
    if first is None or first.attacker_player_id is None or first.victim_player_id is None:
        return None
    killer = participants.get(first.attacker_player_id)
    victim = participants.get(first.victim_player_id)
    if killer is None or victim is None:
        return None
    winner = winner_team_id(round_item)
    seconds = None
    if (
        config.trade_window.mode is TradeWindowMode.SECONDS
        and config.trade_window.tickrate is not None
        and round_item.freeze_end_tick is not None
    ):
        seconds = max(
            0.0,
            (first.tick - round_item.freeze_end_tick) / config.trade_window.tickrate,
        )
    return OpeningDuel(
        match_id=round_item.match_id,
        round_id=round_item.round_id,
        round_number=round_item.round_number,
        opening_killer_player_id=first.attacker_player_id,
        opening_victim_player_id=first.victim_player_id,
        killer_team_id=killer.team_id,
        victim_team_id=victim.team_id,
        killer_side=killer.side,
        victim_side=victim.side,
        tick=first.tick,
        relative_tick=first.relative_tick,
        event_id=first.event_id,
        round_winner=round_item.winner_side if winner is not None else None,
        opening_team_won_round=(killer.team_id == winner) if winner is not None else None,
        seconds_from_freeze_end=seconds,
    )
