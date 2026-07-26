"""Application use cases for importing and querying canonical match datasets."""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from uuid import UUID

from pydantic import ValidationError

from stratweb.application.canonical_models import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalMatchDataset,
    CanonicalPlayer,
    CanonicalRound,
    DataAvailability,
    ResultCapability,
    RoundOutcomeStatus,
    ValidationIssue,
    ValidationSeverity,
)
from stratweb.application.canonical_upgrade import (
    LEGACY_CANONICAL_SCHEMA_VERSION,
    upgrade_v1_payload,
)
from stratweb.application.canonicalization import compute_dataset_fingerprint
from stratweb.application.persistence_models import (
    ImportResult,
    ImportStatus,
    MatchImportSummary,
    MatchQueryFilters,
    RoundDetails,
    RoundEvents,
    StoredMatch,
)
from stratweb.application.validation import (
    CanonicalDatasetValidator,
    CanonicalEvent,
    ValidationInput,
)
from stratweb.config import get_settings
from stratweb.exceptions import (
    CanonicalImportError,
    CanonicalSchemaVersionError,
    DatasetFingerprintMismatchError,
    DatasetIntegrityError,
    FatalValidationError,
    MatchNotFoundError,
    PersistenceError,
)
from stratweb.ports import MatchRepository

DEFAULT_DATABASE_PATH = Path("data/stratweb.duckdb")
DATABASE_PATH_ENV = "STRATWEB_DUCKDB_PATH"


def resolve_database_path(
    cli_path: str | Path | None,
    *,
    environ: Mapping[str, str] | None = None,
    default: Path = DEFAULT_DATABASE_PATH,
) -> Path:
    """Resolve CLI > environment > default precedence without creating anything."""

    values = os.environ if environ is None else environ
    configured = values.get(DATABASE_PATH_ENV)
    if environ is None and configured is None:
        configured = str(get_settings().duckdb_path)
    selected = cli_path or configured or default
    return Path(selected).expanduser().resolve()


def load_canonical_dataset(path: str | Path) -> CanonicalMatchDataset:
    """Validate a canonical JSON artifact without trusting any embedded summary."""

    candidate = Path(path).expanduser().resolve()
    try:
        payload = candidate.read_text(encoding="utf-8")
    except OSError as exc:
        raise CanonicalImportError(f"Could not read canonical JSON: {candidate}") from exc
    try:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise CanonicalImportError("Canonical JSON root must be an object.")
        schema_version = decoded.get("schema_version")
        if schema_version == LEGACY_CANONICAL_SCHEMA_VERSION:
            return upgrade_v1_payload(decoded)
        if schema_version != CANONICAL_SCHEMA_VERSION:
            raise CanonicalSchemaVersionError(
                f"Unsupported canonical schema {schema_version!r}; "
                f"expected {CANONICAL_SCHEMA_VERSION!r}."
            )
        return CanonicalMatchDataset.model_validate(decoded)
    except json.JSONDecodeError as exc:
        raise CanonicalImportError(f"Canonical JSON is not valid JSON: {exc}") from exc
    except ValidationError as exc:
        raise CanonicalImportError(
            f"Canonical JSON does not match its declared schema: {exc}"
        ) from exc


class ImportCanonicalMatchService:
    """Validate then atomically import one CanonicalMatchDataset."""

    def __init__(self, repository: MatchRepository) -> None:
        self._repository = repository

    def import_dataset(
        self,
        dataset: CanonicalMatchDataset,
        *,
        source_original_name: str | None = None,
        replace: bool = False,
    ) -> ImportResult:
        started = perf_counter()
        validate_import_dataset(dataset)
        warnings = _import_warnings(dataset)
        try:
            saved = self._repository.save_match(
                dataset,
                source_original_name=_metadata_filename(source_original_name),
                replace=replace,
            )
        except PersistenceError as exc:
            return ImportResult(
                match_id=dataset.match.match_id,
                dataset_fingerprint=dataset.dataset_fingerprint,
                status=ImportStatus.FAILED,
                warnings=(*warnings, str(exc)),
                duration_seconds=perf_counter() - started,
                database_path=self._repository.database_path,
            )
        return ImportResult(
            match_id=saved.match_id,
            dataset_fingerprint=saved.dataset_fingerprint,
            status=saved.status,
            row_counts=saved.row_counts,
            warnings=warnings,
            duration_seconds=perf_counter() - started,
            database_path=self._repository.database_path,
        )

    def import_canonical_json(
        self,
        path: str | Path,
        *,
        replace: bool = False,
    ) -> ImportResult:
        dataset = load_canonical_dataset(path)
        return self.import_dataset(dataset, replace=replace)


