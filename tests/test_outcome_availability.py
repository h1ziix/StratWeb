from __future__ import annotations

from pathlib import Path
from uuid import UUID

import polars as pl
import pytest
from pydantic import ValidationError

from stratweb.application.canonical_models import (
    CanonicalRound,
    CapabilityCoverageStatus,
    DataAvailability,
    RoundOutcomeStatus,
)
from stratweb.application.canonicalization import compute_dataset_fingerprint
from stratweb.application.outcome_policy import evaluate_result_use_policy
from stratweb.application.outcome_resolution import (
    CT_SCORE_FIELD,
    ROUND_END_REASON_FIELD,
    ROUND_WINNER_FIELD,
    T_SCORE_FIELD,
)
from stratweb.application.persistence import load_canonical_dataset
from stratweb.application.round_resolution import RoundResolver
from stratweb.application.validation import result_availability_issues
from stratweb.contracts import ParsedDemo, ParserIdentity
from stratweb.domain.enums import Side

_MATCH_ID = UUID("00000000-0000-0000-0000-000000000451")
_DEMO_ID = UUID("00000000-0000-0000-0000-000000000452")


def _parsed(end_rows: dict[str, list[object]], *, round_count: int = 1) -> ParsedDemo:
    starts = list(range(100, 100 + round_count * 100, 100))
    ends = [tick + 90 for tick in starts]
    tables = {
        "round_prestart": pl.DataFrame(
            {"tick": starts, "total_rounds_played": list(range(round_count))}
        ),
        "round_officially_ended": pl.DataFrame(
            {
                "tick": ends,
                "total_rounds_played": list(range(1, round_count + 1)),
                **end_rows,
            }
        ),
    }
    return ParsedDemo(
        demo_file_id=_DEMO_ID,
        parser=ParserIdentity(name="demoparser2", version="0.41.4"),
        header={"map_name": "de_test"},
        tables=tables,
        available_events=tuple(tables),
    )


def test_authoritative_result_score_and_reason_are_available() -> None:
    result = RoundResolver().resolve(
        _parsed(
            {
                ROUND_WINNER_FIELD: [2],
                ROUND_END_REASON_FIELD: [9],
                T_SCORE_FIELD: [1],
                CT_SCORE_FIELD: [0],
            }
        ),
        _MATCH_ID,
    )

    round_item = result.rounds[0]
    assert round_item.winner_side is Side.T
    assert round_item.outcome_status is RoundOutcomeStatus.SOURCE_EVENT
    assert round_item.outcome_source == (f"round_officially_ended:{ROUND_WINNER_FIELD}")
    assert round_item.score_status is DataAvailability.AVAILABLE
    assert (round_item.score_t_after, round_item.score_ct_after) == (1, 0)
    assert round_item.end_reason == "9"
    assert round_item.end_reason_status is DataAvailability.AVAILABLE
    assert result.result_capabilities.round_winner.status is (CapabilityCoverageStatus.AVAILABLE)


def test_missing_source_fields_are_explicit_and_aggregate() -> None:
    result = RoundResolver().resolve(_parsed({}), _MATCH_ID)
    round_item = result.rounds[0]

    assert round_item.winner_side is None
    assert round_item.outcome_status is RoundOutcomeStatus.MISSING_FROM_SOURCE
    assert round_item.score_status is DataAvailability.MISSING_FROM_SOURCE
    assert round_item.end_reason_status is DataAvailability.MISSING_FROM_SOURCE
    issues = result_availability_issues(result.result_capabilities)
    assert {issue.code for issue in issues} == {
        "round_winner_unavailable",
        "round_score_unavailable",
        "round_end_reason_unavailable",
    }
    assert all(issue.evidence["affected_round_count"] == 1 for issue in issues)


def test_conflicting_winner_values_are_unresolved_not_guessed() -> None:
    result = RoundResolver().resolve(
        _parsed(
            {
                "tick": [190, 190],
                "total_rounds_played": [1, 1],
                ROUND_WINNER_FIELD: [2, 3],
            }
        ),
        _MATCH_ID,
    )

    round_item = result.rounds[0]
    assert round_item.winner_side is None
    assert round_item.outcome_status is RoundOutcomeStatus.UNRESOLVED_CONFLICT
    issues = result_availability_issues(result.result_capabilities)
    assert len(issues) == 3
    conflict = next(issue for issue in issues if issue.code == "round_outcome_conflict")
    assert conflict.is_fatal is False


