"""Small server-side localization contract for the offline UI."""

from __future__ import annotations

import re
from typing import Final

DEFAULT_LOCALE: Final = "ru"
SUPPORTED_LOCALES: Final = ("ru",)
UI_LOCALE_SCHEMA_VERSION: Final = "1.0.0"

_RU: Final[dict[str, str]] = {
    "nav.matches": "Матчи",
    "nav.opponents": "Соперники",
    "nav.overview": "Обзор",
    "nav.rounds": "Раунды",
    "nav.map": "Карта",
    "nav.timeline": "Таймлайн",
    "nav.economy": "Экономика",
    "nav.facts": "Факты",
    "nav.players": "Игроки",
    "nav.diagnostics": "Диагностика",
    "app.offline_evidence": "Офлайн-анализ",
    "action.open": "Открыть",
    "action.apply": "Применить",
    "action.reset": "Сбросить",
    "action.details": "Подробнее",
    "action.copy": "Копировать",
    "status.available": "Готово",
    "status.partial": "Частично",
    "status.unavailable": "Недоступно",
    "status.unresolved": "Не определено",
    "status.good": "Готово",
    "status.warn": "Внимание",
    "status.bad": "Ошибка",
    "team.one": "Команда 1",
    "team.two": "Команда 2",
    "team.unknown": "Команда не определена",
    "value.unknown": "Неизвестно",
    "value.unavailable": "Недоступно",
    "tactical.path_cluster": "Формации и маршруты",
    "tactical.execute_package": "Выходы на плент",
    "tactical.utility_outcome": "Результат гранат",
    "tactical.spacing_profile": "Дистанции игроков",
    "tactical.entry_structure": "Первый контакт",
    "tactical.trade_structure": "Размены",
    "tactical.rotation_transition": "Переходы после контакта",
    "tactical.clutch_behavior": "Клатч-ситуации",
    "tactical.save_behavior": "Сохранение оружия",
    "tactical.heatmap_cell": "Присутствие на карте",
}

_WARNING_LABELS: Final[dict[str, str]] = {
    "match is ready": "Матч готов",
    "waiting for the local import worker": "Ожидание локальной обработки",
    "assigning version-pinned map zones": "Определение зон карты",
    "materializing deterministic per-round facts": "Расчёт фактов по раундам",
    "imported dataset": "Матч импортирован",
    "map_revision_unproven": "Версия карты не подтверждена",
    "zone_assignments_use_unproven_map_revision": (
        "Зоны рассчитаны по неподтверждённой версии карты"
    ),
    "source_rotate_flag_baked_into_asset": "Поворот уже учтён в изображении карты",
    "no_eligible_findings": "Нет выводов, прошедших критерии готовности",
    "corpus_below_minimum": "Недостаточно матчей в выборке",
    "confirmed opponent corpus is below the configured minimum.": (
        "Подтверждённый корпус соперника меньше заданного минимума."
    ),
    "no recommendation is available for real-corpus acceptance.": (
        "Для принятия отчёта по реальному корпусу пока нет рекомендаций."
    ),
    "readiness gate has no eligible findings": (
        "Ни одно наблюдение не прошло проверку готовности."
    ),
    "no counter strategy recommendations published": (
        "Контрстратегические рекомендации пока не опубликованы."
    ),
    "tactical_v2_observations_do_not_prove_intent_or_causality": (
        "Наблюдения не доказывают замысел команды или причинно-следственную связь"
    ),
    "tick_windows_are_versioned_policies_not_inferred_seconds": (
        "Временные окна заданы в тиках и закреплены версией правил"
    ),
    "complete_zone_formation_unavailable": "Полная формация по зонам доступна не во всех раундах",
    "plant_site_or_utility_provenance_unavailable": (
        "Не для каждого выхода подтверждены плент и происхождение гранат"
    ),
    "utility_outcome_requires_unique_association_and_never_proves_causality": (
        "Результат гранаты показывается только при однозначной связи и не доказывает причину"
    ),
    "insufficient_same_tick_player_positions": (
        "Не для каждой точки времени доступны позиции нескольких игроков"
    ),
    "opening_order_ambiguous_or_unavailable": "Порядок первого контакта иногда не доказан",
    "opening_death_or_trade_data_unavailable": "Данные первой смерти или размена неполны",
    "post_contact_zone_transitions_unavailable": "Переходы между зонами после контакта недоступны",
    "complete_roster_or_round_outcome_unavailable": "Не подтверждён полный состав или итог раунда",
    "save_exit_fact_unavailable": "Факт сохранения оружия пока недоступен",
    "authoritative_alive_position_unavailable": (
        "Часть подтверждённых позиций живых игроков недоступна"
    ),
    "absence_of_a_trade_event_is_not_proof_that_no_trade_was_attempted": (
        "Отсутствие размена в данных не доказывает, что команда не пыталась разменять игрока"
    ),
    "alive_state_is_evaluated_after_the_complete_same_tick_kill_group": (
        "Число живых игроков определяется после всей группы событий одного тика"
    ),
    "checkpoint_sampling_does_not_prove_spacing_between_checkpoints": (
        "Позиции между контрольными снимками не додумываются"
    ),
    "checkpoints_with_fewer_than_two_known_player_zones_are_excluded": (
        "Снимки с менее чем двумя подтверждёнными зонами игроков исключены"
    ),
    "clutch_attempt_intent_is_not_inferred_from_the_result": (
        "Результат раунда не используется для догадки о замысле игрока"
    ),
    "damage_is_a_same_owner_weapon_time_association_not_proven_causality": (
        "Урон связан по игроку, оружию и времени, но причинная связь не доказана"
    ),
    "damage_matching_multiple_effect_windows_is_excluded_as_ambiguous": (
        "Урон, подходящий сразу к нескольким гранатам, исключён как неоднозначный"
    ),
    "distance_is_source2_world_units_not_a_tactical_quality_score": (
        "Дистанция измерена в координатах игры и не является оценкой качества"
    ),
    "execute_population_is_t_side_rounds_with_proven_plant_site": (
        "В выборку входят только T-раунды с подтверждённым местом установки бомбы"
    ),
    "flash_blindness_and_smoke_line_of_sight_effectiveness_are_unavailable": (
        "Эффективность флешек и перекрытие обзора дымом пока не рассчитываются"
    ),
    "frequency_is_alive_spatial_sample_share_not_time_seconds_or_round_probability": (
        "Частота означает долю снимков живых игроков, а не секунды или вероятность раунда"
    ),
    "identical_checkpoint_formations_are_clustered_without_geometry_guessing": (
        "Объединяются только одинаковые подтверждённые расстановки без додумывания пути"
    ),
    "opening_result_does_not_identify_called_entry_role": (
        "Первый контакт не используется для назначения игроку роли энтри"
    ),
    "post_contact_movement_is_observed_transition_not_proven_rotation_intent": (
        "Показано перемещение после контакта, а не доказанный замысел ротации"
    ),
    "same_tick_multiple_opening_kills_are_excluded_as_ambiguous": (
        "Несколько первых убийств в одном тике исключены как неоднозначные"
    ),
    "sampling_density_can_differ_between_versioned_spatial_runs": (
        "Частота сохранения позиционных снимков может отличаться между версиями расчёта"
    ),
    "trade_uses_versioned_stage_5_trade_window": (
        "Размен определяется закреплённым временным окном Stage 5"
    ),
    "transition_frequency_denominator_is_all_observed_zone_edges": (
        "Знаменатель — все подтверждённые переходы между зонами после контакта"
    ),
    "unplanted_executes_and_tactical_intent_are_not_inferred": (
        "Выходы без установки бомбы и замысел команды не додумываются"
    ),
    "utility_bundle_uses_effect_start_inside_versioned_preplant_tick_window": (
        "Гранаты учитываются по закреплённому окну тиков перед установкой бомбы"
    ),
}

