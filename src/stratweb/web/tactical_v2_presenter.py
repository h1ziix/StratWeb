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
    title: str
    description: str
    frequency_percent: str
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
    filtered = tuple(item for item in ordered if _matches(item, filters))
    page_count = max(1, math.ceil(len(filtered) / TACTICAL_V2_PAGE_SIZE))
    selected_page = min(page, page_count)
    start = (selected_page - 1) * TACTICAL_V2_PAGE_SIZE
    visible = filtered[start : start + TACTICAL_V2_PAGE_SIZE]
    highlights = _highlights(
        tuple(
            item for item in filtered if item.insight_type is not TacticalInsightType.HEATMAP_CELL
        )
    )
    base_path = f"/ui/opponents/{profile_id}/tactical-v2"
    return TacticalV2Page(
        filters=filters,
        cards=tuple(_card(item) for item in visible),
        highlights=tuple(_card(item) for item in highlights),
        maps=tuple(sorted({item.map_name for item in insights})),
        type_counts={
            insight_type: sum(item.insight_type is insight_type for item in insights)
            for insight_type in TacticalInsightType
        },
        total_count=len(insights),
        filtered_count=len(filtered),
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
        if len(result) == 6:
            break
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


def _card(item: TacticalInsight) -> TacticalInsightCard:
    title = _title(item)
    if item.insight_type in {
        TacticalInsightType.PATH_CLUSTER,
        TacticalInsightType.EXECUTE_PACKAGE,
        TacticalInsightType.ROTATION_TRANSITION,
        TacticalInsightType.HEATMAP_CELL,
    }:
        description = (
            f"Наблюдалось {item.numerator} из {item.denominator} раз "
            "в доказанной выборке этого типа."
        )
    else:
        description = (
            f"Условие подтвердилось в {item.numerator} из {item.denominator} доступных случаев."
        )
    return TacticalInsightCard(
        source=item,
        title=title,
        description=description,
        frequency_percent=f"{item.frequency * 100:.1f}%",
        evidence_rounds=len(item.evidence_references),
    )


def _title(item: TacticalInsight) -> str:
    if item.insight_type is TacticalInsightType.PATH_CLUSTER:
        return "Схожая расстановка в контрольных точках"
    if item.insight_type is TacticalInsightType.EXECUTE_PACKAGE:
        site = item.key.partition("site:")[2].partition("|")[0]
        return f"Выход с подтверждённой установкой на {site or 'неизвестном пленте'}"
    if item.insight_type is TacticalInsightType.UTILITY_OUTCOME:
        return (
            "Осколочная граната нанесла связанный урон"
            if item.key == "he"
            else "Зажигательная граната нанесла связанный урон"
        )
    if item.insight_type is TacticalInsightType.SPACING_PROFILE:
        checkpoint = item.key.partition(":")[2]
        moment = {"640": "ранней", "1280": "средней", "1920": "поздней"}.get(
            checkpoint, "контрольной"
        )
        return f"Игрок оставался далеко от тиммейтов в {moment} фазе раунда"
    if item.insight_type is TacticalInsightType.ENTRY_STRUCTURE:
        return "Команда выиграла первый подтверждённый контакт"
    if item.insight_type is TacticalInsightType.TRADE_STRUCTURE:
        return "Первая смерть команды была разменяна"
    if item.insight_type is TacticalInsightType.CLUTCH_BEHAVIOR:
        return "Команда выиграла доказанную ситуацию 1 против 2+"
    if item.insight_type is TacticalInsightType.SAVE_BEHAVIOR:
        return "Команда сохранила оружие в доказанном save-контексте"
    if item.insight_type is TacticalInsightType.HEATMAP_CELL:
        cell_x = _numeric_metric(item, "cell_x_median")
        cell_y = _numeric_metric(item, "cell_y_median")
        if cell_x is not None and cell_y is not None:
            return f"Часто наблюдаемый сектор карты ({round(cell_x)}, {round(cell_y)})"
        return "Часто наблюдаемый сектор карты"
    return item.label


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
    "build_tactical_v2_page",
]
