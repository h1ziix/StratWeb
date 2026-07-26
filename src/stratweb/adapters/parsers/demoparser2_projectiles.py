"""Narrow, audited demoparser2 0.41.4 projectile extraction adapter."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import hypot, isfinite
from typing import Any, cast

from stratweb.spatial.projectiles import (
    PROJECTILE_REQUESTED_EVENTS,
    PROJECTILE_REQUESTED_PROPERTIES,
    PROJECTILE_SAMPLING_INTERVAL_TICKS,
    ProjectileAuthority,
    ProjectileAvailability,
    ProjectileCapabilities,
    ProjectileCapability,
    ProjectileExtraction,
    ProjectileLifecycle,
    ProjectileSourcePoint,
    ProjectileSourceTrack,
    ProjectileType,
    UtilityEffectSource,
    UtilityEffectType,
)

_THROW_ASSOCIATION_MAX_OFFSET_TICKS = 64
_EFFECT_END_MAX_OFFSET_TICKS = 4096
_TERMINAL_EVENTS = {
    "flashbang_detonate",
    "hegrenade_detonate",
    "smokegrenade_detonate",
    "inferno_startburn",
    "decoy_started",
}
_EFFECT_END_EVENT = {
    "smokegrenade_detonate": "smokegrenade_expired",
    "inferno_startburn": "inferno_expire",
    "decoy_started": "decoy_detonate",
}


@dataclass(frozen=True)
class _Event:
    name: str
    tick: int
    entity_id: int | None
    steam_id: str | None
    weapon: str | None
    x: float | None
    y: float | None
    z: float | None


def extract_projectiles(backend: object) -> ProjectileExtraction:
    """Return bounded source tracks; failure degrades only projectile capability."""

    parse_grenades = getattr(backend, "parse_grenades", None)
    parse_events = getattr(backend, "parse_events", None)
    list_events = getattr(backend, "list_game_events", None)
    if not callable(parse_grenades) or not callable(parse_events) or not callable(list_events):
        return ProjectileExtraction(warnings=("projectile_parser_methods_unavailable",))
    try:
        available = {str(item) for item in cast(Sequence[object], list_events())}
        requested_events = tuple(item for item in PROJECTILE_REQUESTED_EVENTS if item in available)
        parsed_events = parse_events(list(requested_events)) if requested_events else []
        events = _normalize_events(parsed_events)
        raw = parse_grenades(
            extra=list(PROJECTILE_REQUESTED_PROPERTIES),
            grenades=False,
        )
        tracks, effects = _normalize_tracks(raw, events)
    except Exception as exc:
        return ProjectileExtraction(
            warnings=(f"projectile_extraction_failed:{type(exc).__name__}:{exc}",)
        )
    warnings: list[str] = []
    missing_events = tuple(item for item in PROJECTILE_REQUESTED_EVENTS if item not in available)
    if missing_events:
        warnings.append("projectile_events_absent:" + ",".join(missing_events))
    capabilities = _capabilities(tracks, effects, raw)
    return ProjectileExtraction(
        tracks=tracks,
        effects=effects,
        capabilities=capabilities,
        warnings=tuple(warnings),
    )


def _normalize_events(parsed: object) -> tuple[_Event, ...]:
    result: list[_Event] = []
    if not isinstance(parsed, Sequence):
        return ()
    for item in parsed:
        if not isinstance(item, Sequence) or len(item) != 2:
            continue
        name, frame = item
        if not hasattr(frame, "to_dict"):
            continue
        records = frame.to_dict(orient="records")
        for record in records:
            if not isinstance(record, Mapping):
                continue
            tick = _integer(record.get("tick"))
            if tick is None or tick < 0:
                continue
            result.append(
                _Event(
                    name=str(name),
                    tick=tick,
                    entity_id=_integer(record.get("entityid")),
                    steam_id=_identifier(record.get("user_steamid")),
                    weapon=_text(record.get("weapon")),
                    x=_finite(record.get("x")),
                    y=_finite(record.get("y")),
                    z=_finite(record.get("z")),
                )
            )
    return tuple(sorted(result, key=lambda item: (item.tick, item.name, item.entity_id or -1)))


def _normalize_tracks(
    raw: object, events: tuple[_Event, ...]
) -> tuple[tuple[ProjectileSourceTrack, ...], tuple[UtilityEffectSource, ...]]:
    required = {
        "grenade_type",
        "grenade_entity_id",
        "x",
        "y",
        "z",
        "tick",
        "steamid",
        "name",
    }
    if not hasattr(raw, "columns") or not hasattr(raw, "sort_values"):
        raise ValueError("parse_grenades did not return a dataframe")
    columns = tuple(str(item) for item in raw.columns)
    if not required.issubset(columns):
        raise ValueError(
            "parse_grenades missing columns: " + ",".join(sorted(required - set(columns)))
        )
    ordered = raw.sort_values(
        ["grenade_entity_id", "tick", "grenade_type", "steamid"],
        kind="stable",
    )
    indexes = {name: columns.index(name) for name in columns}
    terminal_by_entity: dict[int, list[_Event]] = defaultdict(list)
    end_by_entity: dict[int, list[_Event]] = defaultdict(list)
    terminal_events: list[_Event] = []
    used_terminal_events: set[tuple[str, int, int | None]] = set()
    throws: list[_Event] = []
    for event in events:
        if event.name == "weapon_fire" and event.weapon is not None:
            if _weapon_projectile_type(event.weapon) is not ProjectileType.UNKNOWN:
                throws.append(event)
        elif event.entity_id is not None and event.name in _TERMINAL_EVENTS:
            terminal_by_entity[event.entity_id].append(event)
            terminal_events.append(event)
        elif event.entity_id is not None and event.name in _EFFECT_END_EVENT.values():
            end_by_entity[event.entity_id].append(event)

    tracks: list[ProjectileSourceTrack] = []
    effects: list[UtilityEffectSource] = []
    segment: list[tuple[object, ...]] = []
    previous_identity: tuple[int, str, str | None] | None = None
    previous_tick: int | None = None
    previous_bounce: int | None = None

    def flush() -> None:
        nonlocal segment
        if not segment:
            return
        track, effect = _build_track(
            segment,
            indexes,
            terminal_by_entity,
            terminal_events,
            used_terminal_events,
            end_by_entity,
            throws,
            len(tracks),
        )
        tracks.append(track)
        if effect is not None:
            effects.append(effect)
        segment = []

    for row in ordered.itertuples(index=False, name=None):
        entity = _integer(row[indexes["grenade_entity_id"]])
        tick = _integer(row[indexes["tick"]])
        raw_type = _text(row[indexes["grenade_type"]])
        steam = _identifier(row[indexes["steamid"]])
        x = _finite(row[indexes["x"]])
        y = _finite(row[indexes["y"]])
        z = _finite(row[indexes["z"]])
        if entity is None or tick is None or raw_type is None or None in (x, y, z):
            continue
        identity = (entity, raw_type, steam)
        bounce = (
            _integer(row[indexes["Grenade.m_nBounces"]])
            if "Grenade.m_nBounces" in indexes
            else None
        )
        boundary = previous_identity is not None and (
            identity != previous_identity
            or previous_tick is None
            or tick - previous_tick > 1
            or tick <= previous_tick
            or (bounce is not None and previous_bounce is not None and bounce < previous_bounce)
        )
        if boundary:
            flush()
        segment.append(row)
        previous_identity = identity
        previous_tick = tick
        previous_bounce = bounce
    flush()
    return tuple(tracks), tuple(effects)


def _build_track(
    rows: list[tuple[object, ...]],
    indexes: dict[str, int],
    terminal_by_entity: dict[int, list[_Event]],
    terminal_events: list[_Event],
    used_terminal_events: set[tuple[str, int, int | None]],
    end_by_entity: dict[int, list[_Event]],
    throws: list[_Event],
    sequence: int,
) -> tuple[ProjectileSourceTrack, UtilityEffectSource | None]:
    first = rows[0]
    entity = _required_integer(first[indexes["grenade_entity_id"]])
    raw_type = str(first[indexes["grenade_type"]])
    steam = _identifier(first[indexes["steamid"]])
    owner_name = _text(first[indexes["name"]])
    first_tick = _required_integer(first[indexes["tick"]])
    last_source_tick = _required_integer(rows[-1][indexes["tick"]])
    projectile_type = _raw_projectile_type(raw_type)
    last_x = _required_float(rows[-1][indexes["x"]])
    last_y = _required_float(rows[-1][indexes["y"]])
    terminal, terminal_association_derived = _match_terminal(
        terminal_by_entity.get(entity, ()),
        terminal_events,
        used_terminal_events,
        projectile_type,
        steam,
        first_tick,
        last_source_tick,
        last_x,
        last_y,
    )
    terminal_tick = terminal.tick if terminal is not None else last_source_tick
    throw, throw_offset = _match_throw(throws, steam, projectile_type, first_tick)
    warnings: list[str] = []
    if terminal is None:
        warnings.append("projectile_terminal_event_unavailable")
    elif terminal_association_derived:
        warnings.append("terminal_event_associated_by_owner_type_tick_and_position")
    if throw is None:
        warnings.append("projectile_throw_action_unavailable")
    else:
        projectile_type = _weapon_projectile_type(throw.weapon or "")
        if throw_offset:
            warnings.append(f"first_projectile_position_offset_ticks:{throw_offset}")
    velocity = (
        _vector(first[indexes["Grenade.m_vInitialVelocity"]])
        if "Grenade.m_vInitialVelocity" in indexes
        else None
    )
    source_track_id = f"entity:{entity}:segment:{sequence}:tick:{first_tick}"
    points: list[ProjectileSourcePoint] = []
    last_bounce: int | None = None
    for row in rows:
        tick = _required_integer(row[indexes["tick"]])
        if tick > terminal_tick:
            break
        bounce = (
            _integer(row[indexes["Grenade.m_nBounces"]])
            if "Grenade.m_nBounces" in indexes
            else None
        )
        bounce_changed = bounce is not None and last_bounce is not None and bounce > last_bounce
        include = (
            tick == first_tick
            or tick == terminal_tick
            or (tick - first_tick) % PROJECTILE_SAMPLING_INTERVAL_TICKS == 0
            or bounce_changed
        )
        if include:
            lifecycle = ProjectileLifecycle.IN_FLIGHT
            if bounce_changed:
                lifecycle = ProjectileLifecycle.BOUNCED
            if terminal is not None and tick == terminal_tick:
                lifecycle = (
                    ProjectileLifecycle.LANDED
                    if terminal.name == "decoy_started"
                    else ProjectileLifecycle.DETONATED
                )
            points.append(
                ProjectileSourcePoint(
                    tick=tick,
                    x=_required_float(row[indexes["x"]]),
                    y=_required_float(row[indexes["y"]]),
                    z=_required_float(row[indexes["z"]]),
                    bounce_count=bounce,
                    lifecycle=lifecycle,
                    source=(
                        f"demoparser2:event:{terminal.name}"
                        if terminal is not None and tick == terminal_tick
                        else "demoparser2:parse_grenades"
                    ),
                )
            )
        last_bounce = bounce
    if (
        terminal is not None
        and terminal.tick not in {point.tick for point in points}
        and None not in (terminal.x, terminal.y, terminal.z)
    ):
        assert terminal.x is not None and terminal.y is not None and terminal.z is not None
        points.append(
            ProjectileSourcePoint(
                tick=terminal.tick,
                x=terminal.x,
                y=terminal.y,
                z=terminal.z,
                bounce_count=last_bounce,
                lifecycle=(
                    ProjectileLifecycle.LANDED
                    if terminal.name == "decoy_started"
                    else ProjectileLifecycle.DETONATED
                ),
                source=f"demoparser2:event:{terminal.name}",
                warnings=(
                    ("trajectory_to_terminal_event_not_interpolated",)
                    if terminal.tick > last_source_tick
                    else ()
                ),
            )
        )
        points.sort(key=lambda item: item.tick)
    availability = (
        ProjectileAvailability.AVAILABLE
        if terminal is not None and throw is not None
        else ProjectileAvailability.PARTIAL
    )
    track = ProjectileSourceTrack(
        source_track_id=source_track_id,
        source_entity_id=entity,
        raw_projectile_type=raw_type,
        projectile_type=projectile_type,
        owner_steam_id=steam,
        owner_name=owner_name,
        thrown_tick=throw.tick if throw is not None else None,
        first_position_tick=first_tick,
        terminal_tick=terminal_tick,
        terminal_event=terminal.name if terminal is not None else None,
        initial_velocity_x=velocity[0] if velocity is not None else None,
        initial_velocity_y=velocity[1] if velocity is not None else None,
        initial_velocity_z=velocity[2] if velocity is not None else None,
        points=tuple(points),
        availability=availability,
        warnings=tuple(warnings),
    )
    return track, _effect_for_track(
        track,
        terminal,
        end_by_entity.get(
            (
                terminal.entity_id
                if terminal is not None and terminal.entity_id is not None
                else entity
            ),
            (),
        ),
        last_source_tick,
    )


def _effect_for_track(
    track: ProjectileSourceTrack,
    terminal: _Event | None,
    end_events: Sequence[_Event],
    last_source_tick: int,
) -> UtilityEffectSource | None:
    if terminal is None:
        return None
    effect_type = _effect_type(terminal.name)
    if effect_type is UtilityEffectType.UNKNOWN:
        return None
    expected_end = _EFFECT_END_EVENT.get(terminal.name)
    end = (
        next(
            (
                item
                for item in end_events
                if item.name == expected_end
                and terminal.tick <= item.tick <= last_source_tick + _EFFECT_END_MAX_OFFSET_TICKS
            ),
            None,
        )
        if expected_end is not None
        else terminal
    )
    warnings: list[str] = []
    if expected_end is not None and end is None:
        warnings.append("utility_effect_end_event_unavailable")
    if None in (terminal.x, terminal.y, terminal.z):
        warnings.append("utility_effect_center_unavailable")
    availability = (
        ProjectileAvailability.AVAILABLE if not warnings else ProjectileAvailability.PARTIAL
    )
    return UtilityEffectSource(
        source_effect_id=f"{track.source_track_id}:{terminal.name}:{terminal.tick}",
        source_track_id=track.source_track_id,
        source_entity_id=track.source_entity_id,
        effect_type=effect_type,
        start_tick=terminal.tick,
        end_tick=end.tick if end is not None else None,
        center_x=terminal.x,
        center_y=terminal.y,
        center_z=terminal.z,
        start_event=terminal.name,
        end_event=end.name if end is not None and end is not terminal else None,
        availability=availability,
        warnings=tuple(warnings),
    )


def _match_throw(
    throws: list[_Event],
    steam_id: str | None,
    projectile_type: ProjectileType,
    first_tick: int,
) -> tuple[_Event | None, int | None]:
    candidates = [
        item
        for item in throws
        if item.steam_id == steam_id
        and _compatible_types(_weapon_projectile_type(item.weapon or ""), projectile_type)
        and 0 <= first_tick - item.tick <= _THROW_ASSOCIATION_MAX_OFFSET_TICKS
    ]
    if not candidates:
        return None, None
    selected = max(candidates, key=lambda item: item.tick)
    throws.remove(selected)
    return selected, first_tick - selected.tick


def _match_terminal(
    direct: Sequence[_Event],
    all_events: Sequence[_Event],
    used: set[tuple[str, int, int | None]],
    projectile_type: ProjectileType,
    steam_id: str | None,
    first_tick: int,
    last_tick: int,
    last_x: float,
    last_y: float,
) -> tuple[_Event | None, bool]:
    direct_candidates = [
        item
        for item in direct
        if first_tick <= item.tick <= last_tick + 4 and _event_key(item) not in used
    ]
    if direct_candidates:
        selected = min(direct_candidates, key=lambda item: abs(item.tick - last_tick))
        used.add(_event_key(selected))
        return selected, False
    candidates = [
        item
        for item in all_events
        if _event_key(item) not in used
        and _compatible_types(_terminal_projectile_type(item.name), projectile_type)
        and (steam_id is None or item.steam_id is None or item.steam_id == steam_id)
        and last_tick - 8 <= item.tick <= last_tick + 64
        and item.x is not None
        and item.y is not None
        and hypot(item.x - last_x, item.y - last_y) <= 512.0
    ]
    if not candidates:
        return None, False
    selected = min(
        candidates,
        key=lambda item: (
            abs(item.tick - last_tick),
            hypot((item.x or 0.0) - last_x, (item.y or 0.0) - last_y),
            item.name,
        ),
    )
    used.add(_event_key(selected))
    return selected, True


def _event_key(event: _Event) -> tuple[str, int, int | None]:
    return event.name, event.tick, event.entity_id


def _terminal_projectile_type(event_name: str) -> ProjectileType:
    return {
        "smokegrenade_detonate": ProjectileType.SMOKE,
        "flashbang_detonate": ProjectileType.FLASHBANG,
        "hegrenade_detonate": ProjectileType.HE_GRENADE,
        "inferno_startburn": ProjectileType.MOLOTOV,
        "decoy_started": ProjectileType.DECOY,
    }.get(event_name, ProjectileType.UNKNOWN)


def _capabilities(
    tracks: tuple[ProjectileSourceTrack, ...],
    effects: tuple[UtilityEffectSource, ...],
    raw: object,
) -> ProjectileCapabilities:
    total = len(tracks)
    columns = {str(item) for item in cast(Sequence[object], getattr(raw, "columns", ()))}
    terminal = sum(item.terminal_event is not None for item in tracks)
    derived_terminal = sum(
        "terminal_event_associated_by_owner_type_tick_and_position" in item.warnings
        for item in tracks
    )
    throws = sum(item.thrown_tick is not None for item in tracks)
    velocity = sum(item.initial_velocity_x is not None for item in tracks)

    def capability(
        covered: int,
        *,
        authority: ProjectileAuthority,
        fields: tuple[str, ...],
        population: int = total,
        warnings: tuple[str, ...] = (),
    ) -> ProjectileCapability:
        status = (
            ProjectileAvailability.UNAVAILABLE
            if population == 0 or covered == 0
            else ProjectileAvailability.AVAILABLE
            if covered == population
            else ProjectileAvailability.PARTIAL
        )
        return ProjectileCapability(
            status=status,
            authority=authority if covered else ProjectileAuthority.UNAVAILABLE,
            population=population,
            covered=covered,
            source_fields=fields,
            warnings=warnings,
        )

    def lifecycle(effect_type: UtilityEffectType) -> ProjectileCapability:
        relevant = tuple(item for item in effects if item.effect_type is effect_type)
        covered = sum(item.end_tick is not None for item in relevant)
        return capability(
            covered,
            population=len(relevant),
            authority=ProjectileAuthority.GAME_EVENT,
            fields=("entityid", "tick", "x", "y", "z"),
        )

    bounce_property = "Grenade.m_nBounces" in columns
    return ProjectileCapabilities(
        positions=capability(
            total,
            authority=ProjectileAuthority.PARSER_ENTITY,
            fields=("x", "y", "z", "tick", "grenade_entity_id"),
        ),
        owner=capability(
            sum(item.owner_steam_id is not None for item in tracks),
            authority=ProjectileAuthority.PARSER_ENTITY,
            fields=("steamid", "name"),
        ),
        initial_velocity=capability(
            velocity,
            authority=ProjectileAuthority.PARSER_ENTITY,
            fields=("Grenade.m_vInitialVelocity",),
            warnings=("initial velocity only; per-tick velocity unavailable",),
        ),
        throw_actions=capability(
            throws,
            authority=ProjectileAuthority.DERIVED_ASSOCIATION,
            fields=("weapon_fire.tick", "weapon_fire.weapon", "steamid"),
            warnings=(
                "throw action is associated by owner/type and bounded tick offset; "
                "first projectile coordinate remains separate",
            ),
        ),
        lifecycle=capability(
            terminal,
            authority=(
                ProjectileAuthority.DERIVED_ASSOCIATION
                if derived_terminal
                else ProjectileAuthority.GAME_EVENT
            ),
            fields=("entityid", "tick"),
            warnings=(
                (f"{derived_terminal} terminal events use bounded association to a parser track",)
                if derived_terminal
                else ()
            ),
        ),
        bounce_events=capability(
            total if bounce_property else 0,
            authority=ProjectileAuthority.PARSER_ENTITY,
            fields=("Grenade.m_nBounces",),
            warnings=(
                "no bounce game event; bounce tick is the first observed cumulative-count change",
            ),
        ),
        detonation_events=capability(
            terminal,
            authority=(
                ProjectileAuthority.DERIVED_ASSOCIATION
                if derived_terminal
                else ProjectileAuthority.GAME_EVENT
            ),
            fields=("entityid", "tick", "x", "y", "z"),
            warnings=(
                (f"{derived_terminal} terminal events use bounded association to a parser track",)
                if derived_terminal
                else ()
            ),
        ),
        smoke_lifecycle=lifecycle(UtilityEffectType.SMOKE),
        fire_lifecycle=lifecycle(UtilityEffectType.FIRE),
        decoy_lifecycle=lifecycle(UtilityEffectType.DECOY),
    )


def _raw_projectile_type(value: str) -> ProjectileType:
    lowered = value.casefold()
    if "smoke" in lowered:
        return ProjectileType.SMOKE
    if "flash" in lowered:
        return ProjectileType.FLASHBANG
    if "hegrenade" in lowered:
        return ProjectileType.HE_GRENADE
    if "molotov" in lowered:
        return ProjectileType.MOLOTOV
    if "incendiary" in lowered:
        return ProjectileType.INCENDIARY
    if "decoy" in lowered:
        return ProjectileType.DECOY
    return ProjectileType.UNKNOWN


def _weapon_projectile_type(value: str) -> ProjectileType:
    lowered = value.casefold()
    if "smokegrenade" in lowered:
        return ProjectileType.SMOKE
    if "flashbang" in lowered:
        return ProjectileType.FLASHBANG
    if "hegrenade" in lowered:
        return ProjectileType.HE_GRENADE
    if "incgrenade" in lowered or "incendiary" in lowered:
        return ProjectileType.INCENDIARY
    if "molotov" in lowered:
        return ProjectileType.MOLOTOV
    if "decoy" in lowered:
        return ProjectileType.DECOY
    return ProjectileType.UNKNOWN


def _compatible_types(first: ProjectileType, second: ProjectileType) -> bool:
    fire = {ProjectileType.MOLOTOV, ProjectileType.INCENDIARY}
    return first == second or first in fire and second in fire


def _effect_type(event_name: str) -> UtilityEffectType:
    return {
        "smokegrenade_detonate": UtilityEffectType.SMOKE,
        "inferno_startburn": UtilityEffectType.FIRE,
        "flashbang_detonate": UtilityEffectType.FLASH,
        "hegrenade_detonate": UtilityEffectType.HE,
        "decoy_started": UtilityEffectType.DECOY,
    }.get(event_name, UtilityEffectType.UNKNOWN)


def _integer(value: object) -> int | None:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None


def _required_integer(value: object) -> int:
    result = _integer(value)
    if result is None:
        raise ValueError("required projectile integer is unavailable")
    return result


def _identifier(value: object) -> str | None:
    result = _integer(value)
    if result is not None:
        return str(result)
    return _text(value)


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _finite(value: object) -> float | None:
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _required_float(value: object) -> float:
    result = _finite(value)
    if result is None:
        raise ValueError("required projectile coordinate is unavailable")
    return result


def _vector(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        return None
    result = tuple(_finite(item) for item in value)
    if any(item is None for item in result):
        return None
    return cast(tuple[float, float, float], result)