class MatchQueryService:
    """Read-only application facade over the MatchRepository port."""

    def __init__(self, repository: MatchRepository) -> None:
        self._repository = repository

    def list_matches(self, filters: MatchQueryFilters | None = None) -> tuple[StoredMatch, ...]:
        return self._repository.list_matches(filters or MatchQueryFilters())

    def get_match(self, match_id: UUID) -> StoredMatch:
        match = self._repository.get_match(match_id)
        if match is None:
            raise MatchNotFoundError(f"Match not found: {match_id}")
        return match

    def get_summary(self, match_id: UUID) -> MatchImportSummary:
        summary = self._repository.get_import_summary(match_id)
        if summary is None:
            raise MatchNotFoundError(f"Match not found: {match_id}")
        return summary

    def get_players(self, match_id: UUID) -> tuple[CanonicalPlayer, ...]:
        self.get_match(match_id)
        return self._repository.get_players(match_id)

    def get_rounds(self, match_id: UUID) -> tuple[CanonicalRound, ...]:
        self.get_match(match_id)
        return self._repository.get_rounds(match_id)

    def get_round_events(self, match_id: UUID, round_number: int) -> RoundEvents:
        self.get_match(match_id)
        events = self._repository.get_round_events(match_id, round_number)
        if events is None:
            raise MatchNotFoundError(f"Round {round_number} was not found for match {match_id}.")
        return events

    def get_round_details(self, match_id: UUID, round_number: int) -> RoundDetails:
        round_item = next(
            (item for item in self.get_rounds(match_id) if item.round_number == round_number),
            None,
        )
        if round_item is None:
            raise MatchNotFoundError(f"Round {round_number} was not found for match {match_id}.")
        return RoundDetails(
            round=round_item,
            events=self.get_round_events(match_id, round_number),
        )

    def get_player_kills(self, match_id: UUID, player_id: UUID) -> tuple[CanonicalKill, ...]:
        self.get_match(match_id)
        return self._repository.get_player_kills(match_id, player_id)

    def get_player_grenades(self, match_id: UUID, player_id: UUID) -> tuple[CanonicalGrenade, ...]:
        self.get_match(match_id)
        return self._repository.get_player_grenades(match_id, player_id)

    def get_validation_issues(self, match_id: UUID) -> tuple[ValidationIssue, ...]:
        self.get_match(match_id)
        return self._repository.get_validation_issues(match_id)

    def get_table_counts(self, match_id: UUID) -> dict[str, int]:
        self.get_match(match_id)
        return self._repository.get_table_counts(match_id)

    def delete_match(self, match_id: UUID) -> bool:
        return self._repository.delete_match(match_id)


