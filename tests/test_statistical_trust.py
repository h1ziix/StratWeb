from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import duckdb
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
    DuckDBStatisticalTrustRepository,
)
from stratweb.adapters.persistence._pattern_cascade import delete_pattern_runs
from stratweb.application.opponent_models import OpponentProfile
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.main import create_app
from stratweb.patterns.engine import wilson_confidence
from stratweb.patterns.models import (
    BinaryPatternValue,
    CategoricalPatternValue,
    CrossMatchPattern,
    PatternAvailability,
    PatternRoundEvidence,
    PatternScope,
    PatternType,
)
from stratweb.statistical_trust.engine import StatisticalTrustEngine
from stratweb.statistical_trust.models import (
    StatisticalTrustInput,
    TrustAvailability,
    TrustDecision,
)


def _id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"trust-test:{value}")


def _pattern(
    seed: str,
    successes_by_match: tuple[tuple[int, int], ...],
    *,
    testable: bool = True,
    availability: PatternAvailability = PatternAvailability.AVAILABLE,
) -> CrossMatchPattern:
    run_id = _id("pattern-run")
    included = []
    positive = []
    for match_index, (successes, trials) in enumerate(successes_by_match):
        match_id = _id(f"match:{match_index}")
        for round_number in range(1, trials + 1):
            contributes = round_number <= successes
            evidence = PatternRoundEvidence(
                match_id=match_id,
                round_id=uuid5(match_id, f"round:{round_number}"),
                round_number=round_number,
                tick=round_number * 100,
                contributed_to_numerator=contributes,
            )
            included.append(evidence)
            if contributes:
                positive.append(evidence)
    numerator = len(positive)
    denominator = len(included)
    value = (
        BinaryPatternValue(key=f"binary:{seed}", label=f"Binary {seed}")
        if testable
        else CategoricalPatternValue(key=f"zone:{seed}", label=f"Zone {seed}", zone_id=seed)
    )
    return CrossMatchPattern(
        pattern_id=_id(f"pattern:{seed}"),
        pattern_run_id=run_id,
        profile_id=_id("profile"),
        pattern_type=(
            PatternType.LOST_MAN_ADVANTAGE if testable else PatternType.EARLY_ZONE_OCCUPATION
        ),
        scope=PatternScope(
            map_name="de_mirage",
            side=Side.T,
            buy_type=BuyType.FULL,
            feature_rule_version="per_round_facts_v1",
        ),
        value=value,
        availability=availability,
        numerator=numerator,
        denominator=denominator,
        frequency=numerator / denominator,
        sample_size=denominator,
        minimum_sample_size=5,
        small_sample_warning=denominator < 5,
        confidence=wilson_confidence(numerator, denominator),
        numerator_match_count=sum(successes > 0 for successes, _trials in successes_by_match),
        denominator_match_count=len(successes_by_match),
        evidence_references=tuple(positive),
        included_rounds=tuple(included),
    )


def _input(patterns: tuple[CrossMatchPattern, ...]) -> StatisticalTrustInput:
    return StatisticalTrustInput(
        profile_id=_id("profile"),
        source_pattern_run_id=_id("pattern-run"),
        source_pattern_fingerprint="a" * 64,
        source_pattern_schema_version="1.0.0",
        source_pattern_rule_version="cross_match_patterns_v1",
        patterns=patterns,
    )


def test_statistical_trust_is_deterministic_clustered_and_supported() -> None:
    pattern = _pattern("strong", tuple((9, 10) for _ in range(10)))
    engine = StatisticalTrustEngine()

    first = engine.compute(_input((pattern,)))
    second = engine.compute(_input((pattern,)))
    assessment = first.assessments[0]

    assert first == second
    assert assessment.decision is TrustDecision.SUPPORTED
    assert assessment.clustered_interval.availability is TrustAvailability.AVAILABLE
    assert assessment.clustered_interval.cluster_count == 10
    assert assessment.clustered_interval.lower_bound is not None
    assert assessment.clustered_interval.lower_bound > 0.5
    assert assessment.multiple_comparison.adjusted_q_value is not None
    assert assessment.multiple_comparison.adjusted_q_value <= 0.05
    assert assessment.multiple_comparison.tested_cluster_count == 10
    assert assessment.reliability_rank == 1
    assert assessment.patch_stability.availability is TrustAvailability.UNAVAILABLE
    assert assessment.roster_period_stability.availability is TrustAvailability.UNAVAILABLE


def test_statistical_trust_preserves_match_clusters_and_adjusts_test_family() -> None:
    strong = _pattern("strong", tuple((9, 10) for _ in range(10)))
    weak = _pattern("weak", (*tuple((6, 10) for _ in range(9)), (5, 10)))
    run = StatisticalTrustEngine().compute(_input((strong, weak)))
    by_id = {item.source_pattern_id: item for item in run.assessments}
    strong_result = by_id[strong.pattern_id]
    weak_result = by_id[weak.pattern_id]

    assert sum(item.denominator for item in strong_result.match_contributions) == 100
    assert len(strong_result.match_contributions) == 10
    assert strong_result.multiple_comparison.family_size == 2
    assert strong_result.multiple_comparison.adjusted_q_value is not None
    assert strong_result.multiple_comparison.raw_p_value is not None
    assert (
        strong_result.multiple_comparison.adjusted_q_value
        >= strong_result.multiple_comparison.raw_p_value
    )
    assert weak_result.decision is TrustDecision.NOT_SUPPORTED


