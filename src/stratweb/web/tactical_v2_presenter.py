"""Read-only presentation model for the Tactical V2 inspection page."""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlencode
from uuid import UUID

from stratweb.domain.enums import Side
from stratweb.tactical_v2.models import TacticalInsight, TacticalInsightType

TACTICAL_V2_PAGE_SIZE = 18


@dataclass(frozen=True, slots=True)
class TacticalV2Filters:
    insight_type: TacticalInsightType | None = None
    map_name: str | None = None
    side: Side | None = None


@dataclass(frozen=True, slots=True)
class TacticalInsightCard:
    source: TacticalInsight
    title_key: str
    title_values: dict[str, object]
    description_key: str
    description_values: dict[str, object]
    frequency_percent: str
    frequency_band_key: str
    reliability_key: str
    reliability_class: str
    evidence_rounds: int


@dataclass(frozen=True, slots=True)
class TacticalV2Page:
    filters: TacticalV2Filters
    cards: tuple[TacticalInsightCard, ...]
    highlights: tuple[TacticalInsightCard, ...]
    maps: tuple[str, ...]
    type_counts: dict[TacticalInsightType, int]
    total_count: int
    filtered_count: int
    curated: bool
    page: int
    page_count: int
    previous_href: str | None
    next_href: str | None
    reset_href: str


def build_tactical_v2_page(
    profile_id: UUID,
    tactical_run_id: UUID,
    insights: tuple[TacticalInsight, ...],
    *,
    filters: TacticalV2Filters,
    page: int,
) -> TacticalV2Page:
    ordered = _ordered(insights)
    matching = tuple(item for item in ordered if _matches(item, filters))
    curated = filters.insight_type is None
    filtered = _representatives(matching, filters) if curated else matching
    page_count = max(1, math.ceil(len(filtered) / TACTICAL_V2_PAGE_SIZE))
    selected_page = min(page, page_count)
    start = (selected_page - 1) * TACTICAL_V2_PAGE_SIZE
    visible = filtered[start : start + TACTICAL_V2_PAGE_SIZE]
    highlights = _highlights(
        tuple(
            item for item in matching if item.insight_type is not TacticalInsightType.HEATMAP_CELL
        )
    )
    base_path = f"/ui/opponents/{profile_id}/tactical-v2"
    return TacticalV2Page(
        filters=filters,
        cards=tuple(build_tactical_insight_card(item) for item in visible),
        highlights=tuple(build_tactical_insight_card(item) for item in highlights),
        maps=tuple(sorted({item.map_name for item in insights})),
        type_counts={
            insight_type: sum(item.insight_type is insight_type for item in insights)
            for insight_type in TacticalInsightType
        },
        total_count=len(insights),
        filtered_count=len(filtered),
        curated=curated,
        page=selected_page,
        page_count=page_count,
        previous_href=(
            _href(base_path, tactical_run_id, filters, selected_page - 1)
            if selected_page > 1
            else None
        ),
        next_href=(
            _href(base_path, tactical_run_id, filters, selected_page + 1)
            if selected_page < page_count
            else None
        ),
        reset_href=f"{base_path}?run_id={tactical_run_id}",
    )


def _matches(item: TacticalInsight, filters: TacticalV2Filters) -> bool:
    return bool(
        (filters.insight_type is None or item.insight_type is filters.insight_type)
        and (filters.map_name is None or item.map_name == filters.map_name)
        and (filters.side is None or item.side is filters.side)
    )


def _highlights(insights: tuple[TacticalInsight, ...]) -> tuple[TacticalInsight, ...]:
    result: list[TacticalInsight] = []
    used: set[TacticalInsightType] = set()
    for item in insights:
        if item.insight_type in used:
            continue
        used.add(item.insight_type)
        result.append(item)
    return tuple(
        sorted(
            result,
            key=lambda item: (-item.denominator, -item.frequency, item.insight_type.value),
        )[:3]
    )


def _representatives(
    insights: tuple[TacticalInsight, ...], filters: TacticalV2Filters
) -> tuple[TacticalInsight, ...]:
    """Keep the default view short; explicit filters reveal progressively more detail."""

    result: list[TacticalInsight] = []
    used: set[tuple[object, ...]] = set()
    for item in insights:
        group: tuple[object, ...] = (item.insight_type,)
        if filters.map_name is not None:
            group += (item.side,)
        if filters.side is not None:
            group += (item.map_name,)
        if group in used:
            continue
        used.add(group)
        result.append(item)
    return tuple(result)


def _ordered(insights: tuple[TacticalInsight, ...]) -> tuple[TacticalInsight, ...]:
    grouped = {
        insight_type: sorted(
            (item for item in insights if item.insight_type is insight_type),
            key=lambda item: (
                -item.denominator,
                -item.frequency,
                item.map_name,
                item.side.value,
                item.key,
            ),
        )
        for insight_type in TacticalInsightType
    }
    maximum = max((len(items) for items in grouped.values()), default=0)
    return tuple(
        grouped[insight_type][index]
        for index in range(maximum)
        for insight_type in TacticalInsightType
        if index < len(grouped[insight_type])
    )


