"""Typed presentation contracts for the Stage 8.8 scouting report."""

from __future__ import annotations

from collections import Counter
from urllib.parse import urlencode
from uuid import UUID

from pydantic import Field

from stratweb.application.opponent_models import OpponentSubjectType, OpponentWorkspace
from stratweb.application.opponent_scope import (
    subject_findings,
)
from stratweb.application.scouting_reports import ScoutingReportSource
from stratweb.counter_strategy.models import (
    CounterStrategyRecommendation,
    SkippedStrategyFinding,
)
from stratweb.counter_strategy.validation_models import (
    StrategyAcceptanceStatus,
    ValidationCheckStatus,
)
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.findings.models import AnalysisFinding, EvidenceReference, FindingCategory
from stratweb.patterns.models import PatternType, PlayerPatternValue
from stratweb.readiness.models import FindingReadinessRecord, corpus_reliability
from stratweb.reporting.coach_presentation import coach_pattern_text, is_useful_coach_signal
from stratweb.reporting.links import prefer_smooth_playback
from stratweb.web.view_models.product import ViewModel

REPORT_SCHEMA_VERSION = "1.0.0"
REPORT_VIEW_RULE_VERSION = "scouting_report_view_v2"
COACH_REPORT_RULE_VERSION = "coach_report_projection_v3"
CHEAT_SHEET_SCHEMA_VERSION = "1.0.0"
CHEAT_SHEET_RULE_VERSION = "map_cheat_sheet_v1"


class ScoutingReportFilters(ViewModel):
    map_name: str | None = None
    side: Side | None = None
    buy_type: BuyType | None = None
    pattern_type: PatternType | None = None
    minimum_sample_size: int = Field(default=1, ge=1)
    minimum_confidence: float = Field(default=0, ge=0, le=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=10, le=100)


class ReportCheckView(ViewModel):
    code: str
    label: str
    status: str
    css_class: str
    message: str
    observed: str | None = None
    required: str | None = None


class ReportCorpusMatchView(ViewModel):
    match_id: UUID
    map_name: str
    source_name: str
    team_name: str
    round_count: int = Field(ge=0)
    input_status: str
    href: str


class ReportFindingView(ViewModel):
    finding_id: UUID
    title: str
    observation: str
    category: str
    category_label: str
    pattern_type: str
    pattern_label: str
    value_label: str
    map_name: str
    side: str
    buy_type: str
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency_percent: str
    sample_size: int = Field(ge=1)
    evidence_matches: int = Field(ge=1)
    reliability_tier: str
    reliability_label: str
    reliability_message: str
    confidence_score_percent: str
    confidence_interval: str
    readiness_status: str
    readiness_css_class: str
    readiness_reasons: tuple[str, ...]
    strategy_status: str
    strategy_reason: str
    small_sample_warning: bool
    limitations_count: int = Field(ge=0)
    evidence_count: int = Field(ge=1)
    detail_href: str


class ReportFindingGroupView(ViewModel):
    key: str
    title: str
    subtitle: str
    findings: tuple[ReportFindingView, ...]


class ReportRecommendationView(ViewModel):
    recommendation_id: UUID
    source_finding_id: UUID
    title: str
    category: str
    category_label: str
    rule_id: str
    map_name: str
    side: str
    buy_type: str
    observation: str
    tactical_interpretation: str
    recommended_response: str
    avoid: str
    frequency_percent: str
    ratio: str
    evidence_matches: int = Field(ge=1)
    reliability_tier: str
    reliability_label: str
    reliability_message: str
    confidence_score_percent: str
    detail_href: str


class ReportFilterOptions(ViewModel):
    maps: tuple[str, ...]
    buy_types: tuple[str, ...]
    pattern_types: tuple[tuple[str, str], ...]


class ScoutingReportPageView(ViewModel):
    report_schema_version: str = REPORT_SCHEMA_VERSION
    report_view_rule_version: str = REPORT_VIEW_RULE_VERSION
    profile_id: UUID
    display_name: str
    subject_type: OpponentSubjectType
    target_player_name: str | None = None
    strategy_run_id: UUID
    strategy_fingerprint: str
    source_analysis_run_id: UUID
    validation_id: UUID
    validation_fingerprint: str
    acceptance_status: str
    acceptance_label: str
    acceptance_css_class: str
    acceptance_message: str
    selected_matches: int = Field(ge=0)
    included_matches: int = Field(ge=0)
    required_matches: int = Field(ge=1)
    corpus_reliability_tier: str
    corpus_reliability_label: str
    corpus_reliability_message: str
    corpus_reliability_css_class: str
    source_findings: int = Field(ge=0)
    ready_findings: int = Field(ge=0)
    recommendations_count: int = Field(ge=0)
    recommendations_suppressed: bool
    skipped_findings: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    maps: tuple[str, ...]
    sides: tuple[str, ...]
    buy_types: tuple[str, ...]
    checks: tuple[ReportCheckView, ...]
    warnings: tuple[str, ...]
    filters: ScoutingReportFilters
    filter_options: ReportFilterOptions
    filtered_findings: int = Field(ge=0)
    visible_findings: int = Field(ge=0)
    page: int = Field(ge=1)
    page_count: int = Field(ge=1)
    previous_href: str | None = None
    next_href: str | None = None
    finding_groups: tuple[ReportFindingGroupView, ...]
    recommendations: tuple[ReportRecommendationView, ...]
    corpus_matches: tuple[ReportCorpusMatchView, ...]
    skip_reason_counts: dict[str, int]
    report_json_href: str
    report_export_json_href: str
    report_print_href: str
    report_pdf_href: str