def validate_import_dataset(dataset: CanonicalMatchDataset) -> None:
    if dataset.schema_version != CANONICAL_SCHEMA_VERSION:
        raise CanonicalSchemaVersionError(
            f"Unsupported canonical schema {dataset.schema_version!r}; "
            f"expected {CANONICAL_SCHEMA_VERSION!r}."
        )
    if dataset.normalization_metadata.canonical_schema_version != dataset.schema_version:
        raise CanonicalSchemaVersionError(
            "Dataset and normalization metadata canonical schema versions differ."
        )
    recalculated = compute_dataset_fingerprint(dataset)
    if recalculated != dataset.dataset_fingerprint:
        raise DatasetFingerprintMismatchError(
            "Canonical dataset fingerprint does not match its content."
        )
    report = dataset.validation_report
    fatal_issues = tuple(issue for issue in report.issues if issue.is_fatal)
    if report.has_fatal_errors or report.fatal_error_count or fatal_issues:
        raise FatalValidationError(
            f"Canonical dataset contains {max(report.fatal_error_count, len(fatal_issues))} "
            "fatal validation issue(s)."
        )
    _verify_contract_counts(dataset)
    _verify_result_capabilities(dataset)
    _verify_identifiers_and_references(dataset)

    all_events: tuple[CanonicalEvent, ...] = tuple(
        sorted(
            (
                *dataset.kills,
                *dataset.damages,
                *dataset.shots,
                *dataset.grenades,
                *dataset.bomb_events,
            ),
            key=lambda event: (event.tick, str(event.event_id)),
        )
    )
    fresh = CanonicalDatasetValidator().validate(
        ValidationInput(
            match=dataset.match,
            teams=dataset.teams,
            players=dataset.players,
            memberships=dataset.player_team_memberships,
            rounds=dataset.rounds,
            events=all_events,
            result_capabilities=dataset.normalization_metadata.result_capabilities,
        )
    )
    if fresh.has_fatal_errors:
        codes = ", ".join(issue.code for issue in fresh.issues if issue.is_fatal)
        raise DatasetIntegrityError(f"Independent validation failed: {codes}.")


def _verify_contract_counts(dataset: CanonicalMatchDataset) -> None:
    match = dataset.match
    actual_complete = sum(round_item.is_complete for round_item in dataset.rounds)
    if match.round_count != len(dataset.rounds):
        raise DatasetIntegrityError("match.round_count does not equal the round row count.")
    if match.complete_round_count != actual_complete:
        raise DatasetIntegrityError("match.complete_round_count is inconsistent.")
    if match.incomplete_round_count != len(dataset.rounds) - actual_complete:
        raise DatasetIntegrityError("match.incomplete_round_count is inconsistent.")
    report = dataset.validation_report
    issue_counts = Counter(issue.severity for issue in report.issues)
    expected_counts = {severity: issue_counts[severity] for severity in ValidationSeverity}
    if report.issue_counts != expected_counts:
        raise DatasetIntegrityError("validation_report.issue_counts is inconsistent.")
    if report.fatal_error_count != sum(issue.is_fatal for issue in report.issues):
        raise DatasetIntegrityError("validation_report.fatal_error_count is inconsistent.")
    if report.incomplete_round_count != len(dataset.rounds) - actual_complete:
        raise DatasetIntegrityError("validation_report.incomplete_round_count is inconsistent.")
    events = (
        *dataset.kills,
        *dataset.damages,
        *dataset.shots,
        *dataset.grenades,
        *dataset.bomb_events,
    )
    if report.unassigned_event_count != sum(event.round_id is None for event in events):
        raise DatasetIntegrityError("validation_report.unassigned_event_count is inconsistent.")
    if report.unknown_player_count != sum(player.steam_id is None for player in dataset.players):
        raise DatasetIntegrityError("validation_report.unknown_player_count is inconsistent.")
    has_errors = any(issue.severity is ValidationSeverity.ERROR for issue in report.issues)
    if report.is_valid == has_errors:
        raise DatasetIntegrityError("validation_report.is_valid is inconsistent.")
    if report.has_fatal_errors != (report.fatal_error_count > 0):
        raise DatasetIntegrityError("validation_report.has_fatal_errors is inconsistent.")


