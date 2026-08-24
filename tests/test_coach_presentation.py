from stratweb.patterns.models import (
    BinaryPatternValue,
    CategoricalPatternValue,
    PatternType,
    RoutePatternValue,
    SetupPatternValue,
    ZoneCount,
)
from stratweb.reporting.coach_presentation import coach_pattern_text, is_useful_coach_signal


def test_long_bomb_route_is_compressed_into_plain_russian() -> None:
    value = RoutePatternValue(
        zone_ids=tuple(f"zone-{index}" for index in range(12)),
        zone_names=(
            "T SPAWN",
            "OUTSIDE LONG",
            "LONG DOORS",
            "LONG CORNER",
            "LONG",
            "LONG CORNER",
            "LONG",
            "CAR",
            "RAMP",
            "Bombsite A",
            "RAMP",
            "Bombsite A",
        ),
        label=(
            "T SPAWN → OUTSIDE LONG → LONG DOORS → LONG CORNER → LONG → "
            "LONG CORNER → LONG → CAR → RAMP → Bombsite A → RAMP → Bombsite A"
        ),
    )

    text = coach_pattern_text(PatternType.BOMB_ROUTING, value)

    assert text.title == "Бомбу несли через лонг к точке A"
    assert "→" not in text.title
    assert "LONG" not in text.title


def test_unknown_utility_zone_is_explicit_and_not_promoted() -> None:
    value = CategoricalPatternValue(
        key="utility:inferno:zone:unresolved",
        label="inferno · zone unavailable",
        grenade_type="inferno",
    )

    text = coach_pattern_text(PatternType.FIRST_UTILITY, value)

    assert text.title == "Первая граната — молотов; место не определено"
    assert not is_useful_coach_signal(PatternType.FIRST_UTILITY, value)
    assert "unavailable" not in text.title


def test_spawn_only_signals_are_not_promoted_to_coach_cards() -> None:
    early_spawn = CategoricalPatternValue(
        key="zone:t-spawn",
        label="T SPAWN",
        zone_id="t-spawn",
        zone_name="T SPAWN",
    )
    setup = SetupPatternValue(
        positions=(ZoneCount(zone_id="ct-spawn", zone_name="CT SPAWN", player_count=5),),
        label="CT SPAWN ×5",
    )

    assert not is_useful_coach_signal(PatternType.EARLY_ZONE_OCCUPATION, early_spawn)
    assert not is_useful_coach_signal(PatternType.CT_STARTING_POSITION, setup)
    assert (
        coach_pattern_text(PatternType.CT_STARTING_POSITION, setup).title
        == "Все пять игроков защиты начинали на базе защиты"
    )


def test_internal_binary_labels_never_reach_coach_title() -> None:
    cases = (
        (
            PatternType.LOST_MAN_ADVANTAGE,
            "round_contains_lost_man_advantage",
            "Round contained a lost man advantage",
            "Команда теряла численное преимущество",
        ),
        (
            PatternType.UNTRADED_DEATH,
            "round_contains_untraded_death",
            "Round contained an untraded death",
            "Игрок погибал без быстрого размена",
        ),
        (
            PatternType.OPENING_KILL_CONVERSION,
            "converted_opening_kill",
            "Won round after winning opening duel",
            "После первого убийства команда доводила раунд до победы",
        ),
    )

    for pattern_type, key, raw_label, expected in cases:
        value = BinaryPatternValue(key=key, label=raw_label)
        assert coach_pattern_text(pattern_type, value).title == expected


def test_unknown_zone_is_not_translated_by_guessing() -> None:
    value = CategoricalPatternValue(
        key="zone:mystery",
        label="MYSTERY CALLOUT",
        zone_id="mystery",
        zone_name="MYSTERY CALLOUT",
    )

    title = coach_pattern_text(PatternType.EARLY_ZONE_OCCUPATION, value).title

    assert title == "В начале раунда занимали одну и ту же подтверждённую зону"
    assert "MYSTERY" not in title


def test_tunnel_route_is_not_mislabeled_as_mid_route_because_of_xbox() -> None:
    direct_tunnels = RoutePatternValue(
        zone_ids=("spawn", "tunnels", "xbox", "b"),
        zone_names=("T SPAWN", "UPPER TUNNELS", "XBOX", "Bombsite B"),
        label="T SPAWN → UPPER TUNNELS → XBOX → Bombsite B",
    )
    mid_to_b = RoutePatternValue(
        zone_ids=("spawn", "tunnels", "mid-doors", "ct-mid", "b-doors", "b"),
        zone_names=(
            "T SPAWN",
            "LOWER TUNNELS",
            "MID DOORS",
            "CT MID",
            "B DOORS",
            "Bombsite B",
        ),
        label="T SPAWN → LOWER TUNNELS → MID DOORS → CT MID → B DOORS → Bombsite B",
    )

    assert (
        coach_pattern_text(PatternType.BOMB_ROUTING, direct_tunnels).title
        == "Бомбу несли через туннели к точке B"
    )
    assert (
        coach_pattern_text(PatternType.BOMB_ROUTING, mid_to_b).title
        == "Бомбу несли через мид к точке B"
    )
