"""Canonical-event projection and deterministic cross-family ordering."""

from __future__ import annotations

from uuid import UUID, uuid5

from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGameplayEvent,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalRound,
    CanonicalShot,
    EventPhase,
)
from stratweb.domain.enums import Side

from .alive_state import classify_death
from .definitions import first_available_tick, temporal_time
from .models import (
    TemporalConfig,
    TemporalDeathClassification,
    TemporalEvent,
    TemporalEventKind,
    TemporalOrderingStatus,
)

EVENT_PRIORITY: dict[str, int] = {
    "phase_boundary": 10,
    "damage": 20,
    "shot": 30,
    "grenade": 40,
    "bomb_planted": 50,
    "death": 60,
    "bomb_defused": 70,
    "bomb_exploded": 70,
    "bomb_other": 75,
    "round_end": 90,
    "official_end": 100,
}


def ordered_temporal_events(
    round_item: CanonicalRound,
    *,
    kills: tuple[CanonicalKill, ...],
    damages: tuple[CanonicalDamage, ...],
    shots: tuple[CanonicalShot, ...],
    grenades: tuple[CanonicalGrenade, ...],
    bomb_events: tuple[CanonicalBombEvent, ...],
    config: TemporalConfig,
) -> tuple[TemporalEvent, ...]:
    projected = [*_boundary_events(round_item, config)]
    projected.extend(_kill_event(item, config) for item in kills if _belongs(item, round_item))
    projected.extend(_damage_event(item, config) for item in damages if _belongs(item, round_item))
    projected.extend(_shot_event(item, config) for item in shots if _belongs(item, round_item))
    projected.extend(
        _grenade_event(item, config) for item in grenades if _belongs(item, round_item)
    )
    projected.extend(
        _bomb_event(item, config) for item in bomb_events if _belongs(item, round_item)
    )

    effective_end = first_available_tick(round_item.official_end_tick, round_item.end_tick)
    ranged = [
        item.model_copy(update={"ordering_status": TemporalOrderingStatus.OUT_OF_RANGE})
        if (
            (round_item.start_tick is not None and item.time.tick < round_item.start_tick)
            or (effective_end is not None and item.time.tick > effective_end)
        )
        else item
        for item in projected
    ]
    return tuple(sorted(ranged, key=temporal_event_key))


def temporal_event_key(event: TemporalEvent) -> tuple[int, int, int, str]:
    return event.round_number, event.time.tick, event.priority, str(event.event_id)


def _belongs(event: CanonicalGameplayEvent, round_item: CanonicalRound) -> bool:
    return event.round_id == round_item.round_id and event.round_number == round_item.round_number


def _boundary_events(
    round_item: CanonicalRound, config: TemporalConfig
) -> tuple[TemporalEvent, ...]:
    events: list[TemporalEvent] = []
    if round_item.start_tick is not None:
        events.append(
            _synthetic_event(
                round_item,
                config,
                tick=round_item.start_tick,
                label="round_start",
                source=round_item.start_source or "canonical:round_start",
                kind=TemporalEventKind.PHASE_BOUNDARY,
                priority=EVENT_PRIORITY["phase_boundary"],
            )
        )
    if round_item.freeze_end_tick is not None:
        events.append(
            _synthetic_event(
                round_item,
                config,
                tick=round_item.freeze_end_tick,
                label="freeze_end",
                source="canonical:freeze_end_tick",
                kind=TemporalEventKind.PHASE_BOUNDARY,
                priority=EVENT_PRIORITY["phase_boundary"],
            )
        )
    if round_item.end_tick is not None:
        fallback = (round_item.end_source or "").startswith("fallback:")
        kind = TemporalEventKind.FALLBACK_END if fallback else TemporalEventKind.ROUND_END
        label = "fallback_end" if fallback else "round_end"
        if (
            round_item.official_end_tick == round_item.end_tick
            and not fallback
            and round_item.end_source == "round_officially_ended"
        ):
            kind = TemporalEventKind.OFFICIAL_END
            label = "official_end"
        events.append(
            _synthetic_event(
                round_item,
                config,
                tick=round_item.end_tick,
                label=label,
                source=round_item.end_source or "canonical:round_end",
                kind=kind,
                priority=(
                    EVENT_PRIORITY["official_end"]
                    if kind is TemporalEventKind.OFFICIAL_END
                    else EVENT_PRIORITY["round_end"]
                ),
            )
        )
    if (
        round_item.official_end_tick is not None
        and round_item.official_end_tick != round_item.end_tick
    ):
        events.append(
            _synthetic_event(
                round_item,
                config,
                tick=round_item.official_end_tick,
                label="official_end",
                source="round_officially_ended",
                kind=TemporalEventKind.OFFICIAL_END,
                priority=EVENT_PRIORITY["official_end"],
            )
        )
    return tuple(events)


