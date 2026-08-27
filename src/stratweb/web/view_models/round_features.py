"""Typed, evidence-preserving presentation models for Stage 8.4.1."""

from __future__ import annotations

import json
from collections import Counter
from uuid import UUID

from pydantic import Field

from stratweb.features.models import (
    BombRoutePayload,
    BombsitePayload,
    EarlyZonePresencePayload,
    FirstContactPayload,
    FirstUtilityPayload,
    LostAdvantagePayload,
    OpeningDuelPayload,
    PlantTimingPayload,
    PostPlantRosterPayload,
    RetakeAttemptPayload,
    RoundFeature,
    RoundFeatureRunSummary,
    RoundFeatureType,
    SaveExitPayload,
    UntradedDeathPayload,
    ZoneDistributionPayload,
)
from stratweb.web.view_models.product import ViewModel

_FEATURE_LABELS: dict[RoundFeatureType, str] = {
    RoundFeatureType.STARTING_ZONE_DISTRIBUTION: "Стартовая расстановка",
    RoundFeatureType.CHECKPOINT_ZONE_DISTRIBUTION: "Расстановка в контрольный момент",
    RoundFeatureType.FIRST_CONTACT: "Первый контакт",
    RoundFeatureType.OPENING_DUEL: "Первая дуэль",
    RoundFeatureType.FIRST_UTILITY: "Первая граната",
    RoundFeatureType.EARLY_ZONE_PRESENCE: "Раннее присутствие в зоне",
    RoundFeatureType.BOMB_ROUTE: "Маршрут бомбы",
    RoundFeatureType.BOMBSITE: "Точка установки",
    RoundFeatureType.PLANT_TIMING: "Время установки",
    RoundFeatureType.POST_PLANT_ROSTER: "Состав после установки",
    RoundFeatureType.FIRST_CT_ROTATION: "Первая ротация CT",
    RoundFeatureType.LOST_MAN_ADVANTAGE: "Потерянное численное преимущество",
    RoundFeatureType.UNTRADED_DEATH: "Смерть без размена",
    RoundFeatureType.RETAKE_ATTEMPT: "Попытка ретейка",
    RoundFeatureType.SAVE_EXIT: "Сейв / выход",
}


class FeatureCapabilityView(ViewModel):
    feature_type: str
    label: str
    population: int = Field(ge=0)
    available: int = Field(ge=0)
    partial: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    not_applicable: int = Field(ge=0)
    href: str


class RoundFeatureRowView(ViewModel):
    feature_id: UUID
    round_number: int = Field(ge=1)
    team_name: str
    side: str
    feature_type: str
    feature_label: str
    availability: str
    buy_type: str
    tick_label: str
    zone_label: str
    observation: str
    evidence_event_ids: tuple[str, ...]
    evidence_snapshot_ids: tuple[str, ...]
    evidence_economy_snapshot_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    warnings: tuple[str, ...]
    payload_json: str | None = None
    playback_href: str
    playback_label: str
    timeline_href: str


class RoundFeatureRoundView(ViewModel):
    round_number: int = Field(ge=1)
    features: tuple[RoundFeatureRowView, ...]


class RoundStoryEventView(ViewModel):
    feature_label: str
    observation: str
    team_name: str
    side: str
    availability: str
    tick_label: str
    zone_label: str
    playback_href: str


class RoundStoryBeatView(ViewModel):
    title: str
    observation: str
    status: str
    team_name: str | None = None
    side: str | None = None
    tick_label: str | None = None
    zone_label: str | None = None
    playback_href: str | None = None


class RoundStoryView(ViewModel):
    round_number: int = Field(ge=1)
    events: tuple[RoundStoryEventView, ...]
    turning_point: RoundStoryBeatView
    problem: RoundStoryBeatView
    primary_href: str
    timeline_href: str


class RoundFeaturePageView(ViewModel):
    match_id: UUID
    feature_run_id: UUID
    feature_schema_version: str
    feature_rule_version: str
    feature_fingerprint: str
    eligible_rounds: int = Field(ge=0)
    excluded_rounds: int = Field(ge=0)
    total_features: int = Field(ge=0)
    available: int = Field(ge=0)
    partial: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    not_applicable: int = Field(ge=0)
    visible_features: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    previous_href: str | None = None
    next_href: str | None = None
    capabilities: tuple[FeatureCapabilityView, ...]
    stories: tuple[RoundStoryView, ...]
    rounds: tuple[RoundFeatureRoundView, ...]
    warnings: tuple[str, ...]


