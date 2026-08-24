"""Deterministic plain-language projection for the coach report.

The analytics layer deliberately preserves parser-derived labels.  This module is a
presentation boundary: it turns typed pattern values into short Russian phrases without
changing statistics, evidence, or the persisted source value.
"""

from __future__ import annotations

from dataclasses import dataclass

from stratweb.patterns.models import (
    BinaryPatternValue,
    CategoricalPatternValue,
    PatternType,
    PatternValue,
    PlayerPatternValue,
    RoutePatternValue,
    SetupPatternValue,
    TimingBucketPatternValue,
)


@dataclass(frozen=True, slots=True)
class CoachPatternText:
    """Short wording shown to a player or coach."""

    kind: str
    title: str
    explanation: str


_KIND_LABELS = {
    PatternType.SITE_PREFERENCE: "Выбор точки",
    PatternType.EARLY_ZONE_OCCUPATION: "Начало раунда",
    PatternType.RECURRING_OPENING_PLAYER: "Первое убийство",
    PatternType.RECURRING_OPENING_DEATH: "Первая потеря",
    PatternType.FIRST_CONTACT_ZONE: "Первый контакт",
    PatternType.FIRST_UTILITY: "Первая граната",
    PatternType.BOMB_ROUTING: "Движение бомбы",
    PatternType.CT_STARTING_POSITION: "Начало защиты",
    PatternType.EARLY_ROTATION: "Раннее смещение",
    PatternType.OPENING_KILL_CONVERSION: "После первого убийства",
    PatternType.RECOVERY_AFTER_OPENING_DEATH: "После первой потери",
    PatternType.LOST_MAN_ADVANTAGE: "Потеря преимущества",
    PatternType.UNTRADED_DEATH: "Размены",
    PatternType.PLANT_TIMING: "Установка бомбы",
    PatternType.RETAKE_FREQUENCY: "Ретейки",
    PatternType.SAVE_FREQUENCY: "Сохранение оружия",
}

# Callouts remain exact in the analyst report.  The coach view uses familiar Russian CS
# vocabulary and never exposes an unknown English token as though it had been translated.
_ZONE_NAMES = {
    "T SPAWN": "база атаки",
    "CT SPAWN": "база защиты",
    "BOMBSITE A": "точка A",
    "BOMBSITE B": "точка B",
    "A SITE": "точка A",
    "B SITE": "точка B",
    "OUTSIDE LONG": "подход к лонгу",
    "LONG DOORS": "двери лонга",
    "LONG CORNER": "угол лонга",
    "LONG": "лонг",
    "SHORT": "шорт",
    "A SHORT": "шорт A",
    "CAT": "шорт",
    "CATWALK": "шорт",
    "CAR": "машина",
    "RAMP": "рампа",
    "A RAMP": "рампа A",
    "MID": "мид",
    "TOP MID": "верх мида",
    "CT MID": "мид защиты",
    "MID DOORS": "двери мида",
    "DOUBLE DOORS": "двойные двери",
    "SUICIDE": "суицид",
    "PIT": "яма",
    "OUTSIDE TUNNELS": "подход к туннелям",
    "UPPER TUNNELS": "верхние туннели",
    "LOWER TUNNELS": "нижние туннели",
    "TUNNELS": "туннели",
    "B DOORS": "двери B",
    "B PLAT": "платформа B",
    "WINDOW": "окно",
    "XBOX": "икс-бокс",
    "BLUE": "синий ящик",
    "GREEN": "зелёный ящик",
    "CROSS": "переход",
    "STAIRS": "лестница",
    "BOOST": "буст",
    "BOX": "ящики",
    "CLOSET": "ниша",
    "NINJA": "ниндзя",
    "DOG": "дог",
    "PALM": "пальма",
    "FENCE": "забор",
    "A MAIN": "мейн A",
    "B MAIN": "мейн B",
    "CONNECTOR": "коннектор",
    "HEAVEN": "хэвен",
    "HELL": "хелл",
    "WATER": "вода",
    "BRIDGE": "мост",
    "ALLEY": "аллея",
    "RUINS": "руины",
}

_GRENADE_NAMES = {
    "smoke": "дым",
    "smokegrenade": "дым",
    "inferno": "молотов",
    "molotov": "молотов",
    "incendiary": "зажигательная граната",
    "flash": "флешка",
    "flashbang": "флешка",
    "he": "осколочная граната",
    "hegrenade": "осколочная граната",
    "decoy": "ложная граната",
}

