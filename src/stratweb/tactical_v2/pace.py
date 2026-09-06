"""Conservative, source-clock-based pace, approach and opening-AWP observations.

No nominal tick rate, inventory-based weapon attribution or nickname identity fallback.
An approach describes observed corridors near a plant, not a proven tactical intention.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from stratweb.domain.enums import Side
from stratweb.tactical_v2.models import (
    TacticalDamageSample,
    TacticalEvidenceReference,
    TacticalInsightType,
    TacticalKillSample,
    TacticalMatchInput,
    TacticalPlayerSample,
    TacticalRoundInput,
    TacticalShotSample,
)

Contact = TacticalDamageSample | TacticalKillSample
DEPTH_RULE_VERSION = "source_clock_contact_approach_awp_v1"


@dataclass(frozen=True)
class DepthFact:
    kind: TacticalInsightType
    map_name: str
    side: Side
    key: str
    label: str
    population: str
    evidence: TacticalEvidenceReference


def source_tick_seconds(round_item: TacticalRoundInput) -> float | None:
    """Accept a consistent clock fit only, with >=1 second of observed separation."""
    clocks: dict[int, set[float]] = defaultdict(set)
    events: tuple[Contact | TacticalShotSample, ...] = (
        *round_item.kills,
        *round_item.damages,
        *round_item.shots,
    )
    for event in events:
        if event.game_time is not None:
            clocks[event.tick].add(event.game_time)
    if len(clocks) < 2 or any(max(v) - min(v) > 0.002 for v in clocks.values()):
        return None
    ticks = sorted(clocks)
    first, last = ticks[0], ticks[-1]
    start, end = min(clocks[first]), min(clocks[last])
    if end - start < 1:
        return None
    slope = (end - start) / (last - first)
    if not 0.001 <= slope <= 0.1:
        return None
    if any(abs(min(clocks[tick]) - (start + (tick - first) * slope)) > 0.02 for tick in ticks):
        return None
    return slope


def _contacts(round_item: TacticalRoundInput) -> tuple[Contact, ...]:
    selected, opponents = set(round_item.selected_player_ids), set(round_item.opponent_player_ids)
    result: list[Contact] = []
    events: tuple[Contact, ...] = (*round_item.damages, *round_item.kills)
    for event in events:
        if round_item.live_start_tick is None or event.tick < round_item.live_start_tick:
            continue
        if round_item.effective_end_tick is not None and event.tick > round_item.effective_end_tick:
            continue
        if not (
            (event.attacker_player_id in selected and event.victim_player_id in opponents)
            or (event.attacker_player_id in opponents and event.victim_player_id in selected)
        ):
            continue
        if isinstance(event, TacticalDamageSample) and not (
            event.damage_health and event.damage_health > 0
        ):
            continue
        if isinstance(event, TacticalKillSample) and (
            event.is_teamkill is True or event.is_suicide is True
        ):
            continue
        result.append(event)
    return tuple(sorted(result, key=lambda event: (event.tick, str(event.event_id))))


def _recent(
    round_item: TacticalRoundInput,
    player: UUID,
    tick: int,
    seconds: float,
    maximum_age: float = 0.5,
) -> TacticalPlayerSample | None:
    candidates = [
        sample
        for sample in round_item.samples
        if sample.player_id == player
        and sample.side is round_item.side
        and sample.alive is True
        and sample.zone_id
        and 0 <= (tick - sample.tick) * seconds <= maximum_age
    ]
    if not candidates:
        return None
    newest = max(sample.tick for sample in candidates)
    latest = [sample for sample in candidates if sample.tick == newest]
    if len({sample.zone_id for sample in latest}) != 1:
        return None
    return min(latest, key=lambda sample: str(sample.snapshot_id))


def _control_samples(
    round_item: TacticalRoundInput, tick: int, seconds: float
) -> tuple[TacticalPlayerSample, ...]:
    # Simultaneous, distinct non-spawn control zones: walking through two zones is not a split.
    samples = tuple(
        sample
        for player in round_item.selected_player_ids
        if (sample := _recent(round_item, player, tick, seconds)) is not None
    )
    return tuple(
        sample
        for sample in samples
        if sample.zone_id
        and not any(
            word in sample.zone_id.casefold()
            for word in ("spawn", "base", "unknown", "unavailable")
        )
    )


def _site(zone: str | None) -> str | None:
    return {
        "bombsite_a": "A",
        "a_site": "A",
        "site_a": "A",
        "bombsite_b": "B",
        "b_site": "B",
        "site_b": "B",
    }.get(zone or "")


def _evidence(
    round_item: TacticalRoundInput,
    events: tuple[Contact, ...],
    samples: tuple[TacticalPlayerSample, ...],
    *,
    plant: bool = False,
) -> TacticalEvidenceReference:
    ticks = [event.tick for event in events] + [sample.tick for sample in samples]
    event_ids = {event.event_id for event in events}
    clock_events: tuple[Contact | TacticalShotSample, ...] = (
        *round_item.kills,
        *round_item.damages,
        *round_item.shots,
    )
    timed = [event for event in clock_events if event.game_time is not None]
    if timed:
        # Keep source-clock endpoints alongside the tactical event for reproducibility.
        for event in (
            min(timed, key=lambda item: (item.tick, str(item.event_id))),
            max(timed, key=lambda item: (item.tick, str(item.event_id))),
        ):
            event_ids.add(event.event_id)
            ticks.append(event.tick)
    if plant and round_item.plant:
        ticks.append(round_item.plant.tick)
        event_ids.add(round_item.plant.event_id)
    return TacticalEvidenceReference(
        match_id=round_item.match_id,
        round_number=round_item.round_number,
        tick_start=min(ticks),
        tick_end=max(ticks),
        event_ids=tuple(sorted(event_ids, key=str)),
        snapshot_ids=tuple(sorted({sample.snapshot_id for sample in samples}, key=str)),
    )


def compute_depth_facts(matches: tuple[TacticalMatchInput, ...]) -> tuple[DepthFact, ...]:
    facts: list[DepthFact] = []
    for match in matches:
        for round_item in match.rounds:
            if (
                round_item.is_warmup
                or not round_item.is_complete
                or round_item.live_start_tick is None
            ):
                continue
            seconds = source_tick_seconds(round_item)
            contacts = _contacts(round_item)
            if seconds is None:
                continue
            first_tick = contacts[0].tick if contacts else round_item.live_start_tick
            first = tuple(event for event in contacts if event.tick == first_tick)
            elapsed = (first_tick - round_item.live_start_tick) * seconds
            samples = _control_samples(round_item, first_tick, seconds)
            if round_item.side is Side.T and contacts:
                plant_early = (
                    round_item.plant is not None
                    and 0 <= (round_item.plant.tick - round_item.live_start_tick) * seconds < 25
                )
                entry_early = any(_site(sample.zone_id) is not None for sample in samples)
                if elapsed < 25 and (plant_early or entry_early):
                    key, label = "fast_hit", "Быстрый выход на точку: контакт до 0:25"
                elif elapsed < 25:
                    key, label = (
                        "early_contact",
                        "Ранний контакт до 0:25; выход на точку не подтверждён",
                    )
                elif elapsed <= 60 and len({sample.zone_id for sample in samples}) >= 2:
                    key, label = (
                        "default_to_split",
                        "Контакт на 0:25–1:00 после занятия нескольких зон",
                    )
                elif elapsed > 60:
                    key, label = "late_execute", "Поздний первый контакт: после 1:00"
                else:
                    key, label = (
                        "mid_contact",
                        "Контакт на 0:25–1:00; контроль нескольких зон не подтверждён",
                    )
                facts.append(
                    DepthFact(
                        TacticalInsightType.ATTACK_PACE,
                        match.source.map_name,
                        Side.T,
                        key,
                        label,
                        "rounds_with_contact_clock",
                        _evidence(round_item, first, samples, plant=plant_early),
                    )
                )
            if round_item.side is Side.T and match.source.map_name == "de_mirage":
                route = _mirage_approach(round_item, seconds)
                if route is not None:
                    route_key, route_label, route_samples = route
                    facts.append(
                        DepthFact(
                            TacticalInsightType.SITE_HIT,
                            match.source.map_name,
                            Side.T,
                            route_key,
                            route_label,
                            "plants_with_observed_corridors",
                            _evidence(round_item, (), route_samples, plant=True),
                        )
                    )
            # Each selected player's first damage/death contact must itself be an AWP attack.
            for player in round_item.selected_player_ids:
                involved = [
                    event
                    for event in contacts
                    if player in (event.attacker_player_id, event.victim_player_id)
                ]
                shots = tuple(
                    shot
                    for shot in round_item.shots
                    if shot.player_id == player
                    and not _non_gun_action(shot.weapon)
                    and round_item.live_start_tick <= shot.tick
                    and (
                        round_item.effective_end_tick is None
                        or shot.tick <= round_item.effective_end_tick
                    )
                )
                ticks = [event.tick for event in involved] + [shot.tick for shot in shots]
                if not ticks:
                    continue
                tick = min(ticks)
                if (tick - round_item.live_start_tick) * seconds > 12:
                    continue
                simultaneous = tuple(event for event in involved if event.tick == tick)
                awp = tuple(
                    event
                    for event in simultaneous
                    if event.attacker_player_id == player
                    and (event.weapon or "").casefold().removeprefix("weapon_") == "awp"
                )
                awp_shots = tuple(
                    shot
                    for shot in shots
                    if shot.tick == tick
                    and (shot.weapon or "").casefold().removeprefix("weapon_") == "awp"
                )
                weapon_events: tuple[Contact | TacticalShotSample, ...] = (*awp, *awp_shots)
                if not weapon_events:
                    continue
                conflicting_shots = any(
                    shot.tick == tick
                    and shot.weapon is not None
                    and shot.weapon.casefold().removeprefix("weapon_") != "awp"
                    for shot in shots
                )
                if conflicting_shots:
                    continue
                sample = _recent(round_item, player, tick, seconds)
                if not (awp or awp_shots) or sample is None:
                    continue
                identity = (
                    f"steam:{sample.steam_id}"
                    if sample.steam_id
                    else f"match:{match.source.match_id}:player:{player}"
                )
                evidence = _evidence(round_item, awp, (sample,))
                evidence = evidence.model_copy(
                    update={
                        "tick_end": max(tick, evidence.tick_end or tick),
                        "event_ids": tuple(
                            sorted(
                                {*evidence.event_ids, *(shot.event_id for shot in awp_shots)},
                                key=str,
                            )
                        ),
                    }
                )
                facts.append(
                    DepthFact(
                        TacticalInsightType.AWP_OPENING,
                        match.source.map_name,
                        round_item.side,
                        f"{identity}|{sample.zone_id}",
                        f"{sample.player_name or 'Игрок без ника'} — AWP: "
                        f"{_zone_label(sample, match.source.map_name)}",
                        identity,
                        evidence,
                    )
                )
    return tuple(
        sorted(
            facts,
            key=lambda item: (
                item.kind,
                item.map_name,
                item.side,
                item.population,
                item.key,
                str(item.evidence.match_id),
                item.evidence.round_number,
            ),
        )
    )


def _non_gun_action(weapon: str | None) -> bool:
    name = (weapon or "").casefold().removeprefix("weapon_")
    return name.startswith("knife") or name in {
        "c4",
        "flashbang",
        "hegrenade",
        "smokegrenade",
        "molotov",
        "incgrenade",
        "decoy",
        "healthshot",
        "tagrenade",
        "snowball",
    }


def _zone_label(sample: TacticalPlayerSample, map_name: str) -> str:
    if map_name != "de_mirage":
        return sample.zone_name or sample.zone_id or "зона не определена"
    return {
        "window": "окно",
        "ticket": "тикет",
        "conector": "коннектор",
        "connector": "коннектор",
        "top_mid": "верх мида",
        "catwalk": "шорт",
        "short": "шорт",
        "ramp": "яма",
        "palace": "ковры",
        "bombsite_a": "плент A",
        "bombsite_b": "плент B",
    }.get(sample.zone_id or "", sample.zone_name or sample.zone_id or "зона не определена")


def _mirage_approach(
    round_item: TacticalRoundInput, seconds: float
) -> tuple[str, str, tuple[TacticalPlayerSample, ...]] | None:
    plant = round_item.plant
    if plant is None or plant.site not in {"A", "B"}:
        return None
    corridors = (
        {
            "connector": "connector",
            "conector": "connector",
            "ramp": "ramp",
            "tetris": "ramp",
            "palace": "palace",
            "balcony": "palace",
        }
        if plant.site == "A"
        else {
            "catwalk": "short",
            "short": "short",
            "apartments": "apps",
            "b_apps": "apps",
            "b_apartments": "apps",
            "kitchen": "market",
            "market": "market",
        }
    )
    by_corridor: dict[str, list[TacticalPlayerSample]] = defaultdict(list)
    for sample in round_item.samples:
        if (
            sample.player_id not in round_item.selected_player_ids
            or sample.side is not Side.T
            or sample.alive is not True
            or not sample.zone_id
            or not 0 <= (plant.tick - sample.tick) * seconds <= 12
        ):
            continue
        corridor = corridors.get(sample.zone_id)
        if corridor is not None:
            by_corridor[corridor].append(sample)
    if not by_corridor:
        return None

    def parallel(left: str, right: str) -> tuple[TacticalPlayerSample, TacticalPlayerSample] | None:
        pairs = [
            (a, b)
            for a in by_corridor.get(left, ())
            for b in by_corridor.get(right, ())
            if a.player_id != b.player_id and abs(a.tick - b.tick) * seconds <= 3
        ]
        return (
            min(
                pairs,
                key=lambda pair: (
                    abs(pair[0].tick - pair[1].tick),
                    str(pair[0].snapshot_id),
                    str(pair[1].snapshot_id),
                ),
            )
            if pairs
            else None
        )

    pair = parallel("connector", "ramp") if plant.site == "A" else parallel("short", "apps")
    if pair:
        return (
            ("a_connector_ramp", "A: одновременно через коннектор и яму", pair)
            if plant.site == "A"
            else ("b_short_apps", "B: одновременно через шорт и апартаменты", pair)
        )
    # Do not assert 'only' or 'rush': unobserved teammates and intent remain unknown.
    names = {
        "connector": "коннектор",
        "ramp": "яму",
        "palace": "ковры",
        "short": "шорт",
        "apps": "апартаменты",
        "market": "маркет",
    }
    key = "+".join(sorted(by_corridor))
    label = f"{plant.site}: перед установкой замечены проходы через " + ", ".join(
        names[k] for k in sorted(by_corridor)
    )
    return (
        f"{plant.site.lower()}_{key}",
        label,
        tuple(sample for values in by_corridor.values() for sample in values),
    )