def feature_type_options() -> tuple[tuple[str, str], ...]:
    return tuple((item.value, _FEATURE_LABELS[item]) for item in RoundFeatureType)


def build_round_feature_page(
    summary: RoundFeatureRunSummary,
    features: tuple[RoundFeature, ...],
    *,
    team_names: dict[UUID, str],
    player_names: dict[UUID, str],
    page: int,
    page_size: int,
    previous_href: str | None,
    next_href: str | None,
    story_features: tuple[RoundFeature, ...] | None = None,
) -> RoundFeaturePageView:
    rows = tuple(
        _feature_row(item, team_names=team_names, player_names=player_names) for item in features
    )
    round_numbers = sorted({item.round_number for item in rows})
    capabilities = tuple(
        FeatureCapabilityView(
            feature_type=feature_type.value,
            label=_FEATURE_LABELS[feature_type],
            population=value.population,
            available=value.available,
            partial=value.partial,
            unavailable=value.unavailable,
            not_applicable=value.not_applicable,
            href=(
                f"/ui/matches/{summary.match_id}/features?"
                f"run_id={summary.feature_run_id}&type={feature_type.value}"
            ),
        )
        for feature_type, value in summary.capabilities.items()
    )
    story_source = features if story_features is None else story_features
    story_rows = tuple(
        _feature_row(item, team_names=team_names, player_names=player_names)
        for item in story_source
    )
    return RoundFeaturePageView(
        match_id=summary.match_id,
        feature_run_id=summary.feature_run_id,
        feature_schema_version=summary.feature_schema_version,
        feature_rule_version=summary.feature_rule_version,
        feature_fingerprint=summary.feature_fingerprint,
        eligible_rounds=summary.summary.eligible_rounds,
        excluded_rounds=summary.summary.excluded_rounds,
        total_features=summary.summary.features,
        available=summary.summary.available,
        partial=summary.summary.partial,
        unavailable=summary.summary.unavailable,
        not_applicable=summary.summary.not_applicable,
        visible_features=len(rows),
        page=page,
        page_size=page_size,
        previous_href=previous_href,
        next_href=next_href,
        capabilities=capabilities,
        stories=_build_round_stories(story_source, story_rows, summary.match_id),
        rounds=tuple(
            RoundFeatureRoundView(
                round_number=round_number,
                features=tuple(item for item in rows if item.round_number == round_number),
            )
            for round_number in round_numbers
        ),
        warnings=summary.warnings,
    )


_STORY_EVENT_GROUPS = (
    (RoundFeatureType.OPENING_DUEL, RoundFeatureType.FIRST_CONTACT),
    (RoundFeatureType.FIRST_UTILITY,),
    (RoundFeatureType.BOMBSITE,),
    (RoundFeatureType.PLANT_TIMING,),
    (RoundFeatureType.RETAKE_ATTEMPT, RoundFeatureType.SAVE_EXIT),
)
_STORY_EVENT_LIMIT = 5
_USABLE_AVAILABILITY = {"available", "partial"}


def _build_round_stories(
    features: tuple[RoundFeature, ...],
    rows: tuple[RoundFeatureRowView, ...],
    match_id: UUID,
) -> tuple[RoundStoryView, ...]:
    pairs = tuple(zip(features, rows, strict=True))
    stories: list[RoundStoryView] = []
    for round_number in sorted({item.round_number for item in features}):
        round_pairs = tuple(pair for pair in pairs if pair[0].round_number == round_number)
        selected_events: list[tuple[RoundFeature, RoundFeatureRowView]] = []
        for feature_group in _STORY_EVENT_GROUPS:
            selected = next(
                (
                    candidate
                    for feature_type in feature_group
                    if (candidate := _best_story_fact(round_pairs, feature_type)) is not None
                ),
                None,
            )
            if selected is not None:
                selected_events.append(selected)
        selected_events.sort(
            key=lambda pair: (
                pair[0].tick_start if pair[0].tick_start is not None else 2**63 - 1,
                str(pair[0].feature_id),
            )
        )
        events: list[RoundStoryEventView] = []
        for feature, row in selected_events[:_STORY_EVENT_LIMIT]:
            events.append(
                RoundStoryEventView(
                    feature_label=row.feature_label,
                    observation=_story_observation(feature, row.observation),
                    team_name=row.team_name,
                    side=row.side,
                    availability=row.availability,
                    tick_label=row.tick_label,
                    zone_label=row.zone_label,
                    playback_href=row.playback_href,
                )
            )
        stories.append(
            RoundStoryView(
                round_number=round_number,
                events=tuple(events),
                turning_point=_story_beat(
                    round_pairs,
                    RoundFeatureType.LOST_MAN_ADVANTAGE,
                    available_title="Потеря численного преимущества",
                    unavailable_title="Перелом не определён",
                    unavailable_observation=(
                        "В сохранённых фактах нет доказательства момента, "
                        "который изменил ход раунда."
                    ),
                ),
                problem=_story_beat(
                    round_pairs,
                    RoundFeatureType.UNTRADED_DEATH,
                    available_title="Смерть без размена",
                    unavailable_title="Подтверждённая проблема не определена",
                    unavailable_observation=(
                        "Данных недостаточно, чтобы назвать конкретную ошибку команды."
                    ),
                ),
                primary_href=f"/ui/spatial/{match_id}/rounds/{round_number}",
                timeline_href=f"/ui/temporal/{match_id}/rounds/{round_number}",
            )
        )
    return tuple(stories)


