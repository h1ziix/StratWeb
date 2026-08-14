from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from stratweb import cli
from stratweb.application.canonical_models import CanonicalMatchDataset
from stratweb.exceptions import DemoParseError
from stratweb.golden_corpus.evaluation import GoldenFindingEvaluator
from stratweb.golden_corpus.manifest import (
    GoldenCorpusValidator,
    load_manifest,
    load_predictions,
    manifest_fingerprint,
)
from stratweb.golden_corpus.models import (
    CaseReviewStatus,
    CorpusEdgeCase,
    CorpusIssueCode,
    CorpusReadinessStatus,
    DemoSource,
    ExpectedMatchFacts,
    ExpectedParseStatus,
    FindingLabelValue,
    GoldenCorpusManifest,
    GoldenCorpusPolicy,
    GoldenDemoCase,
    GoldenEvidenceReference,
    GoldenFindingLabel,
    GoldenFindingPrediction,
    GoldenPredictionSet,
    ParserCompatibilityRecord,
    ParserCompatibilityStatus,
    ParserRequirement,
    PredictionValue,
)
from stratweb.golden_corpus.runner import GoldenCorpusRunner

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _confirmed_case(index: int, *, source: DemoSource = DemoSource.FACEIT) -> GoldenDemoCase:
    return GoldenDemoCase(
        case_id=f"case-{index:02d}",
        demo_sha256=_digest(f"demo-{index}"),
        source=source,
        review_status=CaseReviewStatus.CONFIRMED,
        expected_parse_status=ExpectedParseStatus.SUCCESS,
        opponent_id="opponent-stable-id",
        opponent_confirmed=True,
        expected=ExpectedMatchFacts(
            match_id=uuid5(NAMESPACE_URL, f"match-{index}"),
            dataset_fingerprint=_digest(f"dataset-{index}"),
            map_name=("de_mirage", "de_ancient", "de_dust2")[index % 3],
            round_count=20,
            complete_round_count=20,
            incomplete_round_count=0,
            canonical_schema_version="1.1.0",
            normalization_rule_version="1.1.0",
        ),
        edge_cases=(
            (
                CorpusEdgeCase.OVERTIME,
                CorpusEdgeCase.SUBSTITUTION,
                CorpusEdgeCase.MISSING_STEAM_ID,
                CorpusEdgeCase.DAMAGED_DEMO,
                CorpusEdgeCase.INCOMPLETE_DEMO,
            )
            if index == 0
            else ()
        ),
        reviewed_at=NOW,
        reviewed_by_role="analyst",
    )


def _label(
    label_id: str,
    value: FindingLabelValue,
    case: GoldenDemoCase,
) -> GoldenFindingLabel:
    evidence = (
        (
            GoldenEvidenceReference(
                case_id=case.case_id,
                match_id=case.expected.match_id,
                round_number=1,
                tick=100,
                event_id=uuid5(NAMESPACE_URL, label_id),
            ),
        )
        if value is FindingLabelValue.PRESENT
        else ()
    )
    return GoldenFindingLabel(
        label_id=label_id,
        finding_key=f"finding:{label_id}",
        value=value,
        evidence_references=evidence,
        reviewed_at=NOW,
        reviewed_by_role="analyst",
        rationale="Reviewed deterministic fixture.",
        limitations=("Evidence is insufficient for a binary label.",)
        if value is FindingLabelValue.INDETERMINATE
        else (),
    )


def _ready_manifest(
    *, labels: tuple[GoldenFindingLabel, ...] | None = None
) -> GoldenCorpusManifest:
    sources = (
        DemoSource.FACEIT,
        DemoSource.VALVE,
        DemoSource.GOTV_HLTV,
        DemoSource.POV,
    )
    cases = tuple(_confirmed_case(index, source=sources[index % 4]) for index in range(20))
    selected_labels = labels or (
        _label("label.present", FindingLabelValue.PRESENT, cases[0]),
        _label("label.absent", FindingLabelValue.ABSENT, cases[1]),
    )
    compatibility = tuple(
        ParserCompatibilityRecord(
            case_id=case.case_id,
            parser_name="demoparser2",
            parser_version="0.41.4",
            status=ParserCompatibilityStatus.SUPPORTED,
            checked_at=NOW,
            observed_dataset_fingerprint=case.expected.dataset_fingerprint,
        )
        for case in cases
    )
    return GoldenCorpusManifest(
        corpus_id="test-ready-corpus",
        corpus_version="1.0.0",
        target_opponent_id="opponent-stable-id",
        created_at=NOW,
        updated_at=NOW,
        cases=cases,
        finding_labels=selected_labels,
        parser_compatibility=compatibility,
    )