def build_tactical_insight_card(item: TacticalInsight) -> TacticalInsightCard:
    title_key, title_values = _title(item)
    if item.insight_type in {
        TacticalInsightType.PATH_CLUSTER,
        TacticalInsightType.EXECUTE_PACKAGE,
        TacticalInsightType.ROTATION_TRANSITION,
        TacticalInsightType.HEATMAP_CELL,
    }:
        description_key = "tactical.card.description.observed"
    else:
        description_key = "tactical.card.description.confirmed"
    return TacticalInsightCard(
        source=item,
        title_key=title_key,
        title_values=title_values,
        description_key=description_key,
        description_values={"numerator": item.numerator, "denominator": item.denominator},
        frequency_percent=f"{item.frequency * 100:.1f}%",
        frequency_band_key=_frequency_band_key(item.frequency),
        reliability_key=_reliability_key(item),
        reliability_class="warn" if item.small_sample_warning else "good",
        evidence_rounds=len(item.evidence_references),
    )


def _frequency_band_key(frequency: float) -> str:
    if frequency >= 1.0:
        return "tactical.frequency.every_time"
    if frequency >= 0.75:
        return "tactical.frequency.almost_always"
    if frequency >= 0.5:
        return "tactical.frequency.often"
    if frequency >= 0.25:
        return "tactical.frequency.sometimes"
    if frequency > 0:
        return "tactical.frequency.rarely"
    return "tactical.frequency.not_seen"


def _reliability_key(item: TacticalInsight) -> str:
    if item.match_count == 1:
        return "tactical.reliability.one_match"
    if item.small_sample_warning:
        return "tactical.reliability.preliminary"
    return "tactical.reliability.repeatable"


def _title(item: TacticalInsight) -> tuple[str, dict[str, object]]:
    if item.insight_type is TacticalInsightType.PATH_CLUSTER:
        return "tactical.card.title.path_cluster", {}
    if item.insight_type is TacticalInsightType.EXECUTE_PACKAGE:
        site = item.key.partition("site:")[2].partition("|")[0]
        return "tactical.card.title.execute_package", {"site": site or "?"}
    if item.insight_type is TacticalInsightType.UTILITY_OUTCOME:
        return (
            "tactical.card.title.utility_he"
            if item.key == "he"
            else "tactical.card.title.utility_fire"
        ), {}
    if item.insight_type is TacticalInsightType.SPACING_PROFILE:
        checkpoint = item.key.partition(":")[2]
        moment = {"640": "early", "1280": "middle", "1920": "late"}.get(checkpoint, "checkpoint")
        return f"tactical.card.title.spacing_{moment}", {}
    if item.insight_type is TacticalInsightType.ENTRY_STRUCTURE:
        return "tactical.card.title.entry_structure", {}
    if item.insight_type is TacticalInsightType.TRADE_STRUCTURE:
        return "tactical.card.title.trade_structure", {}
    if item.insight_type is TacticalInsightType.ROTATION_TRANSITION:
        return "tactical.card.title.rotation_transition", {}
    if item.insight_type is TacticalInsightType.CLUTCH_BEHAVIOR:
        return "tactical.card.title.clutch_behavior", {}
    if item.insight_type is TacticalInsightType.SAVE_BEHAVIOR:
        return "tactical.card.title.save_behavior", {}
    if item.insight_type is TacticalInsightType.HEATMAP_CELL:
        cell_x = _numeric_metric(item, "cell_x_median")
        cell_y = _numeric_metric(item, "cell_y_median")
        if cell_x is not None and cell_y is not None:
            return "tactical.card.title.heatmap_cell_xy", {
                "x": round(cell_x),
                "y": round(cell_y),
            }
        return "tactical.card.title.heatmap_cell", {}
    return "tactical.card.title.fallback", {"label": item.label}


def _numeric_metric(item: TacticalInsight, key: str) -> float | None:
    value = item.metrics.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _href(
    base_path: str,
    tactical_run_id: UUID,
    filters: TacticalV2Filters,
    page: int,
) -> str:
    values: list[tuple[str, str | int]] = [("run_id", str(tactical_run_id))]
    if filters.insight_type is not None:
        values.append(("type", filters.insight_type.value))
    if filters.map_name is not None:
        values.append(("map", filters.map_name))
    if filters.side is not None:
        values.append(("side", filters.side.value))
    if page > 1:
        values.append(("page", page))
    return f"{base_path}?{urlencode(values)}"


__all__ = [
    "TACTICAL_V2_PAGE_SIZE",
    "TacticalInsightCard",
    "TacticalV2Filters",
    "TacticalV2Page",
    "build_tactical_insight_card",
    "build_tactical_v2_page",
]
