"""Product-first match hub assembled from persisted availability only."""

from __future__ import annotations

from pydantic import Field

from stratweb.spatial.query_models import MapOverview
from stratweb.web.view_models.match_readiness import MatchReadinessView
from stratweb.web.view_models.product import MatchOverviewView, ViewModel

MATCH_HUB_VIEW_VERSION = "1.0.0"


class MatchHubSectionView(ViewModel):
    title: str
    description: str
    meta: str
    status: str
    status_label: str
    href: str | None = None


class MatchHubRoundView(ViewModel):
    round_number: int = Field(ge=1)
    score: str
    winner: str
    complete: bool
    href: str | None = None


class MatchHubView(ViewModel):
    view_version: str = MATCH_HUB_VIEW_VERSION
    state: str
    status_label: str
    primary_action_label: str
    primary_action_href: str
    map_image_url: str | None = None
    sections: tuple[MatchHubSectionView, ...]
    rounds: tuple[MatchHubRoundView, ...]
    limitation_count: int = Field(ge=0)


def build_match_hub(
    overview: MatchOverviewView,
    readiness: MatchReadinessView,
    map_overview: MapOverview | None,
    *,
    economy_available: bool,
    features_available: bool,
) -> MatchHubView:
    """Build navigation and labels without recalculating match evidence."""

    match_id = overview.match.match_id
    health = {item.label.casefold(): _product_status(item.status) for item in overview.health}
    spatial_status = health.get("spatial", "unavailable")
    temporal_status = health.get("temporal", "unavailable")
    round_views = tuple(
        MatchHubRoundView(
            round_number=item.round_number,
            score=item.score,
            winner=item.winner,
            complete=item.complete,
            href=(
                item.map_href
                if spatial_status != "unavailable" and item.map_href is not None
                else item.timeline_href
                if temporal_status != "unavailable" and item.timeline_href is not None
                else None
            ),
        )
        for item in overview.rounds
    )

    first_round = round_views[0] if round_views else None
    if first_round is not None and first_round.href is not None:
        primary_label = "Смотреть матч"
        primary_href = first_round.href
    elif features_available:
        primary_label = "Открыть разбор раундов"
        primary_href = f"/ui/matches/{match_id}/features"
    else:
        primary_label = "Посмотреть составы"
        primary_href = f"/ui/matches/{match_id}#players"

    rounds_status = "available" if round_views else "unavailable"
    if round_views and any(not item.complete for item in round_views):
        rounds_status = "partial"

    sections = (
        MatchHubSectionView(
            title="Раунды",
            description="Счёт, победитель и переход к моментам матча.",
            meta=f"{len(round_views)} {_round_word(len(round_views))}",
            status=rounds_status,
            status_label=_status_label(rounds_status),
            href=f"/ui/matches/{match_id}#rounds" if round_views else None,
        ),
        MatchHubSectionView(
            title="Факты по игре",
            description="Первые контакты, гранаты, установки и другие события по раундам.",
            meta="Подтверждённые события" if features_available else "Расчёт не найден",
            status="available" if features_available else "unavailable",
            status_label=_status_label("available" if features_available else "unavailable"),
            href=f"/ui/matches/{match_id}/features" if features_available else None,
        ),
        MatchHubSectionView(
            title="Экономика",
            description="Тип закупки и состояние обеих команд в каждом раунде.",
            meta="По раундам" if economy_available else "Расчёт не найден",
            status="available" if economy_available else "unavailable",
            status_label=_status_label("available" if economy_available else "unavailable"),
            href=f"/ui/matches/{match_id}/economy" if economy_available else None,
        ),
    )

    return MatchHubView(
        state=readiness.state.value,
        status_label=readiness.status_label,
        primary_action_label=primary_label,
        primary_action_href=primary_href,
        map_image_url=map_overview.image_url if map_overview is not None else None,
        sections=sections,
        rounds=round_views,
        limitation_count=len(readiness.issues),
    )


def _status_label(value: str) -> str:
    return {
        "available": "Готово",
        "partial": "Есть ограничения",
        "unavailable": "Недоступно",
    }[value]


def _product_status(value: str | None) -> str:
    if value == "available":
        return "available"
    if value in {"partial", "unreliable"}:
        return "partial"
    return "unavailable"


def _round_word(value: int) -> str:
    if value % 10 == 1 and value % 100 != 11:
        return "раунд"
    if value % 10 in {2, 3, 4} and value % 100 not in {12, 13, 14}:
        return "раунда"
    return "раундов"


__all__ = [
    "MATCH_HUB_VIEW_VERSION",
    "MatchHubRoundView",
    "MatchHubSectionView",
    "MatchHubView",
    "build_match_hub",
]
