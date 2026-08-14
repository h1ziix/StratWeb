"""Strict Stage 9.1 Golden Corpus models.

Raw demo files deliberately do not belong to these models. A manifest identifies a demo
only by SHA-256; operators keep the corresponding ``<sha256>.dem`` outside Git.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256

GOLDEN_CORPUS_SCHEMA_VERSION = "1.0.0"
GOLDEN_CORPUS_RULE_VERSION = "golden_corpus_readiness_v1"
GOLDEN_EVALUATION_SCHEMA_VERSION = "1.0.0"
GOLDEN_EVALUATION_RULE_VERSION = "finding_classification_metrics_v1"


class GoldenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DemoSource(StrEnum):
    FACEIT = "faceit"
    VALVE = "valve"
    GOTV_HLTV = "gotv_hltv"
    POV = "pov"
    UNKNOWN = "unknown"


class CaseReviewStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ExpectedParseStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    REJECTED = "rejected"


class CorpusEdgeCase(StrEnum):
    OVERTIME = "overtime"
    SUBSTITUTION = "substitution"
    MISSING_STEAM_ID = "missing_steam_id"
    DAMAGED_DEMO = "damaged_demo"
    INCOMPLETE_DEMO = "incomplete_demo"
    SIDE_SWITCH = "side_switch"
    SIMULTANEOUS_DEATHS = "simultaneous_deaths"
    VICTIMLESS_DEATH = "victimless_death"


class ParserCompatibilityStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    NOT_TESTED = "not_tested"


class FindingLabelValue(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    INDETERMINATE = "indeterminate"


class PredictionValue(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


class CorpusReadinessStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class CorpusCaseRunStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class CorpusIssueSeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


class CorpusIssueCode(StrEnum):
    TARGET_OPPONENT_UNKNOWN = "target_opponent_unknown"
    CONFIRMED_MATCHES_BELOW_MINIMUM = "confirmed_matches_below_minimum"
    OPPONENT_MISMATCH = "opponent_mismatch"
    MAP_COVERAGE_INCOMPLETE = "map_coverage_incomplete"
    SOURCE_COVERAGE_INCOMPLETE = "source_coverage_incomplete"
    EDGE_CASE_COVERAGE_INCOMPLETE = "edge_case_coverage_incomplete"
    FINDING_LABELS_INCOMPLETE = "finding_labels_incomplete"
    PARSER_MATRIX_INCOMPLETE = "parser_matrix_incomplete"
    DEMO_ROOT_NOT_CHECKED = "demo_root_not_checked"
    DEMO_FILE_MISSING = "demo_file_missing"
    DEMO_HASH_MISMATCH = "demo_hash_mismatch"


class ExpectedMatchFacts(GoldenModel):
    """Facts copied from a reviewed canonical run; unknown values stay ``None``."""

    match_id: UUID | None = None
    dataset_fingerprint: Sha256 | None = None
    map_name: str | None = Field(default=None, pattern=r"^de_[a-z0-9_]+$")
    round_count: int | None = Field(default=None, ge=0)
    complete_round_count: int | None = Field(default=None, ge=0)
    incomplete_round_count: int | None = Field(default=None, ge=0)
    canonical_schema_version: str | None = None
    normalization_rule_version: str | None = None

    @model_validator(mode="after")
    def validate_round_counts(self) -> ExpectedMatchFacts:
        if (
            self.round_count is not None
            and self.complete_round_count is not None
            and self.incomplete_round_count is not None
            and self.complete_round_count + self.incomplete_round_count != self.round_count
        ):
            raise ValueError("complete and incomplete round counts must equal round_count")
        return self


class GoldenDemoCase(GoldenModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    demo_sha256: Sha256
    source: DemoSource
    review_status: CaseReviewStatus = CaseReviewStatus.CANDIDATE
    expected_parse_status: ExpectedParseStatus
    opponent_id: str | None = Field(default=None, min_length=1, max_length=200)
    opponent_confirmed: bool = False
    expected: ExpectedMatchFacts = ExpectedMatchFacts()
    edge_cases: tuple[CorpusEdgeCase, ...] = ()
    reviewed_at: datetime | None = None
    reviewed_by_role: str | None = Field(default=None, min_length=1, max_length=100)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_review_provenance(self) -> GoldenDemoCase:
        if self.reviewed_at is not None and not _timezone_aware(self.reviewed_at):
            raise ValueError("reviewed_at must include a timezone")
        if self.opponent_confirmed and self.opponent_id is None:
            raise ValueError("opponent_confirmed requires opponent_id")
        if self.review_status is CaseReviewStatus.CONFIRMED and (
            self.reviewed_at is None or self.reviewed_by_role is None
        ):
            raise ValueError("confirmed cases require review timestamp and reviewer role")
        if self.source is DemoSource.UNKNOWN and not self.limitations:
            raise ValueError("unknown demo source requires a limitation")
        return self


class ParserRequirement(GoldenModel):
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)


class GoldenCorpusPolicy(GoldenModel):
    minimum_confirmed_opponent_matches: int = Field(default=20, ge=1)
    minimum_distinct_opponent_maps: int = Field(default=3, ge=1)
    minimum_determinate_finding_labels: int = Field(default=2, ge=1)
    minimum_positive_finding_labels: int = Field(default=1, ge=0)
    minimum_negative_finding_labels: int = Field(default=1, ge=0)
    required_sources: tuple[DemoSource, ...] = (
        DemoSource.FACEIT,
        DemoSource.VALVE,
        DemoSource.GOTV_HLTV,
        DemoSource.POV,
    )
    required_edge_cases: tuple[CorpusEdgeCase, ...] = (
        CorpusEdgeCase.OVERTIME,
        CorpusEdgeCase.SUBSTITUTION,
        CorpusEdgeCase.MISSING_STEAM_ID,
        CorpusEdgeCase.DAMAGED_DEMO,
        CorpusEdgeCase.INCOMPLETE_DEMO,
    )
    required_parsers: tuple[ParserRequirement, ...] = (
        ParserRequirement(parser_name="demoparser2", parser_version="0.41.4"),
    )

    @model_validator(mode="after")
    def validate_label_minimums(self) -> GoldenCorpusPolicy:
        if self.minimum_determinate_finding_labels < (
            self.minimum_positive_finding_labels + self.minimum_negative_finding_labels
        ):
            raise ValueError(
                "determinate finding minimum cannot be below positive plus negative minimums"
            )
        return self


class GoldenEvidenceReference(GoldenModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    match_id: UUID
    round_number: int | None = Field(default=None, ge=1)
    tick: int | None = Field(default=None, ge=0)
    event_id: UUID | None = None


class GoldenFindingLabel(GoldenModel):
    label_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.:-]{2,127}$")
    finding_key: str = Field(min_length=1, max_length=200)
    value: FindingLabelValue
    evidence_references: tuple[GoldenEvidenceReference, ...] = ()
    reviewed_at: datetime
    reviewed_by_role: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_positive_evidence(self) -> GoldenFindingLabel:
        if not _timezone_aware(self.reviewed_at):
            raise ValueError("reviewed_at must include a timezone")
        if self.value is FindingLabelValue.PRESENT and not self.evidence_references:
            raise ValueError("present finding labels require evidence references")
        if self.value is FindingLabelValue.INDETERMINATE and not self.limitations:
            raise ValueError("indeterminate finding labels require limitations")
        return self


class ParserCompatibilityRecord(GoldenModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    status: ParserCompatibilityStatus
    checked_at: datetime
    observed_dataset_fingerprint: Sha256 | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_partial_limitations(self) -> ParserCompatibilityRecord:
        if not _timezone_aware(self.checked_at):
            raise ValueError("checked_at must include a timezone")
        if (
            self.status
            in {
                ParserCompatibilityStatus.PARTIAL,
                ParserCompatibilityStatus.UNSUPPORTED,
                ParserCompatibilityStatus.NOT_TESTED,
            }
            and not self.limitations
        ):
            raise ValueError("non-supported compatibility records require limitations")
        return self


class GoldenCorpusManifest(GoldenModel):
    schema_version: str = GOLDEN_CORPUS_SCHEMA_VERSION
    corpus_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    corpus_version: str = Field(min_length=1)
    target_opponent_id: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: datetime
    updated_at: datetime
    policy: GoldenCorpusPolicy = GoldenCorpusPolicy()
    cases: tuple[GoldenDemoCase, ...] = ()
    finding_labels: tuple[GoldenFindingLabel, ...] = ()
    parser_compatibility: tuple[ParserCompatibilityRecord, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> GoldenCorpusManifest:
        if not _timezone_aware(self.created_at) or not _timezone_aware(self.updated_at):
            raise ValueError("manifest timestamps must include a timezone")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        case_ids = [item.case_id for item in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id values must be unique")
        hashes = [item.demo_sha256 for item in self.cases]
        if len(hashes) != len(set(hashes)):
            raise ValueError("demo_sha256 values must be unique")
        label_ids = [item.label_id for item in self.finding_labels]
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("label_id values must be unique")
        known_cases = set(case_ids)
        cases_by_id = {item.case_id: item for item in self.cases}
        referenced_cases = {
            reference.case_id
            for label in self.finding_labels
            for reference in label.evidence_references
        } | {item.case_id for item in self.parser_compatibility}
        unknown_cases = referenced_cases - known_cases
        if unknown_cases:
            raise ValueError(f"manifest references unknown cases: {sorted(unknown_cases)}")
        for label in self.finding_labels:
            for reference in label.evidence_references:
                expected_match = cases_by_id[reference.case_id].expected.match_id
                if expected_match is not None and reference.match_id != expected_match:
                    raise ValueError(f"evidence match_id disagrees with case {reference.case_id}")
        compatibility_keys = [
            (item.case_id, item.parser_name, item.parser_version)
            for item in self.parser_compatibility
        ]
        if len(compatibility_keys) != len(set(compatibility_keys)):
            raise ValueError("parser compatibility keys must be unique")
        for record in self.parser_compatibility:
            expected_fingerprint = cases_by_id[record.case_id].expected.dataset_fingerprint
            if (
                expected_fingerprint is not None
                and record.observed_dataset_fingerprint is not None
                and record.observed_dataset_fingerprint != expected_fingerprint
            ):
                raise ValueError(f"parser fingerprint disagrees with case {record.case_id}")
        return self


class CorpusIssue(GoldenModel):
    code: CorpusIssueCode
    severity: CorpusIssueSeverity
    message: str = Field(min_length=1)
    affected_case_ids: tuple[str, ...] = ()


class DemoFileCheck(GoldenModel):
    case_id: str
    path: str | None = None
    exists: bool | None = None
    sha256_matches: bool | None = None


class GoldenCorpusCoverage(GoldenModel):
    total_cases: int = Field(ge=0)
    confirmed_cases: int = Field(ge=0)
    candidate_cases: int = Field(ge=0)
    rejected_cases: int = Field(ge=0)
    confirmed_opponent_matches: int = Field(ge=0)
    distinct_opponent_maps: tuple[str, ...] = ()
    confirmed_sources: tuple[DemoSource, ...] = ()
    confirmed_edge_cases: tuple[CorpusEdgeCase, ...] = ()
    determinate_finding_labels: int = Field(ge=0)
    positive_finding_labels: int = Field(ge=0)
    negative_finding_labels: int = Field(ge=0)
    parser_matrix_records: int = Field(ge=0)
    checked_demo_files: int = Field(ge=0)
    valid_demo_files: int = Field(ge=0)


class GoldenCorpusAudit(GoldenModel):
    schema_version: str = GOLDEN_CORPUS_SCHEMA_VERSION
    rule_version: str = GOLDEN_CORPUS_RULE_VERSION
    manifest_fingerprint: Sha256
    corpus_id: str
    corpus_version: str
    status: CorpusReadinessStatus
    coverage: GoldenCorpusCoverage
    issues: tuple[CorpusIssue, ...]
    file_checks: tuple[DemoFileCheck, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> GoldenCorpusAudit:
        expected = (
            CorpusReadinessStatus.BLOCKED
            if any(item.severity is CorpusIssueSeverity.BLOCKER for item in self.issues)
            else CorpusReadinessStatus.READY
        )
        if self.status is not expected:
            raise ValueError("corpus status does not match blocker issues")
        return self


class GoldenCaseRunResult(GoldenModel):
    case_id: str
    status: CorpusCaseRunStatus
    expected_parse_status: ExpectedParseStatus
    observed: ExpectedMatchFacts | None = None
    mismatches: tuple[str, ...] = ()
    parser_error_code: str | None = None


class GoldenCorpusRunReport(GoldenModel):
    schema_version: str = GOLDEN_CORPUS_SCHEMA_VERSION
    manifest_fingerprint: Sha256
    parser_name: str
    parser_version: str
    selected_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    unavailable_cases: int = Field(ge=0)
    complete: bool
    passed: bool
    results: tuple[GoldenCaseRunResult, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> GoldenCorpusRunReport:
        if (
            self.passed_cases + self.failed_cases + self.unavailable_cases != self.selected_cases
            or len(self.results) != self.selected_cases
        ):
            raise ValueError("Golden Corpus run counts do not match results")
        expected_complete = self.selected_cases > 0 and self.unavailable_cases == 0
        if self.complete != expected_complete:
            raise ValueError("Golden Corpus run completeness does not match results")
        if self.passed != (self.complete and self.failed_cases == 0):
            raise ValueError("Golden Corpus run pass state does not match results")
        return self


class GoldenFindingPrediction(GoldenModel):
    label_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.:-]{2,127}$")
    value: PredictionValue


class GoldenPredictionSet(GoldenModel):
    schema_version: str = GOLDEN_EVALUATION_SCHEMA_VERSION
    manifest_fingerprint: Sha256
    algorithm_version: str = Field(min_length=1)
    predictions: tuple[GoldenFindingPrediction, ...]

    @model_validator(mode="after")
    def validate_unique_predictions(self) -> GoldenPredictionSet:
        label_ids = [item.label_id for item in self.predictions]
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("prediction label_id values must be unique")
        return self


class FindingClassificationMetrics(GoldenModel):
    sample_size: int = Field(ge=0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    f1: float | None = Field(default=None, ge=0.0, le=1.0)


class GoldenEvaluationReport(GoldenModel):
    schema_version: str = GOLDEN_EVALUATION_SCHEMA_VERSION
    rule_version: str = GOLDEN_EVALUATION_RULE_VERSION
    manifest_fingerprint: Sha256
    algorithm_version: str
    complete: bool
    metrics: FindingClassificationMetrics
    indeterminate_label_ids: tuple[str, ...] = ()
    unavailable_prediction_ids: tuple[str, ...] = ()
    missing_prediction_ids: tuple[str, ...] = ()
    unknown_prediction_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def _timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = [name for name in globals() if not name.startswith("_")]
