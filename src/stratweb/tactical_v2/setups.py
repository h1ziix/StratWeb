"""Deterministic CT setup and player-role inference from early position evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from stratweb.domain.enums import Side
from stratweb.tactical_v2.models import (
    TACTICAL_V2_CT_SETUP_RULE,
    TACTICAL_V2_CT_SETUP_ZONE_RULE,
    CTSetupPlayerRole,
    CTSetupProfile,
    CTSetupRole,
    TacticalEvidenceReference,
    TacticalInsight,
    TacticalInsightType,
    TacticalMatchInput,
    TacticalPlayerSample,
    TacticalV2Config,
)

_Area = Literal["a", "b", "mid"]
_RoundKey = tuple[UUID, int]


@dataclass(frozen=True, slots=True)
class CTSetupCalculation:
    profiles: tuple[CTSetupProfile, ...]
    eligible_rounds: int
    covered_rounds: int


@dataclass(slots=True)
class _PlayerStats:
    identity_key: str
    steam_id: str | None
    player_ids: set[UUID] = field(default_factory=set)
    names: Counter[str] = field(default_factory=Counter)
    observed_rounds: set[_RoundKey] = field(default_factory=set)
    role_rounds: dict[CTSetupRole, set[_RoundKey]] = field(default_factory=lambda: defaultdict(set))
    role_evidence: dict[CTSetupRole, dict[_RoundKey, TacticalEvidenceReference]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    zone_counts: dict[CTSetupRole, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    awp_observed_rounds: set[_RoundKey] = field(default_factory=set)
    awp_rounds: set[_RoundKey] = field(default_factory=set)


def compute_ct_setups(
    matches: tuple[TacticalMatchInput, ...],
    config: TacticalV2Config,
) -> CTSetupCalculation:
    """Assign map roles without merging players by nickname or inventing unknown zones."""

    stats_by_map: dict[str, dict[str, _PlayerStats]] = defaultdict(dict)
    eligible_by_map: Counter[str] = Counter()
    covered_by_map: dict[str, set[_RoundKey]] = defaultdict(set)

    for match in sorted(matches, key=lambda item: str(item.source.match_id)):
        for round_item in sorted(match.rounds, key=lambda item: item.round_number):
            if (
                round_item.side is not Side.CT
                or round_item.is_warmup
                or not round_item.is_complete
                or round_item.live_start_tick is None
            ):
                continue
            map_name = match.source.map_name
            eligible_by_map[map_name] += 1
            round_key = (match.source.match_id, round_item.round_number)
            terminal_tick = round_item.live_start_tick + config.ct_setup_window_ticks
            by_player: dict[UUID, list[TacticalPlayerSample]] = defaultdict(list)
            for sample in round_item.samples:
                if (
                    sample.player_id in round_item.selected_player_ids
                    and sample.side is Side.CT
                    and sample.alive is True
                    and sample.zone_id is not None
                    and round_item.live_start_tick <= sample.tick <= terminal_tick
                ):
                    by_player[sample.player_id].append(sample)

            for player_id, samples in sorted(by_player.items(), key=lambda item: str(item[0])):
                if not samples:
                    continue
                steam_ids = {item.steam_id for item in samples if item.steam_id}
                steam_id = next(iter(steam_ids)) if len(steam_ids) == 1 else None
                identity_key = (
                    f"steam:{steam_id}"
                    if steam_id is not None
                    else f"occurrence:{match.source.match_id}:{player_id}"
                )
                stats = stats_by_map[map_name].setdefault(
                    identity_key,
                    _PlayerStats(identity_key=identity_key, steam_id=steam_id),
                )
                stats.player_ids.add(player_id)
                stats.observed_rounds.add(round_key)
                stats.names.update(
                    item.player_name for item in samples if item.player_name is not None
                )
                known_weapons = tuple(item.weapons for item in samples if item.weapons is not None)
                if known_weapons:
                    stats.awp_observed_rounds.add(round_key)
                    if any(_has_awp(items) for items in known_weapons):
                        stats.awp_rounds.add(round_key)

                grouped_samples: dict[_Area, list[TacticalPlayerSample]] = defaultdict(list)
                for sample in samples:
                    area = _zone_area(map_name, sample.zone_id or "")
                    if area is not None:
                        grouped_samples[area].append(sample)
                if grouped_samples:
                    covered_by_map[map_name].add(round_key)

                role_areas: dict[CTSetupRole, _Area] = {
                    CTSetupRole.A_ANCHOR: "a",
                    CTSetupRole.B_ANCHOR: "b",
                    CTSetupRole.MID_SNIPER: "mid",
                }
                for role, target_area in role_areas.items():
                    relevant = grouped_samples.get(target_area, ())
                    if relevant:
                        _record_role(stats, role, round_key, match.source.match_id, relevant)
                if len(grouped_samples) >= 2:
                    _record_role(
                        stats, CTSetupRole.ROTATOR, round_key, match.source.match_id, samples
                    )

    profiles = []
    for map_name in sorted(eligible_by_map):
        players = tuple(stats_by_map[map_name].values())
        a_anchor = _top_role(players, CTSetupRole.A_ANCHOR)
        b_anchor = _top_role(players, CTSetupRole.B_ANCHOR)
        mid_player = _top_role(players, CTSetupRole.MID_SNIPER, prefer_awp=True)
        rotator = _top_role(
            players,
            CTSetupRole.ROTATOR,
            minimum_rounds=config.ct_setup_min_rotator_rounds,
            minimum_frequency=config.ct_setup_min_rotator_frequency,
        )
        if not any((a_anchor, b_anchor, mid_player, rotator)):
            continue
        profiles.append(
            CTSetupProfile(
                map_name=map_name,
                site_a_anchors=(a_anchor,) if a_anchor else (),
                site_b_anchors=(b_anchor,) if b_anchor else (),
                mid_players=(mid_player,) if mid_player else (),
                rotators=(rotator,) if rotator else (),
                sample_rounds=eligible_by_map[map_name],
                covered_rounds=len(covered_by_map[map_name]),
                limitations=_profile_limitations(config),
            )
        )
    return CTSetupCalculation(
        profiles=tuple(profiles),
        eligible_rounds=sum(eligible_by_map.values()),
        covered_rounds=sum(len(values) for values in covered_by_map.values()),
    )


def ct_setup_role_metrics(
    assignment: CTSetupPlayerRole,
    profile: CTSetupProfile,
) -> dict[str, Any]:
    """Serialize the typed role into generic TacticalInsight metric storage."""

    return {
        "role": assignment.role.value,
        "identity_key": assignment.identity_key,
        "player_ids": [str(item) for item in assignment.player_ids],
        "steam_id": assignment.steam_id,
        "player_name": assignment.player_name,
        "primary_zones": list(assignment.primary_zones),
        "awp_rounds": assignment.awp_rounds,
        "awp_observed_rounds": assignment.awp_observed_rounds,
        "awp_frequency": assignment.awp_frequency,
        "setup_sample_rounds": profile.sample_rounds,
        "setup_covered_rounds": profile.covered_rounds,
        "profile_limitations": list(profile.limitations),
    }


def ct_setup_profiles_from_insights(
    insights: tuple[TacticalInsight, ...],
) -> tuple[CTSetupProfile, ...]:
    """Rebuild typed setup cards from one immutable Tactical V2 run."""

    grouped: dict[str, list[CTSetupPlayerRole]] = defaultdict(list)
    profile_values: dict[str, tuple[int, int, tuple[str, ...]]] = {}
    for insight in insights:
        if insight.insight_type is not TacticalInsightType.CT_SETUP_ROLE:
            continue
        try:
            role = CTSetupRole(str(insight.metrics["role"]))
            assignment = CTSetupPlayerRole(
                identity_key=str(insight.metrics["identity_key"]),
                player_ids=tuple(UUID(str(item)) for item in _list_metric(insight, "player_ids")),
                steam_id=_optional_str_metric(insight, "steam_id"),
                player_name=str(insight.metrics["player_name"]),
                role=role,
                numerator=insight.numerator,
                denominator=insight.denominator,
                frequency=insight.frequency,
                sample_rounds=insight.sample_size,
                match_count=insight.match_count,
                primary_zones=tuple(str(item) for item in _list_metric(insight, "primary_zones")),
                awp_rounds=_int_metric(insight, "awp_rounds"),
                awp_observed_rounds=_int_metric(insight, "awp_observed_rounds"),
                awp_frequency=_optional_float_metric(insight, "awp_frequency"),
                evidence_references=insight.evidence_references,
                limitations=insight.limitations,
            )
            sample_rounds = _int_metric(insight, "setup_sample_rounds")
            covered_rounds = _int_metric(insight, "setup_covered_rounds")
            limitations = tuple(str(item) for item in _list_metric(insight, "profile_limitations"))
        except (KeyError, TypeError, ValueError):
            continue
        grouped[insight.map_name].append(assignment)
        profile_values[insight.map_name] = (sample_rounds, covered_rounds, limitations)

    result = []
    for map_name in sorted(grouped):
        sample_rounds, covered_rounds, limitations = profile_values[map_name]
        values = grouped[map_name]
        result.append(
            CTSetupProfile(
                map_name=map_name,
                site_a_anchors=_roles(values, CTSetupRole.A_ANCHOR),
                site_b_anchors=_roles(values, CTSetupRole.B_ANCHOR),
                mid_players=_roles(values, CTSetupRole.MID_SNIPER),
                rotators=_roles(values, CTSetupRole.ROTATOR),
                sample_rounds=sample_rounds,
                covered_rounds=covered_rounds,
                limitations=limitations,
            )
        )
    return tuple(result)


def _record_role(
    stats: _PlayerStats,
    role: CTSetupRole,
    round_key: _RoundKey,
    match_id: UUID,
    samples: list[TacticalPlayerSample] | tuple[TacticalPlayerSample, ...],
) -> None:
    stats.role_rounds[role].add(round_key)
    distinct_zones = {
        (item.zone_id or "", item.zone_name or item.zone_id or "Неизвестная зона")
        for item in samples
        if item.zone_id is not None
    }
    stats.zone_counts[role].update(name for _zone_id, name in distinct_zones)
    ticks = [item.tick for item in samples]
    stats.role_evidence[role][round_key] = TacticalEvidenceReference(
        match_id=match_id,
        round_number=round_key[1],
        tick_start=min(ticks),
        tick_end=max(ticks),
        snapshot_ids=tuple(sorted({item.snapshot_id for item in samples}, key=str)),
    )


def _top_role(
    players: tuple[_PlayerStats, ...],
    role: CTSetupRole,
    *,
    prefer_awp: bool = False,
    minimum_rounds: int = 1,
    minimum_frequency: float = 0.0,
) -> CTSetupPlayerRole | None:
    candidates = []
    for stats in players:
        denominator = len(stats.observed_rounds)
        numerator = len(stats.role_rounds[role])
        frequency = numerator / denominator if denominator else 0.0
        if numerator < minimum_rounds or frequency < minimum_frequency:
            continue
        awp_frequency = (
            len(stats.awp_rounds) / len(stats.awp_observed_rounds)
            if stats.awp_observed_rounds
            else None
        )
        candidates.append((stats, numerator, denominator, frequency, awp_frequency))
    if not candidates:
        return None
    stats, numerator, denominator, frequency, awp_frequency = min(
        candidates,
        key=lambda item: (
            -item[3],
            -(item[4] if prefer_awp and item[4] is not None else -1.0),
            -item[1],
            -item[2],
            item[0].identity_key,
        ),
    )
    evidence = tuple(
        stats.role_evidence[role][key] for key in sorted(stats.role_rounds[role], key=_round_key)
    )
    primary_zones = tuple(
        name
        for name, _count in sorted(
            stats.zone_counts[role].items(), key=lambda item: (-item[1], item[0].casefold())
        )[:3]
    )
    player_name = min(
        stats.names or Counter({f"Игрок {str(min(stats.player_ids, key=str))[:8]}": 1}),
        key=lambda name: (-stats.names.get(name, 1), name.casefold()),
    )
    return CTSetupPlayerRole(
        identity_key=stats.identity_key,
        player_ids=tuple(sorted(stats.player_ids, key=str)),
        steam_id=stats.steam_id,
        player_name=player_name,
        role=role,
        numerator=numerator,
        denominator=denominator,
        frequency=frequency,
        sample_rounds=denominator,
        match_count=len({item.match_id for item in evidence}),
        primary_zones=primary_zones,
        awp_rounds=len(stats.awp_rounds),
        awp_observed_rounds=len(stats.awp_observed_rounds),
        awp_frequency=awp_frequency,
        evidence_references=evidence,
        limitations=(
            f"ct_setup_rule:{TACTICAL_V2_CT_SETUP_RULE}",
            f"ct_setup_zone_rule:{TACTICAL_V2_CT_SETUP_ZONE_RULE}",
            "role_label_is_a_deterministic_summary_not_proof_of_called_responsibility",
            "denominator_contains_only_rounds_with_known_early_player_zone",
        ),
    )


def _profile_limitations(config: TacticalV2Config) -> tuple[str, ...]:
    return (
        f"early_window_ticks:{config.ct_setup_window_ticks}",
        "twenty_second_label_assumes_the_versioned_64_tick_policy",
        "unmapped_or_unknown_zones_are_not_assigned_to_a_site",
        "nickname_is_never_used_to_merge_players_across_matches",
        "awp_signal_is_shown_only_when_pinned_freeze_end_equipment_is_available",
    )


def _has_awp(weapons: tuple[str, ...]) -> bool:
    return any(item.casefold().removeprefix("weapon_").strip() == "awp" for item in weapons)


def _zone_area(map_name: str, zone_id: str) -> _Area | None:
    normalized = zone_id.strip().casefold().replace(" ", "_")
    if normalized in {"bombsite_a", "site_a", "a_site"}:
        return "a"
    if normalized in {"bombsite_b", "site_b", "b_site"}:
        return "b"
    for area, zones in _MAP_ZONE_AREAS.get(map_name, {}).items():
        if normalized in zones:
            return area
    return None


def _roles(values: list[CTSetupPlayerRole], role: CTSetupRole) -> tuple[CTSetupPlayerRole, ...]:
    return tuple(
        sorted((item for item in values if item.role is role), key=lambda item: item.identity_key)
    )


def _round_key(value: _RoundKey) -> tuple[str, int]:
    return str(value[0]), value[1]


def _list_metric(insight: TacticalInsight, key: str) -> list[Any]:
    value = insight.metrics[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} is not a list")
    return value


def _int_metric(insight: TacticalInsight, key: str) -> int:
    value = insight.metrics[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{key} is not an integer")
    return value


def _optional_float_metric(insight: TacticalInsight, key: str) -> float | None:
    value = insight.metrics[key]
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{key} is not numeric")
    return float(value)


def _optional_str_metric(insight: TacticalInsight, key: str) -> str | None:
    value = insight.metrics[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{key} is not text")
    return value


_MAP_ZONE_AREAS: dict[str, dict[_Area, frozenset[str]]] = {
    "de_mirage": {
        "a": frozenset({"ticket", "triple", "ninja", "shadow", "firebox", "stairs", "ramp"}),
        "b": frozenset({"bench", "car", "main", "kitchen", "short", "under_b"}),
        "mid": frozenset({"window", "catwalk", "ladder", "conector", "jungle", "start_mid"}),
    },
    "de_ancient": {
        "a": frozenset({"temple", "ct", "plat", "big_box", "triple", "donut", "short_a"}),
        "b": frozenset({"cave", "wood", "pit", "short_b", "long", "ramp"}),
        "mid": frozenset(
            {
                "sniper_nest",
                "alley",
                "red",
                "tree",
                "top_mid",
                "mid",
                "cat_room",
                "lower_mid",
                "cat",
            }
        ),
    },
    "de_dust2": {
        "a": frozenset({"ninja", "goose", "barrels", "ramp", "cross", "car_a", "short"}),
        "b": frozenset(
            {
                "back_plat",
                "back_site",
                "window",
                "b_plat",
                "box",
                "fence",
                "b_doors",
                "car_b",
                "closet",
            }
        ),
        "mid": frozenset(
            {"ct_mid", "boost", "mid_doors", "stairs", "xbox", "lower_tunnels", "cat"}
        ),
    },
    "de_inferno": {
        "a": frozenset(
            {"library", "cubby", "moto", "short", "pit", "mini_pit", "balcony", "halls", "t_apps"}
        ),
        "b": frozenset(
            {
                "garden",
                "dark",
                "coffins",
                "church",
                "pool",
                "fountain",
                "ct",
                "third",
                "second",
                "first",
                "boost",
                "car",
                "sandbag",
                "loggs",
                "banana",
            }
        ),
        "mid": frozenset({"speedway", "arch", "long", "long_corner", "mid"}),
    },
    "de_nuke": {
        "a": frozenset({"hut", "squeakly", "main", "heaven", "vents"}),
        "b": frozenset({"ramp", "dark", "control", "double", "single", "back_vents"}),
        "mid": frozenset({"outside", "garage", "red", "secret", "locker", "ct_box"}),
    },
    "de_overpass": {
        "a": frozenset({"bank", "truck", "toilets", "long", "long_toilets", "short_a", "a_main"}),
        "b": frozenset({"heaven", "water", "monster", "short_b", "barrels", "pit", "jail"}),
        "mid": frozenset({"con", "lower_con", "fountain", "party", "mid", "tracks"}),
    },
    "de_anubis": {
        "a": frozenset({"heaven", "a_main", "a_con", "plateau", "fountain"}),
        "b": frozenset({"b_con", "b_main", "backsite", "pillar", "ledge", "stairs"}),
        "mid": frozenset(
            {
                "mid",
                "sniper",
                "temple",
                "house",
                "doors",
                "top_mid",
                "bridge",
                "undercon",
                "canal",
                "boost",
                "water",
            }
        ),
    },
    "de_cache": {
        "a": frozenset({"nbk", "quad", "squeaky", "a_main", "shroud", "fork", "toxic"}),
        "b": frozenset(
            {
                "b_main",
                "checkers",
                "heaven",
                "tree_room",
                "ct",
                "truck",
                "new_box",
                "snax",
                "headshot",
                "b_halls",
            }
        ),
        "mid": frozenset(
            {"highway", "white_box", "boost", "pipes", "z", "sandbags", "vent", "mid", "garage"}
        ),
    },
}


__all__ = [
    "CTSetupCalculation",
    "compute_ct_setups",
    "ct_setup_profiles_from_insights",
    "ct_setup_role_metrics",
]
