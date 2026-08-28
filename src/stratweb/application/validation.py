"""Independent validation rules for canonical match datasets."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue

from stratweb.application.canonical_models import (
    NORMALIZATION_RULE_VERSION,
    CanonicalBlind,
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalMatch,
    CanonicalPlayer,
    CanonicalRound,
    CanonicalShot,
    CanonicalTeam,
    PlayerTeamMembership,
    ResultCapabilities,
    ResultCapability,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)

CanonicalEvent = (
    CanonicalKill
    | CanonicalDamage
    | CanonicalShot
    | CanonicalGrenade
    | CanonicalBlind
    | CanonicalBombEvent
)


@dataclass(frozen=True, slots=True)
class ValidationInput:
    match: CanonicalMatch
    teams: tuple[CanonicalTeam, ...]
    players: tuple[CanonicalPlayer, ...]
    memberships: tuple[PlayerTeamMembership, ...]
    rounds: tuple[CanonicalRound, ...]
    events: tuple[CanonicalEvent, ...]
    result_capabilities: ResultCapabilities | None = None
    preprocessing_issues: tuple[ValidationIssue, ...] = ()


class CanonicalDatasetValidator:
    """Validate integrity; only structural ambiguity is fatal.

    Fatal errors are overlapping/invalid round windows, broken references,
    negative canonical ticks, duplicate IDs, or unstable event ordering. Malformed
    source rows omitted with an issue remain non-fatal.
    """

    def validate(self, data: ValidationInput) -> ValidationReport:
        issues = list(data.preprocessing_issues)
        issues.extend(self._round_issues(data.rounds))
        issues.extend(self._event_issues(data.rounds, data.events))
        issues.extend(self._reference_issues(data))
        issues.extend(self._dataset_quality_issues(data))
        if data.result_capabilities is not None:
            issues.extend(result_availability_issues(data.result_capabilities))
        issues = sorted(
            issues,
            key=lambda item: (
                item.severity.value,
                item.code,
                item.entity_type,
                item.entity_id or "",
            ),
        )
        counts = Counter(issue.severity for issue in issues)
        fatal_count = sum(issue.is_fatal for issue in issues)
        error_count = counts[ValidationSeverity.ERROR]
        unassigned = sum(event.round_id is None for event in data.events)
        unknown_players = sum(player.steam_id is None for player in data.players)
        incomplete = sum(not round_item.is_complete for round_item in data.rounds)
        return ValidationReport(
            is_valid=error_count == 0,
            has_fatal_errors=fatal_count > 0,
            fatal_error_count=fatal_count,
            issue_counts={severity: counts[severity] for severity in ValidationSeverity},
            unassigned_event_count=unassigned,
            unknown_player_count=unknown_players,
            incomplete_round_count=incomplete,
            issues=tuple(issues),
        )

    def _round_issues(self, rounds: tuple[CanonicalRound, ...]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        ordered = sorted(rounds, key=lambda item: item.round_number)
        for index, round_item in enumerate(ordered):
            boundaries = [
                tick
                for tick in (
                    round_item.start_tick,
                    round_item.freeze_end_tick,
                    round_item.end_tick,
                    round_item.official_end_tick,
                )
                if tick is not None
            ]
            if any(tick < 0 for tick in boundaries):
                issues.append(_issue("negative_round_tick", "round", round_item.round_id, True))
            if boundaries != sorted(boundaries):
                issues.append(
                    _issue(
                        "round_boundaries_not_monotonic",
                        "round",
                        round_item.round_id,
                        True,
                        evidence={"round_number": round_item.round_number},
                    )
                )
            if index + 1 < len(ordered):
                next_round = ordered[index + 1]
                if (
                    round_item.end_tick is not None
                    and next_round.start_tick is not None
                    and round_item.end_tick > next_round.start_tick
                ):
                    issues.append(
                        _issue(
                            "rounds_overlap",
                            "round",
                            round_item.round_id,
                            True,
                            evidence={
                                "end_tick": round_item.end_tick,
                                "next_start_tick": next_round.start_tick,
                            },
                        )
                    )
        return issues

    def _event_issues(
        self,
        rounds: tuple[CanonicalRound, ...],
        events: tuple[CanonicalEvent, ...],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        round_by_id = {item.round_id: item for item in rounds}
        ordered_rounds = sorted(rounds, key=lambda item: item.round_number)
        next_start = {
            item.round_id: ordered_rounds[index + 1].start_tick
            if index + 1 < len(ordered_rounds)
            else None
            for index, item in enumerate(ordered_rounds)
        }

        ids = [event.event_id for event in events]
        for event_id, count in Counter(ids).items():
            if count > 1:
                issues.append(_issue("duplicate_event_id", "event", event_id, True))

        if list(events) != sorted(events, key=lambda item: (item.tick, str(item.event_id))):
            issues.append(_issue("events_not_sorted", "dataset", None, True))

        for event in events:
            if event.tick < 0:
                issues.append(_issue("negative_event_tick", "event", event.event_id, True))
            if event.round_id is None:
                continue
            round_item = round_by_id.get(event.round_id)
            if round_item is None:
                continue
            upper = next_start[round_item.round_id]
            outside = round_item.start_tick is None or event.tick < round_item.start_tick
            if upper is not None and event.tick >= upper:
                outside = True
            if outside:
                issues.append(
                    _issue(
                        "assigned_event_outside_round_window",
                        "event",
                        event.event_id,
                        False,
                        severity=ValidationSeverity.ERROR,
                        evidence={"tick": event.tick, "round_number": round_item.round_number},
                    )
                )
        return issues

    def _reference_issues(self, data: ValidationInput) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        player_ids = {player.player_id for player in data.players}
        team_ids = {team.team_id for team in data.teams}
        round_ids = {round_item.round_id for round_item in data.rounds}

        for membership in data.memberships:
            if membership.player_id not in player_ids:
                issues.append(_issue("unknown_player_reference", "membership", None, True))
            if membership.team_id is not None and membership.team_id not in team_ids:
                issues.append(_issue("unknown_team_reference", "membership", None, True))

        for round_item in data.rounds:
            for team_id in (round_item.t_team_id, round_item.ct_team_id):
                if team_id is not None and team_id not in team_ids:
                    issues.append(
                        _issue("unknown_team_reference", "round", round_item.round_id, True)
                    )

        for event in data.events:
            if event.round_id is not None and event.round_id not in round_ids:
                issues.append(_issue("unknown_round_reference", "event", event.event_id, True))
            for player_id in _event_player_ids(event):
                if player_id is not None and player_id not in player_ids:
                    issues.append(_issue("unknown_player_reference", "event", event.event_id, True))
            for team_id in _event_team_ids(event):
                if team_id is not None and team_id not in team_ids:
                    issues.append(_issue("unknown_team_reference", "event", event.event_id, True))
        return issues

    def _dataset_quality_issues(self, data: ValidationInput) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        player_count = len(data.players)
        if player_count < 2 or player_count > 64:
            issues.append(
                _issue(
                    "implausible_player_count",
                    "dataset",
                    None,
                    False,
                    evidence={"player_count": player_count},
                )
            )
        unassigned = sum(event.round_id is None for event in data.events)
        if unassigned:
            issues.append(
                _issue(
                    "unassigned_events",
                    "dataset",
                    None,
                    False,
                    evidence={"count": unassigned},
                )
            )
        unknown = sum(player.steam_id is None for player in data.players)
        if unknown:
            issues.append(
                _issue(
                    "unknown_players",
                    "dataset",
                    None,
                    False,
                    evidence={"count": unknown},
                )
            )
        incomplete = [item for item in data.rounds if not item.is_complete]
        if incomplete:
            issues.append(
                _issue(
                    "incomplete_rounds",
                    "dataset",
                    None,
                    False,
                    evidence={"count": len(incomplete)},
                )
            )
        if data.match.round_count_disagreement:
            issues.append(_issue("round_count_disagreement", "match", data.match.match_id, False))
        if data.rounds and data.rounds[-1].official_end_tick is None:
            issues.append(
                _issue("missing_final_round_end", "round", data.rounds[-1].round_id, False)
            )
        uncertain = sum(
            round_item.t_team_id is None or round_item.ct_team_id is None
            for round_item in data.rounds
        )
        if uncertain:
            issues.append(
                _issue(
                    "side_resolution_uncertainty",
                    "dataset",
                    None,
                    False,
                    evidence={"round_count": uncertain},
                )
            )
        return issues


def _event_player_ids(event: CanonicalEvent) -> tuple[UUID | None, ...]:
    if isinstance(event, CanonicalKill):
        return (event.attacker_player_id, event.victim_player_id, event.assister_player_id)
    if isinstance(event, CanonicalDamage):
        return (event.attacker_player_id, event.victim_player_id)
    if isinstance(event, CanonicalBlind):
        return (event.attacker_player_id, event.victim_player_id)
    return (event.player_id,)


def _event_team_ids(event: CanonicalEvent) -> tuple[UUID | None, ...]:
    if isinstance(event, (CanonicalKill, CanonicalDamage, CanonicalBlind)):
        return (event.attacker_team_id, event.victim_team_id)
    return (event.team_id,)


def _issue(
    code: str,
    entity_type: str,
    entity_id: UUID | None,
    fatal: bool,
    *,
    severity: ValidationSeverity = ValidationSeverity.WARNING,
    evidence: dict[str, JsonValue] | None = None,
) -> ValidationIssue:
    if fatal:
        severity = ValidationSeverity.ERROR
    return ValidationIssue(
        code=code,
        severity=severity,
        is_fatal=fatal,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        message=code.replace("_", " ").capitalize() + ".",
        evidence=evidence or {},
        rule_version=NORMALIZATION_RULE_VERSION,
    )


def result_availability_issues(
    capabilities: ResultCapabilities,
) -> tuple[ValidationIssue, ...]:
    """Create at most one aggregate issue for each result capability."""

    issues: list[ValidationIssue] = []
    winner = capabilities.round_winner
    if winner.rounds_available < winner.total_round_count:
        if winner.rounds_unresolved:
            code = "round_outcome_conflict"
            severity = ValidationSeverity.ERROR
        elif winner.rounds_available:
            code = "partial_round_outcome_coverage"
            severity = ValidationSeverity.WARNING
        else:
            code = "round_winner_unavailable"
            severity = ValidationSeverity.INFO
        issues.append(_availability_issue(code, severity, "round_winner", winner))

    score = capabilities.round_score
    if score.rounds_available < score.total_round_count:
        if score.rounds_unresolved:
            severity = ValidationSeverity.ERROR
        elif score.rounds_available:
            severity = ValidationSeverity.WARNING
        else:
            severity = ValidationSeverity.INFO
        issues.append(
            _availability_issue("round_score_unavailable", severity, "round_score", score)
        )

    reason = capabilities.round_end_reason
    if reason.rounds_available < reason.total_round_count:
        if reason.rounds_unresolved:
            severity = ValidationSeverity.ERROR
        elif reason.rounds_available:
            severity = ValidationSeverity.WARNING
        else:
            severity = ValidationSeverity.INFO
        issues.append(
            _availability_issue(
                "round_end_reason_unavailable",
                severity,
                "round_end_reason",
                reason,
            )
        )
    return tuple(issues)


def _availability_issue(
    code: str,
    severity: ValidationSeverity,
    entity_type: str,
    capability: ResultCapability,
) -> ValidationIssue:
    affected = capability.total_round_count - capability.rounds_available
    return _issue(
        code,
        entity_type,
        None,
        False,
        severity=severity,
        evidence={
            "affected_round_count": affected,
            "total_round_count": capability.total_round_count,
            "checked_sources": list(capability.source_events_checked),
            "detected_fields": list(capability.detected_fields),
            "availability_classification": capability.status.value,
        },
    )
