from __future__ import annotations

from uuid import uuid4

import polars as pl

from stratweb.application.event_normalization import InspectionEventNormalizer
from stratweb.contracts import ParsedDemo, ParserIdentity


def _parsed_demo(
    tables: dict[str, pl.DataFrame],
    *,
    available_events: tuple[str, ...] | None = None,
) -> ParsedDemo:
    return ParsedDemo(
        demo_file_id=uuid4(),
        parser=ParserIdentity(name="demoparser2", version="0.41.4"),
        header={},
        tables=tables,
        available_events=available_events or tuple(tables),
    )


def test_faceit_aliases_are_mapped_without_standard_round_events() -> None:
    parsed = _parsed_demo(
        {
            "player_hurt": pl.DataFrame({"tick": [10, 20, 30], "total_rounds_played": [1, 12, 24]}),
            "round_freeze_end": pl.DataFrame(
                {
                    "tick": list(range(100, 124)),
                    "total_rounds_played": list(range(24)),
                }
            ),
            "round_officially_ended": pl.DataFrame(
                {
                    "tick": list(range(200, 224)),
                    "total_rounds_played": list(range(1, 25)),
                }
            ),
        }
    )

    result = InspectionEventNormalizer().normalize(parsed)

    assert result.estimated_round_count == 24
    assert result.estimated_round_count_source == "max_total_rounds_played"
    assert result.canonical_events["CanonicalRoundStart"].count == 24
    assert result.canonical_events["CanonicalRoundEnd"].count == 24
    assert result.warnings == ()


def test_alias_families_are_not_summed_or_double_counted() -> None:
    rounds = list(range(1, 6))
    parsed = _parsed_demo(
        {
            "round_freeze_end": pl.DataFrame(
                {"tick": list(range(10, 15)), "total_rounds_played": rounds}
            ),
            "round_start": pl.DataFrame(
                {"tick": list(range(20, 25)), "total_rounds_played": rounds}
            ),
            "round_officially_ended": pl.DataFrame(
                {"tick": list(range(30, 35)), "total_rounds_played": rounds}
            ),
            "round_end": pl.DataFrame({"tick": list(range(40, 45)), "total_rounds_played": rounds}),
        }
    )

    result = InspectionEventNormalizer().normalize(parsed)

    start = result.canonical_events["CanonicalRoundStart"]
    end = result.canonical_events["CanonicalRoundEnd"]
    assert start.count == 5
    assert start.selected_source_event == "round_freeze_end"
    assert start.source_row_counts == {"round_freeze_end": 5, "round_start": 5}
    assert end.count == 5
    assert end.selected_source_event == "round_officially_ended"


def test_global_round_counter_works_without_any_round_lifecycle_events() -> None:
    parsed = _parsed_demo(
        {"player_death": pl.DataFrame({"tick": [1, 2, 3], "total_rounds_played": [3, 19, 27]})}
    )

    result = InspectionEventNormalizer().normalize(parsed)

    assert result.estimated_round_count == 27
    assert result.canonical_events["CanonicalRoundStart"].count == 0
    assert result.canonical_events["CanonicalRoundEnd"].count == 0
    assert result.warnings == ()


def test_warmup_rows_are_excluded_from_lifecycle_fallback() -> None:
    parsed = _parsed_demo(
        {
            "round_poststart": pl.DataFrame(
                {
                    "tick": [1, 2, 3, 4],
                    "is_warmup_period": [True, False, False, False],
                }
            )
        }
    )

    result = InspectionEventNormalizer().normalize(parsed)

    assert result.estimated_round_count == 3
    assert result.estimated_round_count_source == "canonical_round_start_count"
    assert result.canonical_events["CanonicalRoundStart"].count == 3
    assert result.warnings == (
        "Round count is estimated from canonical lifecycle events because "
        "total_rounds_played is unavailable.",
    )


def test_total_round_counter_has_priority_and_disagreement_is_reported() -> None:
    parsed = _parsed_demo(
        {
            "player_hurt": pl.DataFrame({"total_rounds_played": [24]}),
            "round_freeze_end": pl.DataFrame({"tick": list(range(25))}),
        }
    )

    result = InspectionEventNormalizer().normalize(parsed)

    assert result.estimated_round_count == 24
    assert result.estimated_round_count_source == "max_total_rounds_played"
    assert result.round_count_candidates == {
        "max_total_rounds_played": 24,
        "canonical_round_start_count": 25,
    }
    assert "candidates disagree" in result.warnings[0]
