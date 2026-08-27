"""Deterministic Russian presentation helpers for human-readable exports."""

from __future__ import annotations

import re

from stratweb.counter_strategy.validation_models import ValidationCheck
from stratweb.findings.models import AnalysisFinding
from stratweb.patterns.models import (
    BinaryPatternValue,
    CategoricalPatternValue,
    PlayerPatternValue,
)

_PATTERN_LABELS = {
    "site_preference": "Предпочтение плента",
    "early_zone_occupation": "Ранний контроль зоны",
    "recurring_opening_player": "Регулярный участник первой дуэли",
    "recurring_opening_death": "Повторяющаяся первая смерть",
    "first_contact_zone": "Зона первого контакта",
    "first_utility": "Первая граната",
    "bomb_routing": "Маршрут бомбы",
    "ct_starting_position": "Стартовая позиция CT",
    "early_rotation": "Ранняя ротация",
    "opening_kill_conversion": "Реализация первого убийства",
    "recovery_after_opening_death": "Восстановление после первой смерти",
    "lost_man_advantage": "Потерянное численное преимущество",
    "untraded_death": "Смерть без размена",
    "plant_timing": "Время установки",
    "retake_frequency": "Частота ретейков",
    "save_frequency": "Частота сейвов",
}

_CHECK_LABELS = {
    "source_run_integrity": "Целостность исходного расчёта",
    "analysis_input_counts": "Количество входных данных анализа",
    "readiness_reproducibility": "Воспроизводимость проверки готовности",
    "complete_finding_classification": "Полнота классификации наблюдений",
    "corpus_size": "Размер корпуса",
    "both_sides_covered": "Покрытие обеих сторон",
    "buy_context_coverage": "Покрытие типов закупа",
    "published_recommendations": "Опубликованные рекомендации",
    "ready_gate_enforced": "Проверка порога готовности",
    "statistics_preserved": "Сохранность статистики",
    "evidence_preserved": "Сохранность доказательств",
    "evidence_within_corpus": "Доказательства входят в корпус",
    "duplicate_recommendations": "Отсутствие повторных рекомендаций",
    "causality_guard": "Защита от причинных утверждений",
}

_STATUS_LABELS = {
    "passed": "пройдено",
    "ready": "готово",
    "limited": "с ограничениями",
    "blocked": "заблокировано",
    "failed": "ошибка",
    "warning": "предупреждение",
}

_LIMITATION_LABELS = {
    "advantage_includes_all_first_death_effects_by_analytics_rule": (
        "Преимущество учитывает все последствия первой смерти по закреплённому правилу."
    ),
    "association_is_not_a_causal_claim": "Связь не доказывает причинно-следственную зависимость.",
    "bomb_route_has_zone_gaps": "В маршруте бомбы есть участки с неизвестной зоной.",
    "contact_zone_partial": "Зона первого контакта определена частично.",
    "exact_five_player_setup_requires_complete_zone_coverage": (
        "Точная расстановка пяти игроков требует полного покрытия зонами."
    ),
    "frequency_is_conditional_on_observable_early_zone_rounds": (
        "Частота рассчитана только по раундам, где ранняя зона наблюдаема."
    ),
    "no_observed_advantage_loss": "Потеря преимущества в доступной выборке не наблюдалась.",
    "no_plant_observed": "Установка бомбы в доступной выборке не наблюдалась.",
    "no_untraded_enemy_death_under_pinned_trade_rule": (
        "По закреплённому правилу размена не найдено смерти соперника без размена."
    ),
    "observation_does_not_prove_intent_or_causality": (
        "Наблюдение не доказывает намерение или причинность."
    ),
    "opponent_corpus_below_configured_minimum": (
        "Корпус матчей соперника меньше заданного минимума."
    ),
    "positive_presence_only_absence_not_proven": (
        "Зафиксировано только присутствие; отсутствие действия не доказано."
    ),
    "same_tick_contact_order_not_proven": "Порядок контактов внутри одного тика не доказан.",
    "source_observes_effect_not_throw_tick": (
        "Источник фиксирует эффект гранаты, а не обязательно точный тик броска."
    ),
    "utility_zone_unresolved": "Зона применения гранаты не определена.",
    "utility_zone_unresolved_is_an_explicit_category": (
        "Неопределённая зона гранаты сохранена как отдельная категория."
    ),
}

