"""Canonical mappings for gameplay event rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID, uuid5

from stratweb.application.canonical_models import (
    NORMALIZATION_RULE_VERSION,
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGameplayEvent,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalShot,
    EventPhase,
    ValidationIssue,
    ValidationSeverity,
)
from stratweb.application.identity_resolution import PlayerResolutionResult, TeamResolutionResult
from stratweb.application.normalization_utils import (
    StableRawRow,
    optional_bool,
    optional_non_negative_float,
    optional_non_negative_int,
    optional_text,
    role_values,
    stable_rows,
    value,
)
from stratweb.application.round_assignment import RoundAssignmentService
from stratweb.contracts import ParsedDemo
from stratweb.domain.enums import Side

_GRENADE_EVENTS: dict[str, tuple[str, str]] = {
    "smokegrenade_detonate": ("smoke", "detonated"),
    "smokegrenade_expired": ("smoke", "expired"),
    "inferno_startburn": ("inferno", "started"),
    "inferno_expire": ("inferno", "expired"),
    "flashbang_detonate": ("flashbang", "detonated"),
    "hegrenade_detonate": ("he_grenade", "detonated"),
    "decoy_detonate": ("decoy", "detonated"),
}
_BOMB_EVENTS: dict[str, str] = {
    "bomb_planted": "planted",
    "bomb_defused": "defused",
    "bomb_exploded": "exploded",
}


@dataclass(frozen=True, slots=True)
class GameplayNormalizationResult:
    kills: tuple[CanonicalKill, ...]
    damages: tuple[CanonicalDamage, ...]
    shots: tuple[CanonicalShot, ...]
    grenades: tuple[CanonicalGrenade, ...]
    bomb_events: tuple[CanonicalBombEvent, ...]
    issues: tuple[ValidationIssue, ...]


class _BaseFields(TypedDict):
    event_id: UUID
    match_id: UUID
    round_id: UUID | None
    round_number: int | None
    tick: int
    relative_tick: int | None
    phase: EventPhase
    source_event: str


class GameplayEventNormalizer:
    def normalize(
        self,
        parsed: ParsedDemo,
        match_id: UUID,
        assignments: RoundAssignmentService,
        players: PlayerResolutionResult,
        teams: TeamResolutionResult,
    ) -> GameplayNormalizationResult:
        issues: list[ValidationIssue] = []
        kills = self._kills(parsed, match_id, assignments, players, teams, issues)
        damages = self._damages(parsed, match_id, assignments, players, teams, issues)
        shots = self._shots(parsed, match_id, assignments, players, teams, issues)
        grenades = self._grenades(parsed, match_id, assignments, players, teams, issues)
        bombs = self._bombs(parsed, match_id, assignments, players, teams, issues)
        return GameplayNormalizationResult(
            kills=tuple(sorted(kills, key=_event_sort_key)),
            damages=tuple(sorted(damages, key=_event_sort_key)),
            shots=tuple(sorted(shots, key=_event_sort_key)),
            grenades=tuple(sorted(grenades, key=_event_sort_key)),
            bomb_events=tuple(sorted(bombs, key=_event_sort_key)),
            issues=tuple(sorted(issues, key=lambda item: (item.code, item.entity_id or ""))),
        )

    def _kills(
        self,
        parsed: ParsedDemo,
        match_id: UUID,
        assignments: RoundAssignmentService,
        players: PlayerResolutionResult,
        teams: TeamResolutionResult,
        issues: list[ValidationIssue],
    ) -> list[CanonicalKill]:
        result: list[CanonicalKill] = []
        for row in stable_rows("player_death", parsed.tables.get("player_death")):
            common_result = _common_fields("kill", row, match_id, assignments, issues)
            if common_result is None:
                continue
            common, common_warnings = common_result
            attacker = players.player_for(row, "attacker")
            victim = players.player_for(row, "victim")
            assister = players.player_for(row, "assister")
            attacker_side = _role_side(row, "attacker", attacker, teams)
            victim_side = _role_side(row, "victim", victim, teams)
            attacker_team = teams.team_for(attacker)
            victim_team = teams.team_for(victim)
            warnings = list(common_warnings)
            if victim is None:
                warnings.append("victim player could not be resolved")
            if attacker is None:
                warnings.append("attacker player could not be resolved")
            is_suicide = attacker is not None and attacker == victim
            is_teamkill = (
                attacker_team is not None
                and attacker_team == victim_team
                and attacker is not None
                and victim is not None
                and attacker != victim
            )
            result.append(
                CanonicalKill(
                    **common,
                    attacker_player_id=attacker,
                    victim_player_id=victim,
                    assister_player_id=assister,
                    attacker_team_id=attacker_team,
                    victim_team_id=victim_team,
                    attacker_side=attacker_side,
                    victim_side=victim_side,
                    weapon=optional_text(value(row.data, "weapon")),
                    headshot=optional_bool(value(row.data, "headshot")),
                    penetrated=optional_non_negative_int(value(row.data, "penetrated")),
                    through_smoke=optional_bool(value(row.data, "thrusmoke", "through_smoke")),
                    no_scope=optional_bool(value(row.data, "noscope", "no_scope")),
                    attacker_blind=optional_bool(
                        value(row.data, "attackerblind", "attacker_blind")
                    ),
                    distance=optional_non_negative_float(value(row.data, "distance")),
                    is_teamkill=is_teamkill,
                    is_suicide=is_suicide,
                    warnings=tuple(sorted(set(warnings))),
                )
            )
        return result

    def _damages(
        self,
        parsed: ParsedDemo,
        match_id: UUID,
        assignments: RoundAssignmentService,
        players: PlayerResolutionResult,
        teams: TeamResolutionResult,
        issues: list[ValidationIssue],
    ) -> list[CanonicalDamage]:
        result: list[CanonicalDamage] = []
        for row in stable_rows("player_hurt", parsed.tables.get("player_hurt")):
            common_result = _common_fields("damage", row, match_id, assignments, issues)
            if common_result is None:
                continue
            common, common_warnings = common_result
            attacker = players.player_for(row, "attacker")
            victim = players.player_for(row, "victim")
            warnings = list(common_warnings)
            if victim is None:
                warnings.append("victim player could not be resolved")
            result.append(
                CanonicalDamage(
                    **common,
                    attacker_player_id=attacker,
                    victim_player_id=victim,
                    attacker_team_id=teams.team_for(attacker),
                    victim_team_id=teams.team_for(victim),
                    attacker_side=_role_side(row, "attacker", attacker, teams),
                    victim_side=_role_side(row, "victim", victim, teams),
                    weapon=optional_text(value(row.data, "weapon")),
                    damage_health=optional_non_negative_int(
                        value(row.data, "dmg_health", "damage_health")
                    ),
                    damage_armor=optional_non_negative_int(
                        value(row.data, "dmg_armor", "damage_armor")
                    ),
                    victim_health_after=optional_non_negative_int(
                        value(row.data, "health", "victim_health_after")
                    ),
                    hitgroup=optional_text(value(row.data, "hitgroup")),
                    warnings=tuple(sorted(set(warnings))),
                )
            )
        return result

    def _shots(
        self,
        parsed: ParsedDemo,
        match_id: UUID,
        assignments: RoundAssignmentService,
        players: PlayerResolutionResult,
        teams: TeamResolutionResult,
        issues: list[ValidationIssue],
    ) -> list[CanonicalShot]:
        result: list[CanonicalShot] = []
        for row in stable_rows("weapon_fire", parsed.tables.get("weapon_fire")):
            common_result = _common_fields("shot", row, match_id, assignments, issues)
            if common_result is None:
                continue
            common, common_warnings = common_result
            player_id = players.player_for(row, "user")
            result.append(
                CanonicalShot(
                    **common,
                    player_id=player_id,
                    team_id=teams.team_for(player_id),
                    side=_role_side(row, "user", player_id, teams),
                    weapon=optional_text(value(row.data, "weapon")),
                    silenced=optional_bool(value(row.data, "silenced")),
                    warnings=common_warnings,
                )
            )
        return result

    def _grenades(
        self,
        parsed: ParsedDemo,
        match_id: UUID,
        assignments: RoundAssignmentService,
        players: PlayerResolutionResult,
        teams: TeamResolutionResult,
        issues: list[ValidationIssue],
    ) -> list[CanonicalGrenade]:
        result: list[CanonicalGrenade] = []
        for source_event, (grenade_type, lifecycle) in _GRENADE_EVENTS.items():
            for row in stable_rows(source_event, parsed.tables.get(source_event)):
                common_result = _common_fields("grenade", row, match_id, assignments, issues)
                if common_result is None:
                    continue
                common, common_warnings = common_result
                player_id = players.player_for(row, "user")
                result.append(
                    CanonicalGrenade(
                        **common,
                        player_id=player_id,
                        team_id=teams.team_for(player_id),
                        side=_role_side(row, "user", player_id, teams),
                        grenade_type=grenade_type,
                        lifecycle_event=lifecycle,
                        entity_id=optional_non_negative_int(
                            value(row.data, "entityid", "entity_id")
                        ),
                        x=optional_non_negative_float(value(row.data, "x"))
                        if optional_non_negative_float(value(row.data, "x")) is not None
                        else _coordinate(value(row.data, "x")),
                        y=_coordinate(value(row.data, "y")),
                        z=_coordinate(value(row.data, "z")),
                        warnings=common_warnings,
                    )
                )
        return result

    def _bombs(
        self,
        parsed: ParsedDemo,
        match_id: UUID,
        assignments: RoundAssignmentService,
        players: PlayerResolutionResult,
        teams: TeamResolutionResult,
        issues: list[ValidationIssue],
    ) -> list[CanonicalBombEvent]:
        result: list[CanonicalBombEvent] = []
        for source_event, event_type in _BOMB_EVENTS.items():
            for row in stable_rows(source_event, parsed.tables.get(source_event)):
                common_result = _common_fields("bomb", row, match_id, assignments, issues)
                if common_result is None:
                    continue
                common, common_warnings = common_result
                player_id = players.player_for(row, "user")
                raw_site = value(row.data, "site", "bombsite")
                normalized_site = _normalize_site(raw_site)
                warnings = list(common_warnings)
                if raw_site is not None and normalized_site is None:
                    warnings.append("bomb site value retained but not normalized")
                result.append(
                    CanonicalBombEvent(
                        **common,
                        player_id=player_id,
                        team_id=teams.team_for(player_id),
                        side=_role_side(row, "user", player_id, teams),
                        event_type=event_type,
                        site_raw=raw_site
                        if isinstance(raw_site, (str, int))
                        else optional_text(raw_site),
                        site_normalized=normalized_site,
                        warnings=tuple(sorted(set(warnings))),
                    )
                )
        return result


def _common_fields(
    kind: str,
    row: StableRawRow,
    match_id: UUID,
    assignments: RoundAssignmentService,
    issues: list[ValidationIssue],
) -> tuple[_BaseFields, tuple[str, ...]] | None:
    if row.tick is None:
        issues.append(
            ValidationIssue(
                code="invalid_event_tick",
                severity=ValidationSeverity.ERROR,
                entity_type=kind,
                entity_id=row.row_key,
                message="Raw event has a missing, invalid, or negative tick and was omitted.",
                evidence={"source_event": row.source_event},
                rule_version=NORMALIZATION_RULE_VERSION,
            )
        )
        return None
    assigned = assignments.assign(row.tick)
    warnings: list[str] = []
    if assigned.round_id is None:
        warnings.append("event could not be assigned to a canonical round")
    base: _BaseFields = {
        "event_id": uuid5(
            match_id,
            f"event:{kind}:{row.source_event}:{row.tick}:{row.row_key}",
        ),
        "match_id": match_id,
        "round_id": assigned.round_id,
        "round_number": assigned.round_number,
        "tick": row.tick,
        "relative_tick": assigned.relative_tick,
        "phase": assigned.phase,
        "source_event": row.source_event,
    }
    return base, tuple(warnings)


def _role_side(
    row: StableRawRow,
    role: str,
    player_id: UUID | None,
    teams: TeamResolutionResult,
) -> Side:
    _steam, _name, raw_side, _is_bot = role_values(row.data, role)
    if raw_side is not Side.UNKNOWN:
        return raw_side
    if row.tick is None:
        return Side.UNKNOWN
    return teams.side_for(player_id, row.tick)


def _coordinate(raw: object) -> float | None:
    from stratweb.application.normalization_utils import optional_float

    return optional_float(raw)


def _normalize_site(raw: object) -> str | None:
    normalized = optional_text(raw)
    if normalized is None:
        return None
    lookup = {
        "a": "A",
        "bombsite_a": "A",
        "site_a": "A",
        "b": "B",
        "bombsite_b": "B",
        "site_b": "B",
    }
    return lookup.get(normalized.casefold())


def _event_sort_key(event: CanonicalGameplayEvent) -> tuple[int, str]:
    return event.tick, str(event.event_id)
