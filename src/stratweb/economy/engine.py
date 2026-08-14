"""Pure deterministic freeze-end economy computation."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from stratweb.application.canonical_models import (
    CanonicalPlayer,
    CanonicalRound,
    DataAvailability,
    PlayerTeamMembership,
)
from stratweb.application.normalization_utils import canonical_json
from stratweb.application.persistence_models import StoredMatch
from stratweb.domain.enums import Side
from stratweb.economy.models import (
    ECONOMY_ITEM_CATEGORY_VERSION,
    ECONOMY_RULE_VERSION,
    ECONOMY_SCHEMA_VERSION,
    ECONOMY_VALUE_POLICY_VERSION,
    BuyType,
    EconomyCapability,
    EconomyConfig,
    EconomyExtraction,
    EconomySourceSample,
    EconomyState,
    EconomySummary,
    EvidenceAvailability,
    EvidenceValue,
    PlayerEquipmentSnapshot,
    TeamEconomySnapshot,
)
from stratweb.exceptions import EconomyConfigurationError

_SOURCE_PREFIX = "demoparser2:parse_ticks"
_UTILITY_NAMES = frozenset(
    {
        "decoy",
        "decoygrenade",
        "flashbang",
        "hegrenade",
        "incgrenade",
        "incendiarygrenade",
        "molotov",
        "smoke",
        "smokegrenade",
    }
)
_NON_WEAPON_INVENTORY_NAMES = frozenset(
    {
        "assaultsuit",
        "c4",
        "defuser",
        "heavyassaultsuit",
        "helmet",
        "kevlar",
        "vest",
        "vesthelm",
    }
)


class EconomyEngine:
    """Compute immutable economy evidence without parser-specific rows escaping."""

    def compute(
        self,
        match: StoredMatch,
        rounds: Sequence[CanonicalRound],
        players: Sequence[CanonicalPlayer],
        memberships: Sequence[PlayerTeamMembership],
        extraction: EconomyExtraction,
        config: EconomyConfig,
    ) -> EconomyState:
        if extraction.source_demo_sha256 != match.source_demo_sha256:
            raise EconomyConfigurationError(
                "Economy source demo SHA-256 does not match the canonical match."
            )
        config_hash = _sha(canonical_json(config.model_dump(mode="json")))
        samples_payload = [item.model_dump(mode="json") for item in extraction.samples]
        fingerprint = _sha(
            canonical_json(
                {
                    "schema": ECONOMY_SCHEMA_VERSION,
                    "rule": ECONOMY_RULE_VERSION,
                    "item_categories": ECONOMY_ITEM_CATEGORY_VERSION,
                    "value_policy": ECONOMY_VALUE_POLICY_VERSION,
                    "dataset_fingerprint": match.dataset_fingerprint,
                    "source_demo_sha256": extraction.source_demo_sha256,
                    "parser": [extraction.parser_name, extraction.parser_version],
                    "config_hash": config_hash,
                    "source_columns": extraction.source_columns,
                    "samples": samples_payload,
                }
            )
        )
        run_id = uuid5(NAMESPACE_URL, f"stratweb:economy:{fingerprint}")
        by_tick_steam: dict[tuple[int, str], list[EconomySourceSample]] = defaultdict(list)
        for source_sample in extraction.samples:
            if source_sample.steam_id is not None:
                by_tick_steam[(source_sample.tick, source_sample.steam_id)].append(source_sample)
        player_snapshots: list[PlayerEquipmentSnapshot] = []
        team_snapshots: list[TeamEconomySnapshot] = []
        ordered_players = sorted(players, key=lambda item: str(item.player_id))
        players_by_id = {item.player_id: item for item in ordered_players}

        for round_item in sorted(rounds, key=lambda item: item.round_number):
            tick = round_item.freeze_end_tick
            round_exclusions = _round_exclusions(round_item, config)
            for side, team_id in ((Side.T, round_item.t_team_id), (Side.CT, round_item.ct_team_id)):
                active = _active_memberships(memberships, team_id, tick)
                snapshots: list[PlayerEquipmentSnapshot] = []
                for membership in active:
                    player = players_by_id.get(membership.player_id)
                    if player is None:
                        continue
                    candidates = (
                        by_tick_steam.get((tick, player.steam_id), [])
                        if tick is not None and player.steam_id is not None
                        else []
                    )
                    selected_sample = candidates[0] if len(candidates) == 1 else None
                    warnings = (
                        ("duplicate_source_rows_for_player_tick",) if len(candidates) > 1 else ()
                    )
                    player_exclusions = list(round_exclusions)
                    if selected_sample is None:
                        player_exclusions.append("freeze_end_player_sample_unavailable")
                    if membership.side is not side:
                        player_exclusions.append("canonical_membership_side_conflict")
                    snapshot = _player_snapshot(
                        run_id,
                        round_item,
                        player,
                        membership,
                        side,
                        team_id,
                        selected_sample,
                        extraction.source_columns,
                        tuple(dict.fromkeys(player_exclusions)),
                        warnings,
                    )
                    snapshots.append(snapshot)
                    player_snapshots.append(snapshot)
                team_snapshot = _team_snapshot(
                    run_id,
                    round_item,
                    side,
                    team_id,
                    snapshots,
                    config,
                    round_exclusions,
                )
                team_snapshots.append(team_snapshot)

        counts = Counter(item.buy_type for item in team_snapshots)
        side_counts = Counter(f"{item.side.value}:{item.buy_type.value}" for item in team_snapshots)
        classified = sum(item.buy_type is not BuyType.UNKNOWN for item in team_snapshots)
        eligible = sum(item.eligible for item in team_snapshots)
        excluded = sum(not item.eligible for item in team_snapshots)
        capability = EconomyCapability(
            team_rounds=len(team_snapshots),
            eligible_team_rounds=eligible,
            classified_team_rounds=classified,
            unknown_team_rounds=len(team_snapshots) - classified,
            excluded_team_rounds=excluded,
            coverage=classified / eligible if eligible else None,
            warnings=(
                ("economy_source_columns_missing:" + ",".join(_missing_columns(extraction)),)
                if _missing_columns(extraction)
                else ()
            ),
        )
        summary = EconomySummary(
            rounds=len(rounds),
            player_snapshots=len(player_snapshots),
            team_snapshots=len(team_snapshots),
            buy_type_counts={kind: counts[kind] for kind in BuyType},
            side_buy_type_counts=dict(sorted(side_counts.items())),
        )
        warnings = tuple(
            dict.fromkeys(
                (
                    *extraction.warnings,
                    *capability.warnings,
                    *(("no_eligible_team_rounds",) if capability.eligible_team_rounds == 0 else ()),
                )
            )
        )
        return EconomyState(
            economy_run_id=run_id,
            economy_fingerprint=fingerprint,
            economy_config_hash=config_hash,
            match_id=match.match_id,
            dataset_fingerprint=match.dataset_fingerprint,
            source_demo_sha256=match.source_demo_sha256,
            parser_name=extraction.parser_name,
            parser_version=extraction.parser_version,
            config=config,
            capability=capability,
            summary=summary,
            source_columns=extraction.source_columns,
            player_snapshots=tuple(player_snapshots),
            team_snapshots=tuple(team_snapshots),
            warnings=warnings,
        )


def _round_exclusions(round_item: CanonicalRound, config: EconomyConfig) -> tuple[str, ...]:
    reasons: list[str] = []
    if config.exclude_warmup and round_item.is_warmup:
        reasons.append("warmup_round")
    if config.exclude_incomplete_rounds and not round_item.is_complete:
        reasons.append("incomplete_round")
    if config.require_freeze_end_tick and round_item.freeze_end_tick is None:
        reasons.append("freeze_end_tick_unavailable")
    return tuple(reasons)


def _active_memberships(
    memberships: Sequence[PlayerTeamMembership],
    team_id: UUID | None,
    tick: int | None,
) -> tuple[PlayerTeamMembership, ...]:
    if team_id is None or tick is None:
        return ()
    values = [
        item
        for item in memberships
        if item.team_id == team_id
        and item.valid_from_tick <= tick
        and (item.valid_to_tick is None or tick <= item.valid_to_tick)
    ]
    by_player: dict[UUID, PlayerTeamMembership] = {}
    for item in sorted(values, key=lambda value: (value.valid_from_tick, str(value.player_id))):
        by_player[item.player_id] = item
    return tuple(by_player[key] for key in sorted(by_player, key=str))


def _player_snapshot(
    run_id: UUID,
    round_item: CanonicalRound,
    player: CanonicalPlayer,
    membership: PlayerTeamMembership,
    side: Side,
    team_id: UUID | None,
    sample: EconomySourceSample | None,
    source_columns: tuple[str, ...],
    exclusions: tuple[str, ...],
    warnings: tuple[str, ...],
) -> PlayerEquipmentSnapshot:
    context = (sample, frozenset(source_columns))
    inventory = _field(context, "inventory", sample.inventory if sample else None)
    source_team_number = _field(context, "team_num", sample.team_num if sample else None)
    expected_team_number = 2 if side is Side.T else 3
    normalized_exclusions = list(exclusions)
    if (
        source_team_number.availability is EvidenceAvailability.AVAILABLE
        and source_team_number.value != expected_team_number
    ):
        normalized_exclusions.append("source_team_number_conflict")
    final_exclusions = tuple(dict.fromkeys(normalized_exclusions))
    weapons = _derived_items(inventory, utility=False)
    utility = _derived_items(inventory, utility=True)
    return PlayerEquipmentSnapshot(
        player_snapshot_id=uuid5(run_id, f"player:{round_item.round_number}:{player.player_id}"),
        economy_run_id=run_id,
        match_id=round_item.match_id,
        round_id=round_item.round_id,
        round_number=round_item.round_number,
        freeze_end_tick=round_item.freeze_end_tick,
        participant_id=player.player_id,
        steam_id=player.steam_id,
        player_name=player.current_name,
        team_id=team_id,
        team_source="canonical_round.side_team_id+canonical_membership.team_id",
        side=side,
        side_source="canonical_round.side_team_id",
        source_team_number=source_team_number,
        equipment_value=_field(
            context, "current_equip_value", sample.current_equip_value if sample else None
        ),
        round_start_equipment_value=_field(
            context,
            "round_start_equip_value",
            sample.round_start_equip_value if sample else None,
        ),
        cash_spent=_field(
            context,
            "cash_spent_this_round",
            sample.cash_spent_this_round if sample else None,
        ),
        balance=_field(context, "balance", sample.balance if sample else None),
        inventory=inventory,
        inventory_item_ids=_field(
            context,
            "inventory_as_ids",
            sample.inventory_item_ids if sample else None,
        ),
        weapons=weapons,
        utility=utility,
        armor_value=_field(context, "armor_value", sample.armor_value if sample else None),
        has_helmet=_field(context, "has_helmet", sample.has_helmet if sample else None),
        has_defuser=_field(context, "has_defuser", sample.has_defuser if sample else None),
        total_rounds_played=_field(
            context,
            "total_rounds_played",
            sample.total_rounds_played if sample else None,
        ),
        eligible=not final_exclusions,
        exclusion_reasons=final_exclusions,
        warnings=warnings,
    )


U = TypeVar("U")


def _field(
    context: tuple[EconomySourceSample | None, frozenset[str]],
    field: str,
    value: U | None,
) -> EvidenceValue[U]:
    sample, columns = context
    source = f"{_SOURCE_PREFIX}.{field}"
    if field not in columns:
        return EvidenceValue(
            availability=EvidenceAvailability.MISSING_FROM_SOURCE,
            population=1,
            available_count=0,
        )
    if sample is None:
        return EvidenceValue(
            availability=EvidenceAvailability.UNRESOLVED,
            source=source,
            population=1,
            available_count=0,
            warnings=("player_tick_row_unavailable",),
        )
    if field in sample.invalid_fields or value is None:
        return EvidenceValue(
            availability=EvidenceAvailability.UNRESOLVED,
            source=source,
            population=1,
            available_count=0,
            warnings=(("invalid_source_value",) if field in sample.invalid_fields else ()),
        )
    return EvidenceValue(
        value=value,
        availability=EvidenceAvailability.AVAILABLE,
        source=source,
        population=1,
        available_count=1,
    )


def _derived_items(
    inventory: EvidenceValue[tuple[str, ...]], *, utility: bool
) -> EvidenceValue[tuple[str, ...]]:
    if inventory.availability is not EvidenceAvailability.AVAILABLE:
        return EvidenceValue(
            availability=inventory.availability,
            source=inventory.source,
            population=inventory.population,
            available_count=inventory.available_count,
            warnings=inventory.warnings,
        )
    values = tuple(
        item
        for item in inventory.value or ()
        if (
            (_normalize_item(item) in _UTILITY_NAMES)
            if utility
            else (
                _normalize_item(item) not in _UTILITY_NAMES
                and _normalize_item(item) not in _NON_WEAPON_INVENTORY_NAMES
            )
        )
    )
    return EvidenceValue(
        value=values,
        availability=EvidenceAvailability.AVAILABLE,
        source=f"derived:inventory:{ECONOMY_ITEM_CATEGORY_VERSION}",
        population=1,
        available_count=1,
    )


def _team_snapshot(
    run_id: UUID,
    round_item: CanonicalRound,
    side: Side,
    team_id: UUID | None,
    players: Sequence[PlayerEquipmentSnapshot],
    config: EconomyConfig,
    round_exclusions: tuple[str, ...],
) -> TeamEconomySnapshot:
    exclusions = list(round_exclusions)
    if team_id is None:
        exclusions.append("physical_team_unresolved")
    if config.require_complete_roster and len(players) != config.expected_team_size:
        exclusions.append(f"roster_size_mismatch:{len(players)}:{config.expected_team_size}")
    if any(not item.eligible for item in players):
        exclusions.append("player_snapshot_ineligible")
    equipment = _sum_int(item.equipment_value for item in players)
    start_equipment = _sum_int(item.round_start_equipment_value for item in players)
    spent = _sum_int(item.cash_spent for item in players)
    balance = _sum_int(item.balance for item in players)
    weapons = _join_items(item.weapons for item in players)
    utility = _join_items(item.utility for item in players)
    armor = _sum_int(item.armor_value for item in players)
    helmets = _count_true(item.has_helmet for item in players)
    kits = _count_true(item.has_defuser for item in players)
    total_rounds = _consensus_int(item.total_rounds_played for item in players)
    score_for, score_against = _score_evidence(round_item, side)
    overtime: EvidenceValue[bool] = EvidenceValue(
        value=round_item.is_overtime,
        availability=EvidenceAvailability.AVAILABLE,
        source="canonical_round.is_overtime",
        population=1,
        available_count=1,
    )
    if config.require_complete_equipment_value and (
        equipment.availability is not EvidenceAvailability.AVAILABLE
    ):
        exclusions.append("complete_equipment_value_unavailable")
    exclusions_tuple = tuple(dict.fromkeys(exclusions))
    eligible = not exclusions_tuple
    buy_type, availability, source, classification_warnings = _classify(
        equipment,
        spent,
        score_for,
        score_against,
        overtime,
        eligible,
        config,
    )
    return TeamEconomySnapshot(
        team_snapshot_id=uuid5(run_id, f"team:{round_item.round_number}:{side.value}"),
        economy_run_id=run_id,
        match_id=round_item.match_id,
        round_id=round_item.round_id,
        round_number=round_item.round_number,
        freeze_end_tick=round_item.freeze_end_tick,
        team_id=team_id,
        team_source="canonical_round.side_team_id",
        side=side,
        side_source="canonical_round.side_team_id",
        player_count=len(players),
        equipment_value=equipment,
        round_start_equipment_value=start_equipment,
        cash_spent=spent,
        balance=balance,
        weapons=weapons,
        utility=utility,
        armor_value=armor,
        helmet_count=helmets,
        defuse_kit_count=kits,
        total_rounds_played=total_rounds,
        score_for_before=score_for,
        score_against_before=score_against,
        is_overtime=overtime,
        buy_type=buy_type,
        classification_availability=availability,
        classification_source=source,
        eligible=eligible,
        exclusion_reasons=exclusions_tuple,
        warnings=classification_warnings,
    )


def _classify(
    equipment: EvidenceValue[int],
    spent: EvidenceValue[int],
    score_for: EvidenceValue[int],
    score_against: EvidenceValue[int],
    overtime: EvidenceValue[bool],
    eligible: bool,
    config: EconomyConfig,
) -> tuple[BuyType, EvidenceAvailability, str | None, tuple[str, ...]]:
    if not eligible:
        return BuyType.UNKNOWN, EvidenceAvailability.NOT_APPLICABLE, None, ()
    if equipment.availability is not EvidenceAvailability.AVAILABLE:
        return (
            BuyType.UNKNOWN,
            equipment.availability,
            None,
            ("equipment_value_not_complete",),
        )
    score_available = all(
        item.availability is EvidenceAvailability.AVAILABLE
        for item in (score_for, score_against, overtime)
    )
    if score_available:
        score_total = int(score_for.value or 0) + int(score_against.value or 0)
        if not bool(overtime.value) and score_total in {0, 12}:
            return (
                BuyType.PISTOL,
                EvidenceAvailability.AVAILABLE,
                f"{ECONOMY_RULE_VERSION}:regulation_half_opening_score",
                (),
            )
    value = int(equipment.value or 0)
    if value >= config.full_min_equipment_value:
        return BuyType.FULL, EvidenceAvailability.AVAILABLE, ECONOMY_RULE_VERSION, ()
    if spent.availability is EvidenceAvailability.AVAILABLE:
        spent_value = int(spent.value or 0)
        if spent_value >= config.force_min_cash_spent:
            return BuyType.FORCE, EvidenceAvailability.AVAILABLE, ECONOMY_RULE_VERSION, ()
        if value <= config.eco_max_equipment_value and spent_value <= config.eco_max_cash_spent:
            return BuyType.ECO, EvidenceAvailability.AVAILABLE, ECONOMY_RULE_VERSION, ()
    if value > config.eco_max_equipment_value:
        return BuyType.SEMI, EvidenceAvailability.AVAILABLE, ECONOMY_RULE_VERSION, ()
    return (
        BuyType.UNKNOWN,
        EvidenceAvailability.UNRESOLVED,
        None,
        ("low_equipment_without_proven_eco_spend",),
    )


def _sum_int(values: Iterable[EvidenceValue[int]]) -> EvidenceValue[int]:
    items = tuple(values)
    available = [item for item in items if item.availability is EvidenceAvailability.AVAILABLE]
    return _aggregate(sum(int(item.value or 0) for item in available), items, len(available))


def _count_true(values: Iterable[EvidenceValue[bool]]) -> EvidenceValue[int]:
    items = tuple(values)
    available = [item for item in items if item.availability is EvidenceAvailability.AVAILABLE]
    return _aggregate(sum(bool(item.value) for item in available), items, len(available))


def _join_items(
    values: Iterable[EvidenceValue[tuple[str, ...]]],
) -> EvidenceValue[tuple[str, ...]]:
    items = tuple(values)
    available = [item for item in items if item.availability is EvidenceAvailability.AVAILABLE]
    flattened = tuple(value for item in available for value in (item.value or ()))
    return _aggregate(flattened, items, len(available))


def _consensus_int(values: Iterable[EvidenceValue[int]]) -> EvidenceValue[int]:
    items = tuple(values)
    available = [item for item in items if item.availability is EvidenceAvailability.AVAILABLE]
    unique = {int(item.value or 0) for item in available}
    if items and len(available) == len(items) and len(unique) == 1:
        return EvidenceValue(
            value=next(iter(unique)),
            availability=EvidenceAvailability.AVAILABLE,
            source="aggregate:player_consensus",
            population=len(items),
            available_count=len(items),
        )
    status = _aggregate_status(items, len(available))
    return EvidenceValue(
        availability=status,
        source="aggregate:player_consensus" if items else None,
        population=len(items),
        available_count=len(available),
        warnings=(("conflicting_player_values",) if len(unique) > 1 else ()),
    )


def _aggregate(
    value: U,
    items: Sequence[EvidenceValue[Any]],
    available_count: int,
) -> EvidenceValue[U]:
    status = _aggregate_status(items, available_count)
    if status in {EvidenceAvailability.AVAILABLE, EvidenceAvailability.PARTIAL}:
        return EvidenceValue(
            value=value,
            availability=status,
            source="aggregate:freeze_end_players",
            population=len(items),
            available_count=available_count,
        )
    return EvidenceValue(
        availability=status,
        source="aggregate:freeze_end_players" if items else None,
        population=len(items),
        available_count=available_count,
    )


def _aggregate_status(
    items: Sequence[EvidenceValue[Any]], available_count: int
) -> EvidenceAvailability:
    if not items:
        return EvidenceAvailability.UNRESOLVED
    if available_count == len(items):
        return EvidenceAvailability.AVAILABLE
    if available_count:
        return EvidenceAvailability.PARTIAL
    if all(item.availability is EvidenceAvailability.MISSING_FROM_SOURCE for item in items):
        return EvidenceAvailability.MISSING_FROM_SOURCE
    return EvidenceAvailability.UNRESOLVED


def _score_evidence(
    round_item: CanonicalRound, side: Side
) -> tuple[EvidenceValue[int], EvidenceValue[int]]:
    if round_item.score_status is DataAvailability.AVAILABLE:
        own = round_item.score_t_before if side is Side.T else round_item.score_ct_before
        other = round_item.score_ct_before if side is Side.T else round_item.score_t_before
        if own is not None and other is not None:
            source = round_item.score_source or "canonical_round.score_before"
            return (
                EvidenceValue(
                    value=own,
                    availability=EvidenceAvailability.AVAILABLE,
                    source=source,
                    population=1,
                    available_count=1,
                ),
                EvidenceValue(
                    value=other,
                    availability=EvidenceAvailability.AVAILABLE,
                    source=source,
                    population=1,
                    available_count=1,
                ),
            )
    unavailable = EvidenceValue[int](
        availability=EvidenceAvailability.MISSING_FROM_SOURCE,
        population=1,
        available_count=0,
    )
    return unavailable, unavailable


def _normalize_item(value: str) -> str:
    return value.casefold().replace("weapon_", "").replace("item_", "").replace("_", "").strip()


def _missing_columns(extraction: EconomyExtraction) -> tuple[str, ...]:
    return tuple(
        field for field in extraction.requested_fields if field not in extraction.source_columns
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["EconomyEngine"]