def _best_story_fact(
    pairs: tuple[tuple[RoundFeature, RoundFeatureRowView], ...],
    feature_type: RoundFeatureType,
) -> tuple[RoundFeature, RoundFeatureRowView] | None:
    candidates = [
        pair
        for pair in pairs
        if pair[0].feature_type is feature_type and pair[1].availability in _USABLE_AVAILABILITY
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda pair: (
            0 if pair[1].availability == "available" else 1,
            pair[0].tick_start if pair[0].tick_start is not None else 2**63 - 1,
            str(pair[0].feature_id),
        ),
    )


def _story_beat(
    pairs: tuple[tuple[RoundFeature, RoundFeatureRowView], ...],
    feature_type: RoundFeatureType,
    *,
    available_title: str,
    unavailable_title: str,
    unavailable_observation: str,
) -> RoundStoryBeatView:
    selected = _best_story_fact(pairs, feature_type)
    if selected is None:
        return RoundStoryBeatView(
            title=unavailable_title,
            observation=unavailable_observation,
            status="unavailable",
        )
    _, row = selected
    return RoundStoryBeatView(
        title=available_title,
        observation=row.observation,
        status=row.availability,
        team_name=row.team_name,
        side=row.side,
        tick_label=row.tick_label,
        zone_label=row.zone_label,
        playback_href=row.playback_href,
    )


def _story_observation(feature: RoundFeature, fallback: str) -> str:
    payload = feature.payload
    if isinstance(payload, FirstUtilityPayload):
        return "; ".join(part.split(" (", 1)[0] for part in fallback.split("; "))
    if isinstance(payload, PlantTimingPayload):
        if payload.seconds_from_freeze_end is None:
            return "Установка подтверждена, но точное время недоступно."
        seconds = round(payload.seconds_from_freeze_end, 1)
        return f"Бомбу установили через {seconds:g} с после начала активной фазы."
    return fallback