class CoachSignalView(ViewModel):
    """Plain-language projection of one immutable finding."""

    finding: ReportFindingView
    frequency_key: str
    kind_label: str
    plain_title: str
    plain_explanation: str


class CoachReportPageView(ViewModel):
    """Small, deterministic set of signals for the one-tap report flow."""

    rule_version: str = COACH_REPORT_RULE_VERSION
    subject_type: OpponentSubjectType
    subject_name: str
    attack: tuple[CoachSignalView, ...]
    defence: tuple[CoachSignalView, ...]
    risks: tuple[CoachSignalView, ...]
    individual: tuple[CoachSignalView, ...]
    recommendations: tuple[ReportRecommendationView, ...]
    evidence: tuple[CoachSignalView, ...]


class MatchCheatSheetPageView(ViewModel):
    """One-map, one-page projection of immutable findings and recommendations."""

    schema_version: str = CHEAT_SHEET_SCHEMA_VERSION
    rule_version: str = CHEAT_SHEET_RULE_VERSION
    profile_id: UUID
    display_name: str
    subject_type: OpponentSubjectType
    strategy_run_id: UUID
    map_name: str
    available_maps: tuple[str, ...] = Field(min_length=1)
    included_matches: int = Field(ge=0)
    reliability_tier: str
    reliability_label: str
    reliability_message: str
    recommendations_suppressed: bool
    attack: tuple[CoachSignalView, ...]
    defence: tuple[CoachSignalView, ...]
    risks: tuple[CoachSignalView, ...]
    recommendations: tuple[ReportRecommendationView, ...]
    evidence_references: int = Field(ge=0)
    source_report_href: str


class ReportEvidenceView(ViewModel):
    evidence_id: UUID
    match_id: UUID
    match_short_id: str
    round_number: int = Field(ge=1)
    tick_label: str
    contributed_to_numerator: bool
    description: str
    event_ids: tuple[str, ...]
    feature_ids: tuple[str, ...]
    snapshot_ids: tuple[str, ...]
    economy_snapshot_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    map_href: str
    timeline_href: str


class ScoutingReportDetailView(ViewModel):
    report_schema_version: str = REPORT_SCHEMA_VERSION
    report_view_rule_version: str = REPORT_VIEW_RULE_VERSION
    profile_id: UUID
    display_name: str
    strategy_run_id: UUID
    finding: ReportFindingView
    recommendation: ReportRecommendationView | None = None
    tactical_interpretation: str | None = None
    recommended_response: str | None = None
    avoid: str | None = None
    evidence: tuple[ReportEvidenceView, ...]
    limitations: tuple[str, ...]
    warnings: tuple[str, ...]
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1)
    confidence_method: str
    confidence_level: float = Field(gt=0, lt=1)
    confidence_score: float = Field(ge=0, le=1)
    confidence_lower: float = Field(ge=0, le=1)
    confidence_upper: float = Field(ge=0, le=1)
    finding_json_href: str
    recommendation_json_href: str | None = None


