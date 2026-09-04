"""Versioned contracts for evidence-backed head-to-head comparisons."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.domain.enums import Side
from stratweb.tactical_v2.models import TacticalInsight, TacticalV2RunSummary

HEAD_TO_HEAD_SCHEMA_VERSION = "1.0.0"
HEAD_TO_HEAD_RULE_VERSION = "opposite_side_evidence_pairing_v1"


class HeadToHeadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HeadToHeadRule(StrEnum):
    OPENING_VS_TRADE = "opening_pressure_vs_trade_support"
    OPENING_VS_SPACING = "opening_pressure_vs_early_spacing"


class HeadToHeadRiskLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class HeadToHeadReliability(StrEnum):
    GAME_FACTS = "game_facts"
    TACTICAL_TREND = "tactical_trend"
    STABLE_TREND = "stable_trend"
    HIGH = "high"


class HeadToHeadInput(HeadToHeadModel):
    opponent_profile_id: UUID
    our_profile_id: UUID
    opponent_summary: TacticalV2RunSummary
    our_summary: TacticalV2RunSummary
    opponent_insights: tuple[TacticalInsight, ...]
    our_insights: tuple[TacticalInsight, ...]

    @model_validator(mode="after")
    def validate_sources(self) -> HeadToHeadInput:
        if self.opponent_profile_id == self.our_profile_id:
            raise ValueError("head-to-head profiles must be different")
        if self.opponent_summary.profile_id != self.opponent_profile_id:
            raise ValueError("opponent Tactical V2 summary belongs to another profile")
        if self.our_summary.profile_id != self.our_profile_id:
            raise ValueError("own-team Tactical V2 summary belongs to another profile")
        for insight in self.opponent_insights:
            if (
                insight.profile_id != self.opponent_profile_id
                or insight.tactical_run_id != self.opponent_summary.tactical_run_id
            ):
                raise ValueError("opponent insight lineage is inconsistent")
        for insight in self.our_insights:
            if (
                insight.profile_id != self.our_profile_id
                or insight.tactical_run_id != self.our_summary.tactical_run_id
            ):
                raise ValueError("own-team insight lineage is inconsistent")
        return self


class HeadToHeadComparison(HeadToHeadModel):
    comparison_id: UUID
    head_to_head_run_id: UUID
    rule: HeadToHeadRule
    map_name: str
    opponent_side: Side
    our_side: Side
    risk_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    risk_level: HeadToHeadRiskLevel
    reliability: HeadToHeadReliability
    sample_match_count: int = Field(ge=1)
    title: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    tactical_interpretation: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    opponent_insight: TacticalInsight
    our_insight: TacticalInsight
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pairing(self) -> HeadToHeadComparison:
        if self.opponent_side not in {Side.T, Side.CT} or self.our_side not in {
            Side.T,
            Side.CT,
        }:
            raise ValueError("head-to-head requires known T or CT sides")
        expected = Side.CT if self.opponent_side is Side.T else Side.T
        if self.our_side is not expected:
            raise ValueError("head-to-head sides must be opposite")
        if self.opponent_insight.map_name != self.map_name:
            raise ValueError("opponent insight map differs from comparison map")
        if self.our_insight.map_name != self.map_name:
            raise ValueError("own insight map differs from comparison map")
        if self.opponent_insight.side is not self.opponent_side:
            raise ValueError("opponent insight side differs from comparison side")
        if self.our_insight.side is not self.our_side:
            raise ValueError("own insight side differs from comparison side")
        if self.sample_match_count != min(
            self.opponent_insight.match_count, self.our_insight.match_count
        ):
            raise ValueError("head-to-head sample match count is inconsistent")
        return self


class HeadToHeadSummary(HeadToHeadModel):
    comparison_count: int = Field(ge=0)
    high_risk_count: int = Field(ge=0)
    medium_risk_count: int = Field(ge=0)
    low_risk_count: int = Field(ge=0)
    common_maps: tuple[str, ...]


class HeadToHeadRun(HeadToHeadModel):
    head_to_head_schema_version: str = HEAD_TO_HEAD_SCHEMA_VERSION
    head_to_head_rule_version: str = HEAD_TO_HEAD_RULE_VERSION
    head_to_head_run_id: UUID
    head_to_head_fingerprint: Sha256
    opponent_profile_id: UUID
    our_profile_id: UUID
    opponent_tactical_run_id: UUID
    opponent_tactical_fingerprint: Sha256
    our_tactical_run_id: UUID
    our_tactical_fingerprint: Sha256
    comparisons: tuple[HeadToHeadComparison, ...]
    summary: HeadToHeadSummary
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def validate_lineage(self) -> HeadToHeadRun:
        for item in self.comparisons:
            if item.head_to_head_run_id != self.head_to_head_run_id:
                raise ValueError("comparison belongs to another head-to-head run")
            if (
                item.opponent_insight.profile_id != self.opponent_profile_id
                or item.opponent_insight.tactical_run_id != self.opponent_tactical_run_id
            ):
                raise ValueError("comparison opponent lineage is inconsistent")
            if (
                item.our_insight.profile_id != self.our_profile_id
                or item.our_insight.tactical_run_id != self.our_tactical_run_id
            ):
                raise ValueError("comparison own-team lineage is inconsistent")
        if self.summary.comparison_count != len(self.comparisons):
            raise ValueError("head-to-head summary comparison count is inconsistent")
        return self


class HeadToHeadRunRecord(HeadToHeadModel):
    head_to_head_run_id: UUID
    head_to_head_fingerprint: Sha256
    opponent_profile_id: UUID
    our_profile_id: UUID
    opponent_tactical_run_id: UUID
    our_tactical_run_id: UUID
    head_to_head_schema_version: str
    head_to_head_rule_version: str
    created_at: datetime
    compatible: bool


class HeadToHeadSaveStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"


class HeadToHeadSaveResult(HeadToHeadModel):
    head_to_head_run_id: UUID
    head_to_head_fingerprint: Sha256
    status: HeadToHeadSaveStatus


__all__ = [
    name for name in globals() if name.startswith("HEAD_TO_HEAD_") or name.startswith("HeadToHead")
]