def _synthetic_event(
    round_item: CanonicalRound,
    config: TemporalConfig,
    *,
    tick: int,
    label: str,
    source: str,
    kind: TemporalEventKind,
    priority: int,
) -> TemporalEvent:
    return TemporalEvent(
        event_id=uuid5(round_item.round_id, f"temporal:event:{label}:{tick}:{source}"),
        match_id=round_item.match_id,
        round_id=round_item.round_id,
        round_number=round_item.round_number,
        time=temporal_time(tick, config),
        kind=kind,
        event_type=label,
        source_event=source,
        canonical_phase=EventPhase.UNKNOWN,
        priority=priority,
        state_affecting=True,
    )


def _base_event(
    event: CanonicalGameplayEvent,
    config: TemporalConfig,
    *,
    kind: TemporalEventKind,
    event_type: str,
    priority: int,
    actor_player_id: UUID | None = None,
    victim_player_id: UUID | None = None,
    physical_team_id: UUID | None = None,
    side: Side = Side.UNKNOWN,
    site_raw: str | int | None = None,
    combat_death_classification: TemporalDeathClassification | None = None,
    state_affecting: bool,
) -> TemporalEvent:
    assert event.round_id is not None and event.round_number is not None
    return TemporalEvent(
        event_id=event.event_id,
        match_id=event.match_id,
        round_id=event.round_id,
        round_number=event.round_number,
        time=temporal_time(event.tick, config),
        kind=kind,
        event_type=event_type,
        source_event=event.source_event,
        canonical_phase=event.phase,
        priority=priority,
        actor_player_id=actor_player_id,
        victim_player_id=victim_player_id,
        physical_team_id=physical_team_id,
        side=side,
        site_raw=site_raw,
        combat_death_classification=combat_death_classification,
        state_affecting=state_affecting,
        warnings=event.warnings,
    )


def _kill_event(event: CanonicalKill, config: TemporalConfig) -> TemporalEvent:
    return _base_event(
        event,
        config,
        kind=TemporalEventKind.DEATH,
        event_type="death",
        priority=EVENT_PRIORITY["death"],
        actor_player_id=event.attacker_player_id,
        victim_player_id=event.victim_player_id,
        physical_team_id=event.attacker_team_id,
        side=event.attacker_side,
        combat_death_classification=classify_death(event),
        state_affecting=True,
    )


def _damage_event(event: CanonicalDamage, config: TemporalConfig) -> TemporalEvent:
    return _base_event(
        event,
        config,
        kind=TemporalEventKind.DAMAGE,
        event_type="damage",
        priority=EVENT_PRIORITY["damage"],
        actor_player_id=event.attacker_player_id,
        victim_player_id=event.victim_player_id,
        physical_team_id=event.attacker_team_id,
        side=event.attacker_side,
        state_affecting=False,
    )


def _shot_event(event: CanonicalShot, config: TemporalConfig) -> TemporalEvent:
    return _base_event(
        event,
        config,
        kind=TemporalEventKind.SHOT,
        event_type="shot",
        priority=EVENT_PRIORITY["shot"],
        actor_player_id=event.player_id,
        physical_team_id=event.team_id,
        side=event.side,
        state_affecting=False,
    )


def _grenade_event(event: CanonicalGrenade, config: TemporalConfig) -> TemporalEvent:
    return _base_event(
        event,
        config,
        kind=TemporalEventKind.GRENADE,
        event_type=f"grenade:{event.lifecycle_event}",
        priority=EVENT_PRIORITY["grenade"],
        actor_player_id=event.player_id,
        physical_team_id=event.team_id,
        side=event.side,
        state_affecting=False,
    )


def _bomb_event(event: CanonicalBombEvent, config: TemporalConfig) -> TemporalEvent:
    priority = EVENT_PRIORITY.get(f"bomb_{event.event_type}", EVENT_PRIORITY["bomb_other"])
    return _base_event(
        event,
        config,
        kind=TemporalEventKind.BOMB,
        event_type=f"bomb:{event.event_type}",
        priority=priority,
        actor_player_id=event.player_id,
        physical_team_id=event.team_id,
        side=event.side,
        site_raw=event.site_raw,
        state_affecting=event.event_type in {"planted", "defused", "exploded"},
    )