def test_repository_candidate_manifest_is_valid_but_honestly_blocked() -> None:
    manifest = load_manifest(Path("corpus/golden-corpus-v1.json"))
    audit = GoldenCorpusValidator().validate(manifest)
    predictions = load_predictions(Path("corpus/predictions.example.json"))

    assert audit.status is CorpusReadinessStatus.BLOCKED
    assert audit.coverage.total_cases == 5
    assert audit.coverage.confirmed_cases == 0
    assert audit.coverage.candidate_cases == 5
    assert predictions.manifest_fingerprint == audit.manifest_fingerprint
    assert {item.code for item in audit.issues} >= {
        CorpusIssueCode.TARGET_OPPONENT_UNKNOWN,
        CorpusIssueCode.CONFIRMED_MATCHES_BELOW_MINIMUM,
        CorpusIssueCode.SOURCE_COVERAGE_INCOMPLETE,
        CorpusIssueCode.FINDING_LABELS_INCOMPLETE,
    }


def test_complete_twenty_match_manifest_passes_metadata_readiness() -> None:
    audit = GoldenCorpusValidator().validate(_ready_manifest())

    assert audit.status is CorpusReadinessStatus.READY
    assert audit.coverage.confirmed_opponent_matches == 20
    assert audit.coverage.distinct_opponent_maps == ("de_ancient", "de_dust2", "de_mirage")
    assert audit.coverage.determinate_finding_labels == 2
    assert audit.coverage.positive_finding_labels == 1
    assert audit.coverage.negative_finding_labels == 1
    assert [item.code for item in audit.issues] == [CorpusIssueCode.DEMO_ROOT_NOT_CHECKED]


def test_required_parser_must_be_supported_not_merely_listed() -> None:
    manifest = _ready_manifest()
    first = manifest.parser_compatibility[0].model_copy(
        update={
            "status": ParserCompatibilityStatus.PARTIAL,
            "limitations": ("Known parser regression.",),
        }
    )
    manifest = manifest.model_copy(
        update={"parser_compatibility": (first, *manifest.parser_compatibility[1:])}
    )

    audit = GoldenCorpusValidator().validate(manifest)

    assert audit.status is CorpusReadinessStatus.BLOCKED
    parser_issue = next(
        item for item in audit.issues if item.code is CorpusIssueCode.PARSER_MATRIX_INCOMPLETE
    )
    assert parser_issue.affected_case_ids == ("case-00",)


def test_file_verification_uses_sha_address_and_never_original_name(tmp_path: Path) -> None:
    payload = b"PBDEMS2-golden-fixture"
    digest = hashlib.sha256(payload).hexdigest()
    demo = tmp_path / f"{digest}.dem"
    demo.write_bytes(payload)
    case = GoldenDemoCase(
        case_id="case-file",
        demo_sha256=digest,
        source=DemoSource.FACEIT,
        review_status=CaseReviewStatus.CONFIRMED,
        expected_parse_status=ExpectedParseStatus.SUCCESS,
        opponent_id="opponent",
        opponent_confirmed=True,
        expected=ExpectedMatchFacts(map_name="de_mirage"),
        edge_cases=(CorpusEdgeCase.SIDE_SWITCH,),
        reviewed_at=NOW,
        reviewed_by_role="analyst",
    )
    label = _label("label.absent", FindingLabelValue.ABSENT, case)
    manifest = GoldenCorpusManifest(
        corpus_id="file-corpus",
        corpus_version="1",
        target_opponent_id="opponent",
        created_at=NOW,
        updated_at=NOW,
        policy=GoldenCorpusPolicy(
            minimum_confirmed_opponent_matches=1,
            minimum_distinct_opponent_maps=1,
            minimum_determinate_finding_labels=1,
            minimum_positive_finding_labels=0,
            minimum_negative_finding_labels=1,
            required_sources=(DemoSource.FACEIT,),
            required_edge_cases=(CorpusEdgeCase.SIDE_SWITCH,),
            required_parsers=(ParserRequirement(parser_name="fixture", parser_version="1"),),
        ),
        cases=(case,),
        finding_labels=(label,),
        parser_compatibility=(
            ParserCompatibilityRecord(
                case_id=case.case_id,
                parser_name="fixture",
                parser_version="1",
                status=ParserCompatibilityStatus.SUPPORTED,
                checked_at=NOW,
            ),
        ),
    )

    audit = GoldenCorpusValidator().validate(manifest, demo_root=tmp_path)

    assert audit.status is CorpusReadinessStatus.READY
    assert audit.coverage.checked_demo_files == 1
    assert audit.coverage.valid_demo_files == 1
    assert audit.file_checks[0].path == str(demo.resolve())


def test_expected_round_counts_cannot_be_internally_inconsistent() -> None:
    with pytest.raises(ValidationError, match="must equal round_count"):
        ExpectedMatchFacts(
            round_count=20,
            complete_round_count=19,
            incomplete_round_count=0,
        )