_WARNING_LABELS = {
    "readiness_gate_has_no_eligible_findings": (
        "Ни одно наблюдение не прошло проверку готовности."
    ),
    "no_counter_strategy_recommendations_published": (
        "Контрстратегические рекомендации пока не опубликованы."
    ),
    "confirmed opponent corpus is below the configured minimum.": (
        "Подтверждённый корпус соперника меньше заданного минимума."
    ),
    "no recommendation is available for real-corpus acceptance.": (
        "Для принятия отчёта по реальному корпусу пока нет рекомендаций."
    ),
}

_BINARY_VALUE_LABELS = {
    "round_contains_lost_man_advantage": "Раунд с потерей численного преимущества",
    "converted_opening_kill": "Раунд выигран после победы в первой дуэли",
    "recovered_after_opening_death": "Раунд выигран после поражения в первой дуэли",
    "round_contains_untraded_death": "Раунд со смертью без размена",
}


def status_label(value: str) -> str:
    return _STATUS_LABELS.get(value.casefold(), value.replace("_", " "))


def finding_title(finding: AnalysisFinding) -> str:
    pattern_label = _PATTERN_LABELS.get(
        finding.pattern_type.value,
        finding.pattern_type.value,
    )
    return f"{pattern_label}: {_value_label(finding)}"


def finding_observation(finding: AnalysisFinding) -> str:
    return (
        f"Наблюдение «{_value_label(finding)}» подтверждено в {finding.numerator} из "
        f"{finding.denominator} подходящих раундов ({finding.frequency:.1%})."
    )


def limitation_label(value: str) -> str:
    return _LIMITATION_LABELS.get(value, value.replace("_", " "))


def warning_label(value: str) -> str:
    normalized = value.casefold()
    if normalized in _WARNING_LABELS:
        return _WARNING_LABELS[normalized]
    patterns = (
        (r"opponent_corpus_below_minimum:(.+)", "Корпус соперника меньше минимума: {}."),
        (r"zero_frequency_patterns_excluded:(\d+)", "Исключено паттернов с нулевой частотой: {}."),
        (r"corpus_below_readiness_minimum:(.+)", "Корпус меньше порога готовности: {}."),
        (
            r"corpus_below_high_reliability_threshold:(.+)",
            "Выборка ниже уровня высокой надёжности: {}. Рекомендации показаны как гипотезы.",
        ),
        (r"stage_8_7_blocked_findings:(\d+)", "Заблокировано наблюдений: {}."),
    )
    for pattern, template in patterns:
        if match := re.fullmatch(pattern, normalized):
            return template.format(match.group(1))
    return limitation_label(value)


def check_label(value: str) -> str:
    return _CHECK_LABELS.get(value, value.replace("_", " "))


def check_message(check: ValidationCheck) -> str:
    result = f"Проверка «{check_label(check.code.value)}»: {status_label(check.status.value)}."
    if check.observed is not None:
        result += f" Получено: {check.observed}."
    if check.required is not None:
        result += f" Требуется: {check.required}."
    return result


def _value_label(finding: AnalysisFinding) -> str:
    value = finding.pattern_value
    if isinstance(value, PlayerPatternValue):
        return value.current_name
    if isinstance(value, BinaryPatternValue):
        return _BINARY_VALUE_LABELS.get(value.key, value.label)
    if isinstance(value, CategoricalPatternValue):
        return _localized_categorical_value(value.label)
    return value.label


def _localized_categorical_value(value: str) -> str:
    replacements = (
        ("initiator at ", "инициатор в "),
        ("receiver at ", "принимающий контакт в "),
        ("flashbang", "флешка"),
        ("inferno", "молотов"),
        ("smoke", "смок"),
        ("zone unavailable", "зона недоступна"),
        ("Bombsite A", "Плент A"),
        ("Bombsite B", "Плент B"),
    )
    result = value
    for source, target in replacements:
        result = result.replace(source, target)
    return result


__all__ = [
    "check_label",
    "check_message",
    "finding_observation",
    "finding_title",
    "limitation_label",
    "status_label",
    "warning_label",
]
