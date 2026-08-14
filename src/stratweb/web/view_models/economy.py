"""Typed, evidence-preserving presentation models for the Economy UI."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from pydantic import Field

from stratweb.domain.enums import Side
from stratweb.economy.models import (
    EconomyRunSummary,
    EvidenceAvailability,
    EvidenceValue,
    PlayerEquipmentSnapshot,
    TeamEconomySnapshot,
)
from stratweb.web.view_models.product import ViewModel


class EconomyPlayerView(ViewModel):
    name: str
    equipment_value: str
    cash_spent: str
    balance: str
    armor: str
    helmet: str
    defuse_kit: str
    inventory: tuple[str, ...]
    evidence_status: str
    warnings: tuple[str, ...]


class EconomyTeamView(ViewModel):
    side: str
    team_name: str
    buy_type: str
    classification_status: str
    player_count: int = Field(ge=0)
    equipment_value: str
    cash_spent: str
    balance: str
    helmets: str
    defuse_kits: str
    score_before: str
    players: tuple[EconomyPlayerView, ...]
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


class EconomyRoundView(ViewModel):
    round_number: int = Field(ge=1)
    freeze_end_tick: int | None = Field(default=None, ge=0)
    overtime: bool | None = None
    t: EconomyTeamView | None = None
    ct: EconomyTeamView | None = None


class EconomyPageView(ViewModel):
    match_id: UUID
    economy_run_id: UUID
    coverage: str
    eligible_team_rounds: int = Field(ge=0)
    classified_team_rounds: int = Field(ge=0)
    unknown_team_rounds: int = Field(ge=0)
    round_count: int = Field(ge=0)
    player_snapshot_count: int = Field(ge=0)
    team_snapshot_count: int = Field(ge=0)
    buy_type_counts: dict[str, int]
    rounds: tuple[EconomyRoundView, ...]
    economy_schema_version: str
    economy_rule_version: str
    item_category_version: str
    value_policy_version: str
    parser: str
    warnings: tuple[str, ...]


def build_economy_page(
    summary: EconomyRunSummary,
    team_snapshots: tuple[TeamEconomySnapshot, ...],
    player_snapshots: tuple[PlayerEquipmentSnapshot, ...],
    team_names: dict[UUID, str],
) -> EconomyPageView:
    """Build one pinned-run page without inventing missing evidence."""

    players_by_round_side: dict[tuple[int, Side], list[PlayerEquipmentSnapshot]] = defaultdict(list)
    for player in player_snapshots:
        players_by_round_side[(player.round_number, player.side)].append(player)

    teams_by_round_side = {(item.round_number, item.side): item for item in team_snapshots}
    round_numbers = sorted({item.round_number for item in team_snapshots})
    round_views: list[EconomyRoundView] = []
    for round_number in round_numbers:
        t_snapshot = teams_by_round_side.get((round_number, Side.T))
        ct_snapshot = teams_by_round_side.get((round_number, Side.CT))
        representative = t_snapshot or ct_snapshot
        overtime_evidence = representative.is_overtime if representative is not None else None
        overtime = overtime_evidence.value if overtime_evidence is not None else None
        round_views.append(
            EconomyRoundView(
                round_number=round_number,
                freeze_end_tick=(representative.freeze_end_tick if representative else None),
                overtime=overtime,
                t=_team_view(
                    t_snapshot,
                    players_by_round_side.get((round_number, Side.T), []),
                    team_names,
                ),
                ct=_team_view(
                    ct_snapshot,
                    players_by_round_side.get((round_number, Side.CT), []),
                    team_names,
                ),
            )
        )

    coverage = (
        f"{summary.capability.coverage * 100:.1f}%"
        if summary.capability.coverage is not None
        else "Unavailable"
    )
    return EconomyPageView(
        match_id=summary.match_id,
        economy_run_id=summary.economy_run_id,
        coverage=coverage,
        eligible_team_rounds=summary.capability.eligible_team_rounds,
        classified_team_rounds=summary.capability.classified_team_rounds,
        unknown_team_rounds=summary.capability.unknown_team_rounds,
        round_count=summary.summary.rounds,
        player_snapshot_count=summary.summary.player_snapshots,
        team_snapshot_count=summary.summary.team_snapshots,
        buy_type_counts={
            key.value: value for key, value in summary.summary.buy_type_counts.items()
        },
        rounds=tuple(round_views),
        economy_schema_version=summary.economy_schema_version,
        economy_rule_version=summary.economy_rule_version,
        item_category_version=summary.item_category_version,
        value_policy_version=summary.value_policy_version,
        parser=f"{summary.parser_name} {summary.parser_version}",
        warnings=tuple(dict.fromkeys((*summary.capability.warnings, *summary.warnings))),
    )


def _team_view(
    snapshot: TeamEconomySnapshot | None,
    players: list[PlayerEquipmentSnapshot],
    team_names: dict[UUID, str],
) -> EconomyTeamView | None:
    if snapshot is None:
        return None
    name = (
        team_names.get(snapshot.team_id, "Unknown physical team")
        if snapshot.team_id
        else "Unknown physical team"
    )
    return EconomyTeamView(
        side=snapshot.side.value,
        team_name=name,
        buy_type=snapshot.buy_type.value,
        classification_status=_status(snapshot.classification_availability),
        player_count=snapshot.player_count,
        equipment_value=_money(snapshot.equipment_value),
        cash_spent=_money(snapshot.cash_spent),
        balance=_money(snapshot.balance),
        helmets=_number(snapshot.helmet_count),
        defuse_kits=_number(snapshot.defuse_kit_count),
        score_before=_number(snapshot.score_for_before),
        players=tuple(
            _player_view(item)
            for item in sorted(players, key=lambda value: value.player_name.casefold())
        ),
        reasons=snapshot.exclusion_reasons,
        warnings=snapshot.warnings,
    )


def _player_view(snapshot: PlayerEquipmentSnapshot) -> EconomyPlayerView:
    inventory = snapshot.inventory.value or ()
    return EconomyPlayerView(
        name=snapshot.player_name,
        equipment_value=_money(snapshot.equipment_value),
        cash_spent=_money(snapshot.cash_spent),
        balance=_money(snapshot.balance),
        armor=_number(snapshot.armor_value),
        helmet=_boolean(snapshot.has_helmet),
        defuse_kit=_boolean(snapshot.has_defuser),
        inventory=tuple(_human_item(item) for item in inventory),
        evidence_status=_status(snapshot.equipment_value.availability),
        warnings=tuple(dict.fromkeys((*snapshot.exclusion_reasons, *snapshot.warnings))),
    )


def _money(evidence: EvidenceValue[int]) -> str:
    return f"${evidence.value:,}" if evidence.value is not None else "Unavailable"


def _number(evidence: EvidenceValue[int]) -> str:
    return str(evidence.value) if evidence.value is not None else "Unavailable"


def _boolean(evidence: EvidenceValue[bool]) -> str:
    if evidence.value is None:
        return "Unavailable"
    return "Yes" if evidence.value else "No"


def _status(availability: EvidenceAvailability) -> str:
    if availability is EvidenceAvailability.AVAILABLE:
        return "available"
    if availability is EvidenceAvailability.PARTIAL:
        return "partial"
    return "unavailable"


def _human_item(value: str) -> str:
    normalized = value.removeprefix("weapon_").removeprefix("item_")
    return normalized.replace("_", " ").strip().title() or value


__all__ = [
    "EconomyPageView",
    "EconomyPlayerView",
    "EconomyRoundView",
    "EconomyTeamView",
    "build_economy_page",
]