def _feature_row(
    feature: RoundFeature,
    *,
    team_names: dict[UUID, str],
    player_names: dict[UUID, str],
) -> RoundFeatureRowView:
    payload_json = (
        json.dumps(
            feature.payload.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        if feature.payload is not None
        else None
    )
    return RoundFeatureRowView(
        feature_id=feature.feature_id,
        round_number=feature.round_number,
        team_name=team_names.get(feature.team_id, "Команда не определена"),
        side=feature.side.value,
        feature_type=feature.feature_type.value,
        feature_label=_FEATURE_LABELS[feature.feature_type],
        availability=feature.availability.value,
        buy_type=feature.buy_type.value if feature.buy_type is not None else "unavailable",
        tick_label=_tick_label(feature),
        zone_label=feature.zone_name or "Зона не определена",
        observation=_observation(feature, player_names),
        evidence_event_ids=tuple(str(item) for item in feature.evidence_event_ids),
        evidence_snapshot_ids=tuple(str(item) for item in feature.evidence_snapshot_ids),
        evidence_economy_snapshot_ids=tuple(
            str(item) for item in feature.evidence_economy_snapshot_ids
        ),
        limitations=feature.limitations,
        warnings=feature.warnings,
        payload_json=payload_json,
        playback_href=(
            f"/ui/spatial/{feature.match_id}/rounds/{feature.round_number}"
            + (f"?tick={feature.tick_start}&mode=smooth" if feature.tick_start is not None else "")
        ),
        playback_label="Карта на этом тике" if feature.tick_start is not None else "Карта раунда",
        timeline_href=f"/ui/temporal/{feature.match_id}/rounds/{feature.round_number}",
    )


def _tick_label(feature: RoundFeature) -> str:
    if feature.tick_start is None:
        return "Недоступно"
    if feature.tick_end is None or feature.tick_end == feature.tick_start:
        return str(feature.tick_start)
    return f"{feature.tick_start}–{feature.tick_end}"


def _observation(feature: RoundFeature, names: dict[UUID, str]) -> str:
    payload = feature.payload
    if payload is None:
        return _human_code(feature.limitations[0]) if feature.limitations else "Недоступно"
    if isinstance(payload, ZoneDistributionPayload):
        zones = Counter(item.zone_name or "зона не определена" for item in payload.players)
        distribution = ", ".join(f"{zone} ×{count}" for zone, count in zones.items())
        return (
            f"Игроков: {len(payload.players)} · "
            f"контрольная точка {payload.checkpoint_label}: {distribution}"
        )
    if isinstance(payload, FirstContactPayload):
        contacts = "; ".join(
            f"{_player(item.actor_player_id, names)} → {_player(item.victim_player_id, names)}"
            for item in payload.candidates
        )
        return f"{_human_code(payload.role)}: {contacts}"
    if isinstance(payload, OpeningDuelPayload):
        return (
            f"{_human_code(payload.role)}: {_player(payload.killer_player_id, names)} "
            f"против {_player(payload.victim_player_id, names)}"
        )
    if isinstance(payload, FirstUtilityPayload):
        return "; ".join(
            f"{_player(item.player_id, names)} — {_human_code(item.grenade_type)} "
            f"({item.lifecycle_event})"
            for item in payload.candidates
        )
    if isinstance(payload, EarlyZonePresencePayload):
        players = ", ".join(_player(item, names) for item in payload.player_ids)
        return f"Впервые замечены здесь на тике {payload.first_observed_tick}: {players}"
    if isinstance(payload, BombRoutePayload):
        return " → ".join(item.zone_name for item in payload.stops)
    if isinstance(payload, BombsitePayload):
        return f"Установка подтверждена · точка {payload.site or 'не определена'}"
    if isinstance(payload, PlantTimingPayload):
        if payload.relative_tick is None:
            return "Установка подтверждена, время от freeze time недоступно"
        seconds = (
            f" ({payload.seconds_from_freeze_end:.2f}s)"
            if payload.seconds_from_freeze_end is not None
            else ""
        )
        return f"Установка через {payload.relative_tick} тиков после freeze time{seconds}"
    if isinstance(payload, PostPlantRosterPayload):
        return (
            f"Живы: {len(payload.alive_player_ids)}, погибли: {len(payload.dead_player_ids)}, "
            f"неизвестно: {len(payload.unknown_player_ids)}"
        )
    if isinstance(payload, LostAdvantagePayload):
        return (
            f"T {payload.t_alive_before}→{payload.t_alive_after}; "
            f"CT {payload.ct_alive_before}→{payload.ct_alive_after}; "
            f"{_human_code(payload.event_classification)}"
        )
    if isinstance(payload, UntradedDeathPayload):
        return (
            f"{_player(payload.victim_player_id, names)} погиб от "
            f"{_player(payload.attacker_player_id, names)}; размена не было в течение "
            f"{payload.trade_window_ticks} тиков"
        )
    if isinstance(payload, RetakeAttemptPayload):
        players = ", ".join(_player(item, names) for item in payload.entering_player_ids)
        return f"Подтверждён вход на точку: {players}"
    if isinstance(payload, SaveExitPayload):
        players = ", ".join(_player(item, names) for item in payload.surviving_player_ids)
        return f"Сохранили оружие: {players}" if payload.saved else "Сейв не подтверждён"
    return _human_code(feature.feature_type.value)


def _player(player_id: UUID, names: dict[UUID, str]) -> str:
    return names.get(player_id, str(player_id).split("-")[0])


def _human_code(value: str) -> str:
    labels = {
        "initiator": "Инициатор",
        "victim": "Погибший",
        "candidate": "Возможный участник",
        "resolved": "Определено",
        "unknown": "Неизвестно",
        "unavailable": "Недоступно",
        "smoke": "Смок",
        "flashbang": "Флеш",
        "he_grenade": "Осколочная граната",
        "molotov": "Молотов",
        "incendiary": "Зажигательная граната",
        "decoy": "Ложная граната",
    }
    return labels.get(value, value.replace("_", " ").strip().capitalize())


__all__ = [
    "FeatureCapabilityView",
    "RoundFeaturePageView",
    "RoundFeatureRoundView",
    "RoundFeatureRowView",
    "RoundStoryBeatView",
    "RoundStoryEventView",
    "RoundStoryView",
    "build_round_feature_page",
    "feature_type_options",
]