def test_finding_evaluation_is_deterministic_and_excludes_unknowns() -> None:
    cases = tuple(_confirmed_case(index) for index in range(4))
    labels = (
        _label("label.tp", FindingLabelValue.PRESENT, cases[0]),
        _label("label.fp", FindingLabelValue.ABSENT, cases[1]),
        _label("label.fn", FindingLabelValue.PRESENT, cases[2]),
        _label("label.unknown", FindingLabelValue.INDETERMINATE, cases[3]),
    )
    manifest = _ready_manifest(labels=labels)
    predictions = GoldenPredictionSet(
        manifest_fingerprint=manifest_fingerprint(manifest),
        algorithm_version="finding-engine-test-v1",
        predictions=(
            GoldenFindingPrediction(label_id="label.tp", value=PredictionValue.PRESENT),
            GoldenFindingPrediction(label_id="label.fp", value=PredictionValue.PRESENT),
            GoldenFindingPrediction(label_id="label.fn", value=PredictionValue.ABSENT),
        ),
    )

    first = GoldenFindingEvaluator().evaluate(manifest, predictions)
    second = GoldenFindingEvaluator().evaluate(manifest, predictions)

    assert first == second
    assert first.complete is True
    assert first.metrics.sample_size == 3
    assert first.metrics.true_positive == 1
    assert first.metrics.false_positive == 1
    assert first.metrics.false_negative == 1
    assert first.metrics.precision == 0.5
    assert first.metrics.recall == 0.5
    assert first.metrics.f1 == 0.5
    assert first.indeterminate_label_ids == ("label.unknown",)


def test_missing_prediction_is_unavailable_not_assumed_absent() -> None:
    manifest = _ready_manifest()
    predictions = GoldenPredictionSet(
        manifest_fingerprint=manifest_fingerprint(manifest),
        algorithm_version="finding-engine-test-v1",
        predictions=(
            GoldenFindingPrediction(label_id="label.absent", value=PredictionValue.ABSENT),
        ),
    )

    report = GoldenFindingEvaluator().evaluate(manifest, predictions)

    assert report.complete is False
    assert report.metrics.sample_size == 1
    assert report.metrics.false_negative == 0
    assert report.metrics.precision is None
    assert report.missing_prediction_ids == ("label.present",)


def test_runner_compares_reviewed_facts_and_isolates_expected_parse_failure(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    success_payload = b"success-demo"
    damaged_payload = b"damaged-demo"
    success_hash = hashlib.sha256(success_payload).hexdigest()
    damaged_hash = hashlib.sha256(damaged_payload).hexdigest()
    (tmp_path / f"{success_hash}.dem").write_bytes(success_payload)
    (tmp_path / f"{damaged_hash}.dem").write_bytes(damaged_payload)
    dataset: CanonicalMatchDataset = canonical_dataset_factory("runner")
    success = GoldenDemoCase(
        case_id="case-success",
        demo_sha256=success_hash,
        source=DemoSource.FACEIT,
        review_status=CaseReviewStatus.CONFIRMED,
        expected_parse_status=ExpectedParseStatus.SUCCESS,
        opponent_id="opponent",
        opponent_confirmed=True,
        expected=ExpectedMatchFacts(
            match_id=dataset.match.match_id,
            dataset_fingerprint=dataset.dataset_fingerprint,
            map_name=dataset.match.map_name,
            round_count=dataset.match.round_count,
            complete_round_count=dataset.match.complete_round_count,
            incomplete_round_count=dataset.match.incomplete_round_count,
            canonical_schema_version=dataset.schema_version,
            normalization_rule_version=dataset.normalization_metadata.normalization_rule_version,
        ),
        reviewed_at=NOW,
        reviewed_by_role="analyst",
    )
    damaged = GoldenDemoCase(
        case_id="case-damaged",
        demo_sha256=damaged_hash,
        source=DemoSource.FACEIT,
        review_status=CaseReviewStatus.CONFIRMED,
        expected_parse_status=ExpectedParseStatus.REJECTED,
        opponent_id="opponent",
        opponent_confirmed=True,
        edge_cases=(CorpusEdgeCase.DAMAGED_DEMO,),
        reviewed_at=NOW,
        reviewed_by_role="analyst",
    )
    manifest = GoldenCorpusManifest(
        corpus_id="runner-corpus",
        corpus_version="1",
        target_opponent_id="opponent",
        created_at=NOW,
        updated_at=NOW,
        cases=(success, damaged),
    )

    class FakeNormalizer:
        def normalize(self, path: Path) -> CanonicalMatchDataset:
            if path.stem == damaged_hash:
                raise DemoParseError("expected fixture rejection")
            return dataset

    report = GoldenCorpusRunner(FakeNormalizer(), parser_name="fixture", parser_version="1").run(
        manifest, tmp_path
    )

    assert report.complete is True
    assert report.passed is True
    assert report.passed_cases == 2
    assert report.failed_cases == 0
    assert {item.case_id for item in report.results} == {"case-success", "case-damaged"}


def test_cli_reports_blockers_and_has_optional_strict_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    normal = cli.main(["corpus", "validate", "--manifest", "corpus/golden-corpus-v1.json"])
    output = json.loads(capsys.readouterr().out)
    strict = cli.main(
        [
            "corpus",
            "validate",
            "--manifest",
            "corpus/golden-corpus-v1.json",
            "--require-ready",
        ]
    )
    capsys.readouterr()

    assert normal == 0
    assert output["status"] == "blocked"
    assert strict == 11