def _verify_identifiers_and_references(dataset: CanonicalMatchDataset) -> None:
    match_id = dataset.match.match_id
    team_ids = {team.team_id for team in dataset.teams}
    player_ids = {player.player_id for player in dataset.players}
    _require_unique("team IDs", [team.team_id for team in dataset.teams])
    _require_unique("player IDs", [player.player_id for player in dataset.players])
    _require_unique("round IDs", [round_item.round_id for round_item in dataset.rounds])
    _require_unique("round numbers", [round_item.round_number for round_item in dataset.rounds])
    membership_keys = [
        (
            membership.player_id,
            membership.side,
            membership.valid_from_tick,
        )
        for membership in dataset.player_team_memberships
    ]
    _require_unique("membership keys", membership_keys)
    events = (
        *dataset.kills,
        *dataset.damages,
        *dataset.shots,
        *dataset.grenades,
        *dataset.bomb_events,
    )
    _require_unique("event IDs", [event.event_id for event in events])
    for team in dataset.teams:
        if team.match_id != match_id:
            raise DatasetIntegrityError("A team references a different match_id.")
        if any(player_id not in player_ids for player_id in team.starting_player_ids):
            raise DatasetIntegrityError("A team starting roster references an unknown player.")
    for membership in dataset.player_team_memberships:
        if membership.player_id not in player_ids:
            raise DatasetIntegrityError("A membership references an unknown player.")
        if membership.team_id is not None and membership.team_id not in team_ids:
            raise DatasetIntegrityError("A membership references an unknown team.")
    round_by_id = {round_item.round_id: round_item for round_item in dataset.rounds}
    for round_item in dataset.rounds:
        if round_item.match_id != match_id:
            raise DatasetIntegrityError("A round references a different match_id.")
        for team_id in (round_item.t_team_id, round_item.ct_team_id):
            if team_id is not None and team_id not in team_ids:
                raise DatasetIntegrityError("A round references an unknown team.")
    for event in events:
        if event.match_id != match_id:
            raise DatasetIntegrityError("An event references a different match_id.")
        if event.round_id is None:
            if event.round_number is not None:
                raise DatasetIntegrityError("An unassigned event has a round_number.")
            continue
        referenced_round = round_by_id.get(event.round_id)
        if referenced_round is None:
            raise DatasetIntegrityError("An event references an unknown round.")
        if event.round_number != referenced_round.round_number:
            raise DatasetIntegrityError("An event round_id and round_number disagree.")


def _verify_result_capabilities(dataset: CanonicalMatchDataset) -> None:
    rounds = dataset.rounds
    capabilities = dataset.normalization_metadata.result_capabilities
    winner_available = sum(item.outcome_status.is_available for item in rounds)
    winner_missing = sum(
        item.outcome_status is RoundOutcomeStatus.MISSING_FROM_SOURCE for item in rounds
    )
    _require_capability_counts(
        "round_winner",
        capabilities.round_winner,
        total=len(rounds),
        available=winner_available,
        missing=winner_missing,
        unresolved=len(rounds) - winner_available - winner_missing,
    )
    for label, capability, statuses in (
        ("round_score", capabilities.round_score, tuple(item.score_status for item in rounds)),
        (
            "round_end_reason",
            capabilities.round_end_reason,
            tuple(item.end_reason_status for item in rounds),
        ),
    ):
        available = statuses.count(DataAvailability.AVAILABLE)
        missing = statuses.count(DataAvailability.MISSING_FROM_SOURCE) + statuses.count(
            DataAvailability.NOT_APPLICABLE
        )
        _require_capability_counts(
            label,
            capability,
            total=len(rounds),
            available=available,
            missing=missing,
            unresolved=statuses.count(DataAvailability.UNRESOLVED),
        )


def _require_capability_counts(
    label: str,
    capability: ResultCapability,
    *,
    total: int,
    available: int,
    missing: int,
    unresolved: int,
) -> None:
    actual = (
        capability.total_round_count,
        capability.rounds_available,
        capability.rounds_missing,
        capability.rounds_unresolved,
    )
    expected = (total, available, missing, unresolved)
    if actual != expected:
        raise DatasetIntegrityError(
            f"normalization_metadata.{label} capability counts are inconsistent."
        )


def _require_unique(label: str, values: Sequence[object]) -> None:
    if len(values) != len(set(values)):
        raise DatasetIntegrityError(f"Canonical dataset contains duplicate {label}.")


def _import_warnings(dataset: CanonicalMatchDataset) -> tuple[str, ...]:
    warnings = list(dataset.normalization_metadata.warnings)
    warnings.extend(
        f"validation:{issue.code}: {issue.message}"
        for issue in dataset.validation_report.issues
        if issue.severity is ValidationSeverity.WARNING
    )
    return tuple(dict.fromkeys(warnings))


def _metadata_filename(value: str | None) -> str | None:
    if value is None:
        return None
    filename = value.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return filename or None