def test_conflicting_authoritative_event_sources_are_not_hidden_by_precedence() -> None:
    parsed = _parsed({ROUND_WINNER_FIELD: [2]})
    tables = dict(parsed.tables)
    tables["round_end"] = pl.DataFrame(
        {
            "tick": [190],
            "total_rounds_played": [1],
            ROUND_WINNER_FIELD: [3],
        }
    )
    with_conflict = ParsedDemo(
        demo_file_id=parsed.demo_file_id,
        parser=parsed.parser,
        header=parsed.header,
        tables=tables,
        available_events=tuple(tables),
    )

    round_item = RoundResolver().resolve(with_conflict, _MATCH_ID).rounds[0]
    assert round_item.winner_side is None
    assert round_item.outcome_status is RoundOutcomeStatus.UNRESOLVED_CONFLICT
    assert round_item.outcome_source is not None
    assert "round_end" in round_item.outcome_source
    assert "round_officially_ended" in round_item.outcome_source


def test_partial_winner_coverage_is_reported_once() -> None:
    result = RoundResolver().resolve(
        _parsed({ROUND_WINNER_FIELD: [2, None]}, round_count=2),
        _MATCH_ID,
    )

    capability = result.result_capabilities.round_winner
    assert capability.status is CapabilityCoverageStatus.PARTIAL
    assert (capability.rounds_available, capability.rounds_missing) == (1, 1)
    issues = result_availability_issues(result.result_capabilities)
    assert [issue.code for issue in issues].count("partial_round_outcome_coverage") == 1


def test_unknown_cannot_be_serialized_as_a_round_winner() -> None:
    with pytest.raises(ValidationError, match="must use null"):
        CanonicalRound(
            round_id=UUID("00000000-0000-0000-0000-000000000453"),
            match_id=_MATCH_ID,
            round_number=1,
            winner_side=Side.UNKNOWN,
        )


def test_safety_policy_blocks_partial_data_and_allows_complete_data() -> None:
    complete = RoundResolver().resolve(
        _parsed(
            {
                ROUND_WINNER_FIELD: [2],
                T_SCORE_FIELD: [1],
                CT_SCORE_FIELD: [0],
            }
        ),
        _MATCH_ID,
    )
    missing = RoundResolver().resolve(_parsed({}), _MATCH_ID)

    allowed = evaluate_result_use_policy(complete.rounds)
    blocked = evaluate_result_use_policy(missing.rounds)
    assert allowed.round_winner.can_compute_win_metrics is True
    assert allowed.round_score.can_use is True
    assert blocked.round_winner.can_compute_win_metrics is False
    assert blocked.round_score.can_use is False
    assert blocked.round_winner.unavailable_reason == "missing_from_source:1"


def test_availability_metadata_participates_in_fingerprint(
    canonical_dataset_factory: object,
) -> None:
    build = canonical_dataset_factory
    assert callable(build)
    dataset = build()
    changed_capability = dataset.normalization_metadata.result_capabilities.round_winner.model_copy(
        update={"source_events_checked": ("different_source",)}
    )
    changed_metadata = dataset.normalization_metadata.model_copy(
        update={
            "result_capabilities": dataset.normalization_metadata.result_capabilities.model_copy(
                update={"round_winner": changed_capability}
            )
        }
    )
    changed = dataset.model_copy(update={"normalization_metadata": changed_metadata})

    assert compute_dataset_fingerprint(changed) != dataset.dataset_fingerprint
    assert compute_dataset_fingerprint(dataset) == compute_dataset_fingerprint(dataset)


def test_legacy_v1_json_is_upgraded_conservatively() -> None:
    dataset = load_canonical_dataset(Path("canonical-match.json"))

    assert dataset.schema_version == "1.1.0"
    assert all(round_item.winner_side is None for round_item in dataset.rounds)
    assert all(not round_item.outcome_status.is_available for round_item in dataset.rounds)
    assert any(
        "upgraded from 1.0.0" in warning for warning in dataset.normalization_metadata.warnings
    )
