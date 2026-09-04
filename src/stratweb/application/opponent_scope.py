"""Deterministic scoping rules for team and individual opponent profiles."""

from __future__ import annotations

from stratweb.application.opponent_models import OpponentSubjectType, OpponentWorkspace
from stratweb.findings.models import AnalysisFinding
from stratweb.patterns.models import PlayerPatternValue


def finding_belongs_to_subject(
    finding: AnalysisFinding,
    workspace: OpponentWorkspace,
) -> bool:
    """Return true only when a finding belongs to the explicitly selected subject."""

    profile = workspace.profile
    if profile.subject_type is OpponentSubjectType.TEAM:
        return True
    if profile.target_steam_id is None:
        return False
    value = finding.pattern_value
    return isinstance(value, PlayerPatternValue) and value.steam_id == profile.target_steam_id


def subject_findings(
    findings: tuple[AnalysisFinding, ...],
    workspace: OpponentWorkspace,
) -> tuple[AnalysisFinding, ...]:
    return tuple(item for item in findings if finding_belongs_to_subject(item, workspace))


__all__ = ["finding_belongs_to_subject", "subject_findings"]
