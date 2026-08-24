"""Typed presentation models for the local product UI."""

from stratweb.web.view_models.economy import (
    EconomyPageView,
    EconomyPlayerView,
    EconomyRoundView,
    EconomyTeamView,
    build_economy_page,
)
from stratweb.web.view_models.product import (
    HealthItemView,
    MatchLibraryItemView,
    MatchOverviewView,
    PlayerSummaryView,
    RoundStripItemView,
    TeamScoreView,
)
from stratweb.web.view_models.round_features import (
    FeatureCapabilityView,
    RoundFeaturePageView,
    RoundFeatureRoundView,
    RoundFeatureRowView,
    build_round_feature_page,
    feature_type_options,
)
from stratweb.web.view_models.scouting_report import (
    CoachReportPageView,
    CoachSignalView,
    ScoutingReportDetailView,
    ScoutingReportFilters,
    ScoutingReportPageView,
    build_coach_report_page,
    build_scouting_report_detail,
    build_scouting_report_page,
)

__all__ = [
    "EconomyPageView",
    "EconomyPlayerView",
    "EconomyRoundView",
    "EconomyTeamView",
    "CoachReportPageView",
    "CoachSignalView",
    "HealthItemView",
    "FeatureCapabilityView",
    "MatchLibraryItemView",
    "MatchOverviewView",
    "PlayerSummaryView",
    "RoundStripItemView",
    "RoundFeaturePageView",
    "RoundFeatureRoundView",
    "RoundFeatureRowView",
    "TeamScoreView",
    "build_economy_page",
    "build_coach_report_page",
    "build_round_feature_page",
    "ScoutingReportDetailView",
    "ScoutingReportFilters",
    "ScoutingReportPageView",
    "build_scouting_report_detail",
    "build_scouting_report_page",
    "feature_type_options",
]