def test_cluster_bootstrap_has_cross_python_golden_bounds() -> None:
    pattern = _pattern(
        "hetero",
        ((9, 10), (8, 10), (7, 10), (6, 10), (5, 10)) * 2,
    )
    interval = (
        StatisticalTrustEngine().compute(_input((pattern,))).assessments[0].clustered_interval
    )

    assert interval.lower_bound == 0.61
    assert interval.upper_bound == 0.79


def test_statistical_trust_uses_typed_unavailable_instead_of_invented_baseline() -> None:
    untestable = _pattern("mid", tuple((8, 10) for _ in range(10)), testable=False)
    result = StatisticalTrustEngine().compute(_input((untestable,))).assessments[0]

    assert result.decision is TrustDecision.NOT_TESTABLE
    assert result.null_frequency is None
    assert result.effect_size is None
    assert result.multiple_comparison.availability is TrustAvailability.UNAVAILABLE
    assert "no_pre_registered_null_for_pattern_value" in result.limitations
    assert result.reliability_rank is None


def test_statistical_trust_refuses_support_when_match_corpus_is_too_small() -> None:
    pattern = _pattern("small", ((10, 10), (10, 10)))
    result = StatisticalTrustEngine().compute(_input((pattern,))).assessments[0]

    assert result.decision is TrustDecision.INSUFFICIENT_DATA
    assert result.match_stability.availability is TrustAvailability.UNAVAILABLE
    assert result.reliability_score is None


def test_statistical_trust_refuses_support_for_partial_source_pattern() -> None:
    pattern = _pattern(
        "partial",
        tuple((9, 10) for _ in range(10)),
        availability=PatternAvailability.PARTIAL,
    )
    result = StatisticalTrustEngine().compute(_input((pattern,))).assessments[0]

    assert result.decision is TrustDecision.NOT_SUPPORTED
    assert result.gates.source_quality.value == "fail"
    assert "source_pattern_availability_is_partial" in result.limitations
    assert result.reliability_rank is None


def _persist_source_pattern_run(database: object) -> None:
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO cross_match_pattern_runs (
                pattern_run_id, pattern_fingerprint, pattern_schema_version,
                pattern_rule_version, confidence_method, pattern_config_hash,
                workspace_fingerprint, profile_id, config, capabilities,
                summary, row_counts, warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                _id("pattern-run"),
                "a" * 64,
                "1.0.0",
                "cross_match_patterns_v1",
                "wilson_score_95_v1",
                "b" * 64,
                "c" * 64,
                _id("profile"),
                "{}",
                "{}",
                "{}",
                "{}",
                "[]",
            ],
        )


def test_statistical_trust_persistence_round_trip_and_pattern_cascade(tmp_path: Path) -> None:
    database = tmp_path / "trust.duckdb"
    DuckDBMatchRepository(database).initialize()
    _persist_source_pattern_run(database)
    pattern = _pattern("strong", tuple((9, 10) for _ in range(10)))
    state = StatisticalTrustEngine().compute(_input((pattern,)))
    repository = DuckDBStatisticalTrustRepository(database)

    saved = repository.save_trust(state)
    repeated = repository.save_trust(state)
    summary = repository.get_summary_for_run(_id("profile"), state.trust_run_id)
    assessments = repository.list_assessments(_id("profile"), trust_run_id=state.trust_run_id)

    assert saved.row_counts["statistical_trust_assessments"] == 1
    assert repeated.status.value == "already_exists"
    assert summary is not None
    assert summary.summary.supported_patterns == 1
    assert assessments == state.assessments

    with duckdb.connect(str(database)) as connection:
        delete_pattern_runs(connection, pattern_run_ids=[_id("pattern-run")])
        assert connection.execute("SELECT count(*) FROM statistical_trust_runs").fetchone() == (0,)


def test_statistical_trust_json_endpoints_return_pinned_run(tmp_path: Path) -> None:
    database = tmp_path / "trust-api.duckdb"
    DuckDBMatchRepository(database).initialize()
    _persist_source_pattern_run(database)
    state = StatisticalTrustEngine().compute(
        _input((_pattern("strong", tuple((9, 10) for _ in range(10))),))
    )
    DuckDBStatisticalTrustRepository(database).save_trust(state)
    now = datetime.now(UTC)
    DuckDBOpponentRepository(database).create_profile(
        OpponentProfile(
            profile_id=_id("profile"),
            display_name="Fixture opponent",
            created_at=now,
            updated_at=now,
        )
    )

    with TestClient(create_app(database)) as client:
        summary = client.get(
            f"/api/opponents/{_id('profile')}/statistical-trust/summary",
            params={"run_id": str(state.trust_run_id)},
        )
        assessments = client.get(
            f"/api/opponents/{_id('profile')}/statistical-trust/assessments",
            params={"run_id": str(state.trust_run_id)},
        )
        page = client.get(
            f"/ui/opponents/{_id('profile')}/statistical-trust",
            params={"run_id": str(state.trust_run_id)},
        )

    assert summary.status_code == 200
    assert summary.json()["trust_rule_version"] == "match_clustered_trust_v1"
    assert assessments.status_code == 200
    assert assessments.json()["count"] == 1
    assert page.status_code == 200
    assert "Статистическая надёжность" in page.text
    assert "match_clustered_trust_v1" in page.text