_BINARY_TITLES = {
    "round_contains_lost_man_advantage": "Команда теряла численное преимущество",
    "round_contains_untraded_death": "Игрок погибал без быстрого размена",
    "converted_opening_kill": "После первого убийства команда доводила раунд до победы",
    "recovered_after_opening_death": "После первой потери команда возвращалась в раунд",
    "retake": "Команда переходила к ретейку",
    "save": "Команда сохраняла оружие",
}


def coach_pattern_text(pattern_type: PatternType, value: PatternValue) -> CoachPatternText:
    """Return deterministic coach wording for one typed pattern value."""

    kind = _KIND_LABELS[pattern_type]
    explanation = (
        "Формулировка сокращена для быстрого чтения. Точное значение и исходные раунды "
        "сохранены в доказательствах."
    )

    if isinstance(value, PlayerPatternValue):
        action = (
            "чаще других делал первое убийство"
            if value.role == "opening_killer"
            else "чаще других погибал первым"
        )
        return CoachPatternText(
            kind=kind,
            title=f"{value.current_name} {action}",
            explanation=explanation,
        )

    if isinstance(value, RoutePatternValue):
        return CoachPatternText(kind=kind, title=_route_title(value), explanation=explanation)

    if isinstance(value, SetupPatternValue):
        return CoachPatternText(kind=kind, title=_setup_title(value), explanation=explanation)

    if isinstance(value, TimingBucketPatternValue):
        return CoachPatternText(kind=kind, title=_timing_title(value), explanation=explanation)

    if isinstance(value, BinaryPatternValue):
        return CoachPatternText(
            kind=kind,
            title=_BINARY_TITLES.get(value.key, _binary_fallback(pattern_type)),
            explanation=explanation,
        )

    if isinstance(value, CategoricalPatternValue):
        return CoachPatternText(
            kind=kind,
            title=_categorical_title(pattern_type, value),
            explanation=explanation,
        )

    return CoachPatternText(
        kind=kind,
        title="Зафиксировано повторяющееся действие",
        explanation=explanation,
    )


def is_useful_coach_signal(pattern_type: PatternType, value: PatternValue) -> bool:
    """Exclude technically valid but tactically empty cards from the short coach deck."""

    if pattern_type is PatternType.EARLY_ZONE_OCCUPATION and isinstance(
        value, CategoricalPatternValue
    ):
        return _normalized_zone(value.zone_name or value.label) not in {"T SPAWN", "CT SPAWN"}
    if pattern_type is PatternType.CT_STARTING_POSITION and isinstance(value, SetupPatternValue):
        return not all(
            _normalized_zone(item.zone_name) in {"T SPAWN", "CT SPAWN"} for item in value.positions
        )
    if pattern_type is PatternType.FIRST_UTILITY and isinstance(value, CategoricalPatternValue):
        return value.zone_id is not None and value.zone_name is not None
    return True


def _categorical_title(pattern_type: PatternType, value: CategoricalPatternValue) -> str:
    zone = _localized_zone(value.zone_name)
    if pattern_type is PatternType.SITE_PREFERENCE:
        site = _site_from_value(value)
        return f"Чаще выбирали точку {site}" if site else "Повторялся выбор одной точки"
    if pattern_type is PatternType.EARLY_ZONE_OCCUPATION:
        return (
            f"В начале раунда занимали зону «{zone}»"
            if zone
            else (
                "В начале раунда занимали одну и ту же подтверждённую зону"
                if value.zone_name is not None
                else "Зона в начале раунда не определена"
            )
        )
    if pattern_type is PatternType.FIRST_CONTACT_ZONE:
        verb = "начинали" if value.role == "initiator" else "принимали"
        return (
            f"Первый контакт {verb} в зоне «{zone}»"
            if zone
            else (
                f"Первый контакт чаще {verb} в одной подтверждённой зоне"
                if value.zone_name is not None
                else "Место первого контакта не определено"
            )
        )
    if pattern_type is PatternType.FIRST_UTILITY:
        grenade = _GRENADE_NAMES.get((value.grenade_type or "").casefold(), "граната")
        return (
            f"Первая граната — {grenade} в зоне «{zone}»"
            if zone
            else (
                f"Первая граната — {grenade} в одной подтверждённой зоне"
                if value.zone_name is not None
                else f"Первая граната — {grenade}; место не определено"
            )
        )
    if pattern_type is PatternType.EARLY_ROTATION:
        return (
            f"Рано смещались в зону «{zone}»"
            if zone
            else "Повторялось раннее смещение; конечная зона не определена"
        )
    return f"Повторяющееся действие в зоне «{zone}»" if zone else "Повторяющееся действие"