_MAP_LABELS: Final[dict[str, str]] = {
    "de_ancient": "Ancient",
    "de_anubis": "Anubis",
    "de_cache": "Cache",
    "de_dust2": "Dust II",
    "de_inferno": "Inferno",
    "de_mirage": "Mirage",
    "de_nuke": "Nuke",
    "de_overpass": "Overpass",
    "de_train": "Train",
    "de_vertigo": "Vertigo",
}

_BUY_TYPE_LABELS: Final[dict[str, str]] = {
    "pistol": "Пистолетный",
    "eco": "Эко",
    "force": "Форс",
    "semi": "Неполный",
    "full": "Полный",
    "unknown": "Неизвестно",
    "unavailable": "Недоступно",
}


def translate(key: str, **values: object) -> str:
    """Translate a stable message key; missing keys stay visible to developers."""

    template = _RU.get(key, key)
    return template.format(**values) if values else template


def team_display_name(value: str | None) -> str:
    """Hide canonical placeholder identities without inventing a real team name."""

    if value is None or not value.strip():
        return translate("team.unknown")
    stripped = value.strip()
    normalized = stripped.casefold().replace(" ", "")
    if normalized in {"teamalpha", "team_a", "teama"}:
        return translate("team.one")
    if normalized in {"teambravo", "team_b", "teamb"}:
        return translate("team.two")
    technical_labels = (
        ("TeamAlpha", translate("team.one")),
        ("TeamBravo", translate("team.two")),
    )
    for technical, label in technical_labels:
        if stripped.casefold().startswith(technical.casefold()):
            return label + stripped[len(technical) :]
    return stripped


def status_label(value: object) -> str:
    normalized = str(value).strip().casefold()
    return translate(f"status.{normalized}")


def map_display_name(value: object) -> str:
    raw = str(value).strip()
    return _MAP_LABELS.get(raw.casefold(), raw)


def buy_type_label(value: object) -> str:
    raw = str(value).strip()
    return _BUY_TYPE_LABELS.get(raw.casefold(), raw)


def warning_label(value: object) -> str:
    raw = str(value).strip()
    normalized = raw.casefold()
    if normalized in _WARNING_LABELS:
        return _WARNING_LABELS[normalized]
    if match := re.fullmatch(r"(\d+) player summaries", normalized):
        return f"Игроков в статистике: {match.group(1)}"
    if match := re.fullmatch(r"(\d+) authoritative samples", normalized):
        return f"Подтверждённых снимков: {match.group(1)}"
    if match := re.fullmatch(r"small_corpus:(\d+)/(\d+)_matches", normalized):
        return f"Малая выборка: {match.group(1)} из рекомендуемых {match.group(2)} матчей"
    if normalized.startswith("temporal "):
        return f"Версия состояний раунда: {raw.removeprefix('Temporal ')}"
    return raw.replace("_", " ")


__all__ = [
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "UI_LOCALE_SCHEMA_VERSION",
    "buy_type_label",
    "map_display_name",
    "status_label",
    "team_display_name",
    "translate",
    "warning_label",
]
