"""Human-facing match readiness assembled from existing deterministic results."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from stratweb.maps.models import MapSelectionStatus
from stratweb.spatial.query_models import MapOverview
from stratweb.web.view_models.product import MatchOverviewView, ViewModel
from stratweb.zones.assignment_models import ZoneAssignmentRunSummary

MATCH_READINESS_VIEW_VERSION = "1.0.0"


class MatchReadinessState(StrEnum):
    READY = "ready"
    LIMITED = "limited"
    BLOCKED = "blocked"


class ReadinessCapabilityView(ViewModel):
    title: str
    description: str
    status: str
    status_label: str


class ReadinessIssueView(ViewModel):
    title: str
    explanation: str
    impact: str


class MatchReadinessView(ViewModel):
    view_version: str = MATCH_READINESS_VIEW_VERSION
    state: MatchReadinessState
    status_label: str
    title: str
    lead: str
    primary_action_label: str
    primary_action_href: str
    map_image_url: str | None = None
    capabilities: tuple[ReadinessCapabilityView, ...]
    issues: tuple[ReadinessIssueView, ...]
    available_capability_count: int = Field(ge=0)


def build_match_readiness(
    overview: MatchOverviewView,
    map_overview: MapOverview | None,
    zone_summary: ZoneAssignmentRunSummary | None,
) -> MatchReadinessView:
    """Translate technical availability into a small, truthful product contract."""

    match_id = overview.match.match_id
    health = {item.label.casefold(): item.status for item in overview.health}

    canonical_status = _product_status(health.get("canonical"))
    analytics_status = _product_status(health.get("analytics"))
    temporal_status = _product_status(health.get("temporal"))
    spatial_status = _product_status(health.get("spatial"))

    capabilities = (
        ReadinessCapabilityView(
            title="2D-повтор",
            description="Позиции игроков и события раунда на карте.",
            status=spatial_status,
            status_label=_status_label(spatial_status),
        ),
        ReadinessCapabilityView(
            title="Хронология раундов",
            description="Ключевые моменты и состояние команд по ходу раунда.",
            status=temporal_status,
            status_label=_status_label(temporal_status),
        ),
        ReadinessCapabilityView(
            title="Разбор матча",
            description="Счёт, составы и подтверждённые игровые события.",
            status=canonical_status,
            status_label=_status_label(canonical_status),
        ),
    )

    issues: list[ReadinessIssueView] = []
    if canonical_status != "available":
        issues.append(
            ReadinessIssueView(
                title="Демка прочитана не полностью",
                explanation="В исходных событиях матча есть ошибки или пропуски.",
                impact="StratWeb показывает только подтверждённые данные и не заполняет пробелы.",
            )
        )
    if analytics_status == "unavailable":
        issues.append(
            ReadinessIssueView(
                title="Статистика матча пока недоступна",
                explanation="Демка сохранена, но расчёт игровых показателей не найден.",
                impact="Таблица игроков и часть итогов могут быть пустыми.",
            )
        )
    if temporal_status == "unavailable":
        issues.append(
            ReadinessIssueView(
                title="Хронология раундов пока недоступна",
                explanation="Для этого матча не найден совместимый расчёт состояний раунда.",
                impact="Нельзя открыть точный момент до или после события.",
            )
        )
    if spatial_status == "partial":
        issues.append(
            ReadinessIssueView(
                title="Не все позиции попали в 2D-повтор",
                explanation="У части моментов в демке нет достаточных координат.",
                impact="Доступные позиции и события показаны без догадок.",
            )
        )
    elif spatial_status == "unavailable":
        issues.append(
            ReadinessIssueView(
                title="2D-повтор пока недоступен",
                explanation="Для этого матча не найден совместимый расчёт позиций.",
                impact="Остальные части разбора остаются доступными.",
            )
        )

    if spatial_status != "unavailable" and map_overview is not None:
        if not map_overview.image_url:
            issues.append(
                ReadinessIssueView(
                    title="Изображение карты недоступно",
                    explanation="Позиционные данные есть, но фон этой карты не установлен.",
                    impact="Хронология и события доступны; 2D-просмотр будет ограничен.",
                )
            )
        if map_overview.revision_selection_status is not MapSelectionStatus.PROVEN:
            issues.append(
                ReadinessIssueView(
                    title="Версия карты не подтверждена демкой",
                    explanation="StratWeb использует подходящую установленную схему карты.",
                    impact=(
                        "Названия некоторых зон могут быть неточными; позиции и события сохранены."
                    ),
                )
            )
        if zone_summary is None:
            issues.append(
                ReadinessIssueView(
                    title="Названия зон пока не рассчитаны",
                    explanation=(
                        "Координаты игроков сохранены, но им не назначены названия участков карты."
                    ),
                    impact="2D-повтор работает, а текстовые маршруты могут быть неполными.",
                )
            )
        elif zone_summary.summary.unknown or zone_summary.summary.unavailable:
            issues.append(
                ReadinessIssueView(
                    title="Не все позиции получили название зоны",
                    explanation="Часть координат лежит вне подтверждённых зон или недоступна.",
                    impact="StratWeb оставляет такие места без названия и ничего не придумывает.",
                )
            )

    available_count = sum(item.status != "unavailable" for item in capabilities)
    if available_count == 0:
        state = MatchReadinessState.BLOCKED
        status_label = "Нужна обработка"
        title = "Матч сохранён"
        lead = "Демка находится в библиотеке, но разделы разбора ещё не готовы."
    elif issues:
        state = MatchReadinessState.LIMITED
        status_label = "Можно смотреть"
        title = "Разбор готов"
        lead = "Основные данные матча доступны. Ниже честно отмечено, что может быть неполным."
    else:
        state = MatchReadinessState.READY
        status_label = "Всё готово"
        title = "Разбор готов"
        lead = "Матч обработан: можно смотреть раунды, хронологию и позиции игроков."

    return MatchReadinessView(
        state=state,
        status_label=status_label,
        title=title,
        lead=lead,
        primary_action_label=(
            "Открыть карточку матча" if state is MatchReadinessState.BLOCKED else "Открыть разбор"
        ),
        primary_action_href=f"/ui/matches/{match_id}",
        map_image_url=map_overview.image_url if map_overview is not None else None,
        capabilities=capabilities,
        issues=tuple(issues),
        available_capability_count=available_count,
    )


def _product_status(value: str | None) -> str:
    if value == "available":
        return "available"
    if value in {"partial", "unreliable"}:
        return "partial"
    return "unavailable"


def _status_label(value: str) -> str:
    return {
        "available": "Готово",
        "partial": "Есть ограничения",
        "unavailable": "Недоступно",
    }[value]


__all__ = [
    "MATCH_READINESS_VIEW_VERSION",
    "MatchReadinessState",
    "MatchReadinessView",
    "ReadinessCapabilityView",
    "ReadinessIssueView",
    "build_match_readiness",
]