def _route_title(value: RoutePatternValue) -> str:
    names = _collapse_adjacent(value.zone_names)
    normalized = tuple(_normalized_zone(item) for item in names)
    site = _route_site(normalized)
    corridor = _route_corridor(normalized, site)
    if site and corridor:
        return f"Бомбу несли {corridor} к точке {site}"
    if site:
        return f"Маршрут бомбы заканчивался на точке {site}"
    destination = next(
        (_localized_zone(item) for item in reversed(names) if not _is_spawn(item)),
        None,
    )
    if destination:
        return f"Бомбу регулярно несли в сторону зоны «{destination}»"
    return "Зафиксирован повторяющийся маршрут бомбы"


def _route_site(names: tuple[str, ...]) -> str | None:
    for name in reversed(names):
        if name in {"BOMBSITE A", "A SITE"}:
            return "A"
        if name in {"BOMBSITE B", "B SITE"}:
            return "B"
    return None


def _route_corridor(names: tuple[str, ...], site: str | None) -> str | None:
    values = set(names)
    if site == "B" and values.intersection({"MID", "MID DOORS", "CT MID", "B DOORS"}):
        return "через мид"
    if values.intersection({"LONG", "LONG DOORS", "LONG CORNER", "OUTSIDE LONG"}):
        return "через лонг"
    if values.intersection({"SHORT", "A SHORT", "CAT", "CATWALK"}):
        return "через шорт"
    if values.intersection({"TUNNELS", "UPPER TUNNELS", "LOWER TUNNELS"}):
        return "через туннели"
    if values.intersection({"A MAIN", "B MAIN"}):
        return "через мейн"
    return None


def _setup_title(value: SetupPatternValue) -> str:
    if len(value.positions) == 1:
        position = value.positions[0]
        zone = _localized_zone(position.zone_name)
        if _normalized_zone(position.zone_name) == "CT SPAWN" and position.player_count == 5:
            return "Все пять игроков защиты начинали на базе защиты"
        if zone:
            return f"{_players(position.player_count)} начинали в зоне «{zone}»"
    parts = []
    for position in value.positions[:3]:
        zone = _localized_zone(position.zone_name)
        if zone:
            parts.append(f"{position.player_count} — {zone}")
    return (
        f"Расстановка защиты: {', '.join(parts)}"
        if parts
        else "Повторялась одна стартовая расстановка защиты"
    )


def _timing_title(value: TimingBucketPatternValue) -> str:
    lower = value.lower_seconds
    upper = value.upper_seconds
    if lower == 0 and upper is not None:
        return f"Бомбу ставили в первые {upper:g} секунд"
    if upper is None:
        return f"Бомбу ставили через {lower:g} секунд или позже"
    return f"Бомбу ставили через {lower:g}–{upper:g} секунд"


def _binary_fallback(pattern_type: PatternType) -> str:
    return {
        PatternType.OPENING_KILL_CONVERSION: (
            "После первого убийства команда доводила раунд до победы"
        ),
        PatternType.RECOVERY_AFTER_OPENING_DEATH: (
            "После первой потери команда возвращалась в раунд"
        ),
        PatternType.LOST_MAN_ADVANTAGE: "Команда теряла численное преимущество",
        PatternType.UNTRADED_DEATH: "Игрок погибал без быстрого размена",
        PatternType.RETAKE_FREQUENCY: "Команда переходила к ретейку",
        PatternType.SAVE_FREQUENCY: "Команда сохраняла оружие",
    }.get(pattern_type, "Зафиксировано повторяющееся событие")


def _site_from_value(value: CategoricalPatternValue) -> str | None:
    key = value.key.casefold()
    normalized = _normalized_zone(value.zone_name or value.label)
    if key.endswith(":a") or normalized in {"BOMBSITE A", "A SITE"}:
        return "A"
    if key.endswith(":b") or normalized in {"BOMBSITE B", "B SITE"}:
        return "B"
    return None


def _localized_zone(value: str | None) -> str | None:
    if value is None:
        return None
    localized = _ZONE_NAMES.get(_normalized_zone(value))
    if localized is not None:
        return localized
    cleaned = " ".join(value.split())
    return cleaned if any("\u0400" <= character <= "\u04ff" for character in cleaned) else None


def _normalized_zone(value: str) -> str:
    return " ".join(value.replace("_", " ").split()).upper()


def _collapse_adjacent(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if not result or _normalized_zone(result[-1]) != _normalized_zone(value):
            result.append(value)
    return tuple(result)


def _is_spawn(value: str) -> bool:
    return _normalized_zone(value) in {"T SPAWN", "CT SPAWN"}


def _players(count: int) -> str:
    if count == 1:
        return "Один игрок"
    if count in {2, 3, 4}:
        return f"{count} игрока"
    return f"{count} игроков"


__all__ = ["CoachPatternText", "coach_pattern_text", "is_useful_coach_signal"]