def build_scouting_report_page(
    source: ScoutingReportSource,
    workspace: OpponentWorkspace,
    filters: ScoutingReportFilters,
) -> ScoutingReportPageView:
    scoped_findings = subject_findings(source.findings, workspace)
    subject_ids = {item.finding_id for item in scoped_findings}
    readiness = {item.finding_id: item for item in source.readiness.records}
    skipped = {
        item.finding_id: item for item in source.skipped_findings if item.finding_id in subject_ids
    }
    recommendations_by_finding = {
        item.source_finding_id: item
        for item in source.recommendations
        if item.source_finding_id in subject_ids
    }
    filtered = tuple(item for item in scoped_findings if _matches_filter(item, filters))
    filtered = tuple(
        sorted(
            filtered,
            key=lambda item: (
                item.pattern_type.value,
                item.scope.map_name,
                item.scope.buy_type.value if item.scope.buy_type else "unknown",
                item.scope.side.value,
                -item.frequency,
                str(item.finding_id),
            ),
        )
    )

    page_count = max(1, (len(filtered) + filters.page_size - 1) // filters.page_size)
    page = min(filters.page, page_count)
    effective_filters = filters.model_copy(update={"page": page})
    start = (page - 1) * filters.page_size
    visible = filtered[start : start + filters.page_size]
    cards = tuple(
        _finding_view(
            item,
            source=source,
            readiness=readiness[item.finding_id],
            skipped=skipped.get(item.finding_id),
            recommendation=recommendations_by_finding.get(item.finding_id),
        )
        for item in visible
    )
    groups = tuple(
        ReportFindingGroupView(
            key=key,
            title=title,
            subtitle=subtitle,
            findings=tuple(item for item in cards if _group_key(item) == key),
        )
        for key, title, subtitle in _GROUPS
        if any(_group_key(item) == key for item in cards)
    )
    visible_ids = {item.finding_id for item in visible}
    recommendations_suppressed = source.validation.status is StrategyAcceptanceStatus.FAILED
    recommendation_views = (
        ()
        if recommendations_suppressed
        else tuple(
            _recommendation_view(item, source.strategy.profile_id)
            for item in source.recommendations
            if item.source_finding_id in visible_ids
        )
    )
    selected_by_match = {item.selection.match_id: item for item in workspace.selected_matches}
    corpus_matches = tuple(
        ReportCorpusMatchView(
            match_id=item.match_id,
            map_name=item.map_name,
            source_name=(
                selected_by_match[item.match_id].source_name
                if item.match_id in selected_by_match
                else "Source unavailable"
            ),
            team_name=(
                selected_by_match[item.match_id].team_name
                if item.match_id in selected_by_match
                else "Команда соперника недоступна"
            ),
            round_count=(
                selected_by_match[item.match_id].round_count
                if item.match_id in selected_by_match
                else 0
            ),
            input_status=item.input_status.value,
            href=f"/ui/matches/{item.match_id}",
        )
        for item in source.analysis.input_matches
    )
    validation = source.validation
    status = validation.status.value
    required_matches = validation.config.minimum_corpus_matches
    reliability_tier, reliability_label, reliability_message = corpus_reliability(
        validation.coverage.included_matches
    )
    return ScoutingReportPageView(
        profile_id=source.strategy.profile_id,
        display_name=workspace.profile.display_name,
        subject_type=workspace.profile.subject_type,
        target_player_name=workspace.profile.target_player_name,
        strategy_run_id=source.strategy.strategy_run_id,
        strategy_fingerprint=source.strategy.strategy_fingerprint,
        source_analysis_run_id=source.analysis.analysis_run_id,
        validation_id=validation.validation_id,
        validation_fingerprint=validation.validation_fingerprint,
        acceptance_status=status,
        acceptance_label=_human(status),
        acceptance_css_class=_status_css(status),
        acceptance_message=_acceptance_message(
            status, validation.coverage.included_matches, required_matches
        ),
        selected_matches=validation.coverage.selected_matches,
        included_matches=validation.coverage.included_matches,
        required_matches=required_matches,
        corpus_reliability_tier=reliability_tier.value,
        corpus_reliability_label=reliability_label,
        corpus_reliability_message=reliability_message,
        corpus_reliability_css_class=_reliability_css(reliability_tier.value),
        source_findings=len(scoped_findings),
        ready_findings=sum(
            readiness[item.finding_id].eligible_for_stage_8_7 for item in scoped_findings
        ),
        recommendations_count=len(recommendations_by_finding),
        recommendations_suppressed=recommendations_suppressed,
        skipped_findings=len(skipped),
        evidence_references=sum(len(item.evidence_references) for item in scoped_findings),
        maps=validation.coverage.maps,
        sides=validation.coverage.sides,
        buy_types=validation.coverage.buy_types,
        checks=tuple(
            ReportCheckView(
                code=item.code.value,
                label=_human(item.code.value),
                status=item.status.value,
                css_class=_check_css(item.status),
                message=_check_message(
                    item.code.value,
                    item.status.value,
                    item.observed,
                    item.required,
                ),
                observed=str(item.observed) if item.observed is not None else None,
                required=str(item.required) if item.required is not None else None,
            )
            for item in validation.checks
        ),
        warnings=tuple(dict.fromkeys((*validation.warnings, *source.strategy.warnings))),
        filters=effective_filters,
        filter_options=ReportFilterOptions(
            maps=tuple(sorted({item.scope.map_name for item in scoped_findings})),
            buy_types=tuple(
                sorted(
                    {
                        item.scope.buy_type.value
                        for item in scoped_findings
                        if item.scope.buy_type is not None
                    }
                )
            ),
            pattern_types=tuple(
                (item.value, _human(item.value))
                for item in PatternType
                if any(candidate.pattern_type is item for candidate in scoped_findings)
            ),
        ),
        filtered_findings=len(filtered),
        visible_findings=len(visible),
        page=page,
        page_count=page_count,
        previous_href=(
            _report_href(
                source.strategy.profile_id,
                source.strategy.strategy_run_id,
                effective_filters,
                page=page - 1,
            )
            if page > 1
            else None
        ),
        next_href=(
            _report_href(
                source.strategy.profile_id,
                source.strategy.strategy_run_id,
                effective_filters,
                page=page + 1,
            )
            if page < page_count
            else None
        ),
        finding_groups=groups,
        recommendations=recommendation_views,
        corpus_matches=corpus_matches,
        skip_reason_counts=dict(Counter(item.reason.value for item in skipped.values())),
        report_json_href=_report_json_href(
            source.strategy.profile_id,
            source.strategy.strategy_run_id,
            effective_filters,
        ),
        report_export_json_href=(
            f"/api/opponents/{source.strategy.profile_id}/report/export.json"
            f"?run_id={source.strategy.strategy_run_id}"
        ),
        report_print_href=(
            f"/ui/opponents/{source.strategy.profile_id}/report/print"
            f"?run_id={source.strategy.strategy_run_id}"
        ),
        report_pdf_href=(
            f"/api/opponents/{source.strategy.profile_id}/report/export.pdf"
            f"?run_id={source.strategy.strategy_run_id}"
        ),
    )


def build_coach_report_page(
    source: ScoutingReportSource,
    workspace: OpponentWorkspace,
    *,
    section_limit: int = 3,
) -> CoachReportPageView:
    """Build a concise UI projection without changing stored findings or statistics."""

    if section_limit < 1:
        raise ValueError("coach report section limit must be positive")
    scoped_findings = subject_findings(source.findings, workspace)
    subject_ids = {item.finding_id for item in scoped_findings}
    readiness = {item.finding_id: item for item in source.readiness.records}
    skipped = {
        item.finding_id: item for item in source.skipped_findings if item.finding_id in subject_ids
    }
    recommendations_by_finding = {
        item.source_finding_id: item
        for item in source.recommendations
        if item.source_finding_id in subject_ids
    }
    cards = tuple(
        _finding_view(
            finding,
            source=source,
            readiness=readiness[finding.finding_id],
            skipped=skipped.get(finding.finding_id),
            recommendation=recommendations_by_finding.get(finding.finding_id),
        )
        for finding in scoped_findings
    )
    grouped = {
        key: tuple(item for item in cards if _group_key(item) == key)
        for key in ("t_side", "ct_side", "risks", "individual")
    }
    findings_by_id = {item.finding_id: item for item in scoped_findings}
    individual: tuple[CoachSignalView, ...]
    if workspace.profile.subject_type is OpponentSubjectType.PLAYER:
        personal = grouped["individual"]
        attack = _coach_signals(
            tuple(item for item in personal if item.side == Side.T.value),
            findings_by_id,
            section_limit,
        )
        defence = _coach_signals(
            tuple(item for item in personal if item.side == Side.CT.value),
            findings_by_id,
            section_limit,
        )
        risks = _coach_signals(
            tuple(
                item
                for item in personal
                if findings_by_id[item.finding_id].pattern_type
                is PatternType.RECURRING_OPENING_DEATH
            ),
            findings_by_id,
            section_limit,
        )
        individual = ()
    else:
        attack = _coach_signals(grouped["t_side"], findings_by_id, section_limit)
        defence = _coach_signals(grouped["ct_side"], findings_by_id, section_limit)
        risks = _coach_signals(grouped["risks"], findings_by_id, section_limit)
        individual = _coach_signals(grouped["individual"], findings_by_id, section_limit)
    evidence = _unique_signals((*attack, *defence, *risks, *individual), limit=4)
    recommendations: tuple[ReportRecommendationView, ...] = ()
    if source.validation.status is not StrategyAcceptanceStatus.FAILED:
        recommendations = tuple(
            sorted(
                (
                    _recommendation_view(item, workspace.profile.profile_id)
                    for item in source.recommendations
                    if item.source_finding_id in subject_ids
                ),
                key=lambda item: (
                    -item.evidence_matches,
                    -_ratio_value(item.ratio),
                    item.map_name,
                    item.side,
                    str(item.recommendation_id),
                ),
            )[:section_limit]
        )
    return CoachReportPageView(
        subject_type=workspace.profile.subject_type,
        subject_name=workspace.profile.target_player_name or workspace.profile.display_name,
        attack=attack,
        defence=defence,
        risks=risks,
        individual=individual,
        recommendations=recommendations,
        evidence=evidence,
    )


def build_match_cheat_sheet_page(
    source: ScoutingReportSource,
    workspace: OpponentWorkspace,
    *,
    map_name: str | None = None,
    section_limit: int = 2,
) -> MatchCheatSheetPageView:
    """Build a compact map-specific plan without recalculating source statistics."""

    if section_limit < 1:
        raise ValueError("cheat sheet section limit must be positive")
    scoped_findings = subject_findings(source.findings, workspace)
    available_maps = tuple(
        sorted(
            {
                *(
                    item.map_name
                    for item in source.analysis.input_matches
                    if item.input_status.value == "included"
                ),
                *(item.scope.map_name for item in scoped_findings),
            }
        )
    )
    if not available_maps:
        raise ValueError("В отчёте нет карт для шпаргалки.")
    selected_map = map_name or available_maps[0]
    if selected_map not in available_maps:
        raise ValueError("Выбранной карты нет в закреплённом отчёте.")

    readiness = {item.finding_id: item for item in source.readiness.records}
    skipped = {item.finding_id: item for item in source.skipped_findings}
    recommendations_by_finding = {item.source_finding_id: item for item in source.recommendations}
    source_findings = {
        item.finding_id: item for item in scoped_findings if item.scope.map_name == selected_map
    }
    cards = tuple(
        _finding_view(
            finding,
            source=source,
            readiness=readiness[finding.finding_id],
            skipped=skipped.get(finding.finding_id),
            recommendation=recommendations_by_finding.get(finding.finding_id),
        )
        for finding in source_findings.values()
    )
    grouped = {
        key: tuple(item for item in cards if _group_key(item) == key)
        for key in ("t_side", "ct_side", "risks")
    }
    if workspace.profile.subject_type is OpponentSubjectType.PLAYER:
        personal = tuple(item for item in cards if _group_key(item) == "individual")
        attack = _coach_signals(
            tuple(item for item in personal if item.side == Side.T.value),
            source_findings,
            section_limit,
        )
        defence = _coach_signals(
            tuple(item for item in personal if item.side == Side.CT.value),
            source_findings,
            section_limit,
        )
        risks = _coach_signals(
            tuple(
                item
                for item in personal
                if source_findings[item.finding_id].pattern_type
                is PatternType.RECURRING_OPENING_DEATH
            ),
            source_findings,
            section_limit,
        )
    else:
        attack = _coach_signals(grouped["t_side"], source_findings, section_limit)
        defence = _coach_signals(grouped["ct_side"], source_findings, section_limit)
        risks = _coach_signals(grouped["risks"], source_findings, section_limit)
    recommendations_suppressed = source.validation.status is StrategyAcceptanceStatus.FAILED
    recommendations: tuple[ReportRecommendationView, ...] = ()
    if not recommendations_suppressed:
        recommendations = tuple(
            sorted(
                (
                    _recommendation_view(item, workspace.profile.profile_id)
                    for item in source.recommendations
                    if item.scope.map_name == selected_map
                ),
                key=lambda item: (
                    -item.evidence_matches,
                    -_ratio_value(item.ratio),
                    item.side,
                    str(item.recommendation_id),
                ),
            )[:section_limit]
        )
    included_matches = sum(
        item.map_name == selected_map and item.input_status.value == "included"
        for item in source.analysis.input_matches
    )
    reliability_tier, reliability_label, reliability_message = corpus_reliability(included_matches)
    selected_signals = (*attack, *defence, *risks)
    return MatchCheatSheetPageView(
        profile_id=source.strategy.profile_id,
        display_name=workspace.profile.display_name,
        subject_type=workspace.profile.subject_type,
        strategy_run_id=source.strategy.strategy_run_id,
        map_name=selected_map,
        available_maps=available_maps,
        included_matches=included_matches,
        reliability_tier=reliability_tier.value,
        reliability_label=reliability_label,
        reliability_message=reliability_message,
        recommendations_suppressed=recommendations_suppressed,
        attack=attack,
        defence=defence,
        risks=risks,
        recommendations=recommendations,
        evidence_references=sum(item.finding.evidence_count for item in selected_signals),
        source_report_href=(
            f"/ui/opponents/{source.strategy.profile_id}/report"
            f"?run_id={source.strategy.strategy_run_id}"
        ),
    )


def _coach_signals(
    findings: tuple[ReportFindingView, ...],
    source_findings: dict[UUID, AnalysisFinding],
    limit: int,
) -> tuple[CoachSignalView, ...]:
    findings = tuple(
        item
        for item in findings
        if is_useful_coach_signal(
            source_findings[item.finding_id].pattern_type,
            source_findings[item.finding_id].pattern_value,
        )
    )
    ranked = sorted(
        findings,
        key=lambda item: (
            item.small_sample_warning,
            -item.evidence_matches,
            -item.sample_size,
            -(item.numerator / item.denominator),
            item.pattern_type,
            item.map_name,
            str(item.finding_id),
        ),
    )
    result: list[CoachSignalView] = []
    used_patterns: set[str] = set()
    for item in ranked:
        if item.pattern_type in used_patterns:
            continue
        used_patterns.add(item.pattern_type)
        source = source_findings[item.finding_id]
        plain = coach_pattern_text(source.pattern_type, source.pattern_value)
        result.append(
            CoachSignalView(
                finding=item,
                frequency_key=_coach_frequency_key(item.numerator / item.denominator),
                kind_label=plain.kind,
                plain_title=plain.title,
                plain_explanation=plain.explanation,
            )
        )
        if len(result) == limit:
            break
    return tuple(result)


def _unique_signals(
    signals: tuple[CoachSignalView, ...], *, limit: int
) -> tuple[CoachSignalView, ...]:
    result: list[CoachSignalView] = []
    used: set[UUID] = set()
    for item in signals:
        if item.finding.finding_id in used:
            continue
        used.add(item.finding.finding_id)
        result.append(item)
        if len(result) == limit:
            break
    return tuple(result)


def _coach_frequency_key(value: float) -> str:
    if value >= 1.0:
        return "tactical.frequency.every_time"
    if value >= 0.75:
        return "tactical.frequency.almost_always"
    if value >= 0.5:
        return "tactical.frequency.often"
    if value >= 0.25:
        return "tactical.frequency.sometimes"
    if value > 0:
        return "tactical.frequency.rarely"
    return "tactical.frequency.not_seen"


def _ratio_value(value: str) -> float:
    numerator, _, denominator = value.partition("/")
    return int(numerator) / int(denominator)


def build_scouting_report_detail(
    source: ScoutingReportSource,
    workspace: OpponentWorkspace,
    finding: AnalysisFinding,
) -> ScoutingReportDetailView:
    readiness = next(
        item for item in source.readiness.records if item.finding_id == finding.finding_id
    )
    skipped = next(
        (item for item in source.skipped_findings if item.finding_id == finding.finding_id),
        None,
    )
    recommendation = next(
        (item for item in source.recommendations if item.source_finding_id == finding.finding_id),
        None,
    )
    card = _finding_view(
        finding,
        source=source,
        readiness=readiness,
        skipped=skipped,
        recommendation=recommendation,
    )
    recommendation_view = (
        _recommendation_view(recommendation, source.strategy.profile_id)
        if recommendation is not None
        else None
    )
    return ScoutingReportDetailView(
        profile_id=source.strategy.profile_id,
        display_name=workspace.profile.display_name,
        strategy_run_id=source.strategy.strategy_run_id,
        finding=card,
        recommendation=recommendation_view,
        tactical_interpretation=(
            recommendation.tactical_interpretation.text if recommendation else None
        ),
        recommended_response=(recommendation.recommendation.text if recommendation else None),
        avoid=recommendation.avoid.text if recommendation else None,
        evidence=tuple(_evidence_view(item) for item in finding.evidence_references),
        limitations=finding.limitations,
        warnings=finding.warnings,
        numerator=finding.numerator,
        denominator=finding.denominator,
        frequency=finding.frequency,
        confidence_method=finding.confidence.method,
        confidence_level=finding.confidence.level,
        confidence_score=finding.confidence.score,
        confidence_lower=finding.confidence.lower_bound,
        confidence_upper=finding.confidence.upper_bound,
        finding_json_href=(
            f"/api/opponents/{source.strategy.profile_id}/analysis/findings/"
            f"{finding.finding_id}"
            f"?run_id={source.analysis.analysis_run_id}"
        ),
        recommendation_json_href=(
            f"/api/opponents/{source.strategy.profile_id}/analysis/strategies/"
            f"{recommendation.recommendation_id}?run_id={source.strategy.strategy_run_id}"
            if recommendation is not None
            else None
        ),
    )


def _finding_view(
    finding: AnalysisFinding,
    *,
    source: ScoutingReportSource,
    readiness: FindingReadinessRecord,
    skipped: SkippedStrategyFinding | None,
    recommendation: CounterStrategyRecommendation | None,
) -> ReportFindingView:
    readiness_reasons = tuple(
        _human(item.value) for item in (*readiness.blocking_reasons, *readiness.limitations)
    )
    if recommendation is not None:
        strategy_status = "published"
        strategy_reason = "Прошло проверку готовности и детерминированное правило."
    elif skipped is not None:
        strategy_status = "not published"
        strategy_reason = _human(skipped.reason.value)
    else:
        strategy_status = "unclassified"
        strategy_reason = "Классификация рекомендации недоступна"
    value_label = _value_label(finding)
    reliability_tier, reliability_label, reliability_message = corpus_reliability(
        finding.denominator_match_count
    )
    return ReportFindingView(
        finding_id=finding.finding_id,
        title=f"{_human(finding.pattern_type.value)}: {value_label}",
        observation=(
            f"Наблюдение «{value_label}» подтверждено в {finding.numerator} из "
            f"{finding.denominator} подходящих раундов ({_percent(finding.frequency)})."
        ),
        category=finding.category.value,
        category_label=_human(finding.category.value),
        pattern_type=finding.pattern_type.value,
        pattern_label=_human(finding.pattern_type.value),
        value_label=value_label,
        map_name=finding.scope.map_name,
        side=finding.scope.side.value,
        buy_type=finding.scope.buy_type.value if finding.scope.buy_type else "unknown",
        numerator=finding.numerator,
        denominator=finding.denominator,
        frequency_percent=_percent(finding.frequency),
        sample_size=finding.sample_size,
        evidence_matches=finding.denominator_match_count,
        reliability_tier=reliability_tier.value,
        reliability_label=reliability_label,
        reliability_message=reliability_message,
        confidence_score_percent=_percent(finding.confidence.score),
        confidence_interval=(
            f"{_percent(finding.confidence.lower_bound)}–{_percent(finding.confidence.upper_bound)}"
        ),
        readiness_status=readiness.status.value,
        readiness_css_class=_status_css(readiness.status.value),
        readiness_reasons=readiness_reasons,
        strategy_status=strategy_status,
        strategy_reason=strategy_reason,
        small_sample_warning=finding.small_sample_warning,
        limitations_count=len(finding.limitations),
        evidence_count=len(finding.evidence_references),
        detail_href=(
            f"/ui/opponents/{source.strategy.profile_id}/report/findings/"
            f"{finding.finding_id}"
            f"?run_id={source.strategy.strategy_run_id}"
        ),
    )


def _recommendation_view(
    recommendation: CounterStrategyRecommendation,
    profile_id: UUID,
) -> ReportRecommendationView:
    reliability_tier, reliability_label, reliability_message = corpus_reliability(
        recommendation.denominator_match_count
    )
    return ReportRecommendationView(
        recommendation_id=recommendation.recommendation_id,
        source_finding_id=recommendation.source_finding_id,
        title=_recommendation_title(recommendation),
        category=recommendation.category.value,
        category_label=_human(recommendation.category.value),
        rule_id=recommendation.rule_id.value,
        map_name=recommendation.scope.map_name,
        side=recommendation.scope.side.value,
        buy_type=(
            recommendation.scope.buy_type.value
            if recommendation.scope.buy_type is not None
            else "unknown"
        ),
        observation=(
            f"Наблюдение подтверждено в {recommendation.numerator} из "
            f"{recommendation.denominator} подходящих раундов "
            f"({_percent(recommendation.frequency)})."
        ),
        tactical_interpretation=_recommendation_text(recommendation, "interpretation"),
        recommended_response=_recommendation_text(recommendation, "response"),
        avoid=_recommendation_text(recommendation, "avoid"),
        frequency_percent=_percent(recommendation.frequency),
        ratio=f"{recommendation.numerator}/{recommendation.denominator}",
        evidence_matches=recommendation.denominator_match_count,
        reliability_tier=reliability_tier.value,
        reliability_label=reliability_label,
        reliability_message=reliability_message,
        confidence_score_percent=_percent(recommendation.confidence.score),
        detail_href=(
            f"/ui/opponents/{profile_id}/report/findings/"
            f"{recommendation.source_finding_id}?run_id={recommendation.strategy_run_id}"
        ),
    )


def _evidence_view(reference: EvidenceReference) -> ReportEvidenceView:
    return ReportEvidenceView(
        evidence_id=reference.evidence_id,
        match_id=reference.match_id,
        match_short_id=str(reference.match_id).split("-")[0],
        round_number=reference.round_number,
        tick_label=str(reference.tick) if reference.tick is not None else "Недоступно",
        contributed_to_numerator=reference.contributed_to_numerator,
        description=(
            "Раунд вошёл в числитель наблюдения."
            if reference.contributed_to_numerator
            else "Раунд вошёл только в знаменатель наблюдения."
        ),
        event_ids=tuple(str(item) for item in reference.event_ids),
        feature_ids=tuple(str(item) for item in reference.feature_ids),
        snapshot_ids=tuple(str(item) for item in reference.snapshot_ids),
        economy_snapshot_ids=tuple(str(item) for item in reference.economy_snapshot_ids),
        limitations=reference.limitations,
        map_href=prefer_smooth_playback(reference.map_href),
        timeline_href=reference.timeline_href,
    )


def _matches_filter(finding: AnalysisFinding, filters: ScoutingReportFilters) -> bool:
    return (
        (filters.map_name is None or finding.scope.map_name == filters.map_name)
        and (filters.side is None or finding.scope.side is filters.side)
        and (filters.buy_type is None or finding.scope.buy_type is filters.buy_type)
        and (filters.pattern_type is None or finding.pattern_type is filters.pattern_type)
        and finding.sample_size >= filters.minimum_sample_size
        and finding.confidence.score >= filters.minimum_confidence
    )


def _group_key(finding: ReportFindingView) -> str:
    if finding.category == FindingCategory.PLAYER_TENDENCY.value:
        return "individual"
    if finding.category == FindingCategory.OUTCOME_ASSOCIATION.value or finding.pattern_type in {
        PatternType.RECURRING_OPENING_DEATH.value,
        PatternType.LOST_MAN_ADVANTAGE.value,
        PatternType.UNTRADED_DEATH.value,
    }:
        return "risks"
    return "t_side" if finding.side == Side.T.value else "ct_side"


_GROUPS = (
    (
        "t_side",
        "Тенденции за T",
        "Наблюдаемые действия подтверждённого соперника на стороне T.",
    ),
    (
        "ct_side",
        "Тенденции за CT",
        "Наблюдаемые действия подтверждённого соперника на стороне CT.",
    ),
    (
        "individual",
        "Индивидуальные тенденции",
        "Наблюдения игроков привязаны к Steam ID; неразрешённые личности "
        "остаются в пределах матча.",
    ),
    (
        "risks",
        "Результаты и сигналы риска",
        "Связи, которые могут указывать на повторяющиеся ошибки, "
        "но не доказывают намерение или причину.",
    ),
)


def _report_href(
    profile_id: UUID,
    strategy_run_id: UUID,
    filters: ScoutingReportFilters,
    *,
    page: int,
) -> str:
    query = _filter_query(filters, page=page)
    query["run_id"] = str(strategy_run_id)
    return f"/ui/opponents/{profile_id}/report?{urlencode(query)}"


def _report_json_href(
    profile_id: UUID,
    strategy_run_id: UUID,
    filters: ScoutingReportFilters,
) -> str:
    query = _filter_query(filters, page=filters.page)
    query["run_id"] = str(strategy_run_id)
    return f"/api/opponents/{profile_id}/report?{urlencode(query)}"


def _filter_query(filters: ScoutingReportFilters, *, page: int) -> dict[str, str | int | float]:
    result: dict[str, str | int | float] = {
        "page": page,
        "page_size": filters.page_size,
        "minimum_sample_size": filters.minimum_sample_size,
        "minimum_confidence": filters.minimum_confidence,
    }
    if filters.map_name:
        result["map"] = filters.map_name
    if filters.side:
        result["side"] = filters.side.value
    if filters.buy_type:
        result["buy_type"] = filters.buy_type.value
    if filters.pattern_type:
        result["pattern_type"] = filters.pattern_type.value
    return result


def _check_css(status: ValidationCheckStatus) -> str:
    if status is ValidationCheckStatus.PASSED:
        return "available"
    if status in {ValidationCheckStatus.WARNING, ValidationCheckStatus.BLOCKED}:
        return "partial"
    return "unavailable"


def _status_css(status: str) -> str:
    return (
        "available"
        if status in {"passed", "ready"}
        else ("partial" if status in {"blocked", "limited"} else "unavailable")
    )


def _reliability_css(tier: str) -> str:
    if tier == "high":
        return "available"
    if tier == "tactical_trend":
        return "partial"
    return "neutral"


def _acceptance_message(status: str, included: int, required: int) -> str:
    if status == "passed":
        return "Выбранный расчёт прошёл все детерминированные проверки."
    if status == "blocked":
        return (
            f"Данные внутренне согласованы, но отчёт пока не принят "
            f"({included}/{required} подтверждённых матчей)."
        )
    return "Проверка целостности не пройдена. Не используйте этот отчёт для подготовки."


def _value_label(finding: AnalysisFinding) -> str:
    value = finding.pattern_value
    return value.current_name if isinstance(value, PlayerPatternValue) else value.label


def _human(value: str) -> str:
    labels = {
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
        "team_tendency": "Командная тенденция",
        "player_tendency": "Индивидуальная тенденция",
        "outcome_association": "Связь с результатом",
        "map_control": "Контроль карты",
        "player_specific": "По конкретному игроку",
        "round_management": "Управление раундом",
        "trade_structure": "Структура разменов",
        "finding_not_ready": "наблюдение не прошло проверку готовности",
        "corpus_below_minimum": "выборка ниже уровня высокой надёжности",
        "finding_matches_below_minimum": "наблюдение встречается в малом числе матчей",
        "finding_sample_below_minimum": "малая выборка подходящих раундов",
        "no_supported_rule": "нет поддерживаемого правила",
        "rule_threshold_not_met": "порог правила не достигнут",
        "passed": "пройдено",
        "ready": "готово",
        "limited": "с ограничениями",
        "blocked": "заблокировано",
        "failed": "ошибка",
        "warning": "предупреждение",
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
    return labels.get(value, value.replace("_", " ").strip().capitalize())


def _recommendation_title(recommendation: CounterStrategyRecommendation) -> str:
    return {
        "frequent_site_v1": "Подготовить ответ на частый выход",
        "frequent_early_control_v1": "Оспорить ранний контроль",
        "recurring_opening_player_v1": "Подготовиться к первой дуэли игрока",
        "recurring_opening_death_v1": "Давить на повторяющуюся первую смерть",
        "low_opening_conversion_v1": "Не отдавать раунд после первой смерти",
        "opening_death_recovery_v1": "Закрыть сценарий восстановления",
        "lost_man_advantage_v1": "Наказывать потерю преимущества",
        "untraded_death_v1": "Разрушать структуру разменов",
    }.get(recommendation.rule_id.value, "Тактический ответ")


def _check_message(
    code: str,
    status: str,
    observed: object,
    required: object,
) -> str:
    message = f"Проверка «{_human(code)}»: {_human(status)}."
    if observed is not None:
        message += f" Получено: {observed}."
    if required is not None:
        message += f" Требуется: {required}."
    return message


def _recommendation_text(
    recommendation: CounterStrategyRecommendation,
    kind: str,
) -> str:
    common = {
        "interpretation": (
            "Это повторяющийся исторический сигнал, а не доказательство намерения или причины."
        ),
        "response": (
            "Подготовьте проверяемый контр-сценарий и адаптируйтесь "
            "только после подтверждения в матче."
        ),
        "avoid": (
            "Не считайте тенденцию гарантированным действием и не переоценивайте небольшую выборку."
        ),
    }
    return common[kind]


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


__all__ = [
    "COACH_REPORT_RULE_VERSION",
    "REPORT_SCHEMA_VERSION",
    "REPORT_VIEW_RULE_VERSION",
    "CoachReportPageView",
    "CoachSignalView",
    "ScoutingReportDetailView",
    "ScoutingReportFilters",
    "ScoutingReportPageView",
    "build_coach_report_page",
    "build_scouting_report_detail",
    "build_scouting_report_page",
]
