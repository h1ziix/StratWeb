"""Independent structural validation for computed analytics records."""

from __future__ import annotations

from collections import Counter

from stratweb.application.canonical_models import ValidationSeverity

from .definitions import multikill_category
from .models import (
    AnalyticsAvailability,
    AnalyticsValidationIssue,
    MatchAnalytics,
    TimeConversionStatus,
    TradeWindowMode,
)


class AnalyticsValidator:
    def validate(self, analytics: MatchAnalytics) -> tuple[AnalyticsValidationIssue, ...]:
        issues: list[AnalyticsValidationIssue] = []
        player_kills = sum(item.kills for item in analytics.player_rounds)
        team_kills = sum(item.kills for item in analytics.team_rounds)
        team_deaths = sum(item.deaths for item in analytics.team_rounds)
        expected = analytics.summary.valid_enemy_kills
        if player_kills != expected:
            issues.append(_fatal("player_kill_sum_mismatch", player_kills, expected))
        if team_kills != expected:
            issues.append(_fatal("team_kill_sum_mismatch", team_kills, expected))
        if team_deaths != expected:
            issues.append(_fatal("team_death_sum_mismatch", team_deaths, expected))

        opening_counts = Counter(item.round_id for item in analytics.opening_duels)
        if any(count > 1 for count in opening_counts.values()):
            issues.append(_fatal("multiple_opening_duels", max(opening_counts.values()), 1))

        original_counts = Counter(item.original_kill_event_id for item in analytics.trade_events)
        trade_counts = Counter(item.traded_kill_event_id for item in analytics.trade_events)
        if any(count > 1 for count in original_counts.values()):
            issues.append(_fatal("original_kill_traded_multiple_times", 2, 1))
        if any(count > 1 for count in trade_counts.values()):
            issues.append(_fatal("trade_kill_used_multiple_times", 2, 1))
        if any(item.tick_delta < 0 for item in analytics.trade_events):
            issues.append(_fatal("negative_trade_tick_delta", -1, 0))
        seconds_mode = analytics.config.trade_window.mode is TradeWindowMode.SECONDS
        if any(
            (item.seconds_delta_status is TimeConversionStatus.AVAILABLE)
            != (item.seconds_delta is not None and bool(item.seconds_delta_source))
            for item in analytics.trade_events
        ):
            issues.append(_fatal("trade_seconds_metadata_mismatch", 1, 0))
        if seconds_mode and any(
            item.seconds_delta_status is not TimeConversionStatus.AVAILABLE
            for item in analytics.trade_events
        ):
            issues.append(_fatal("trade_seconds_missing_in_seconds_mode", 1, 0))
        if not seconds_mode and any(
            item.seconds_delta is not None
            or item.seconds_delta_source is not None
            or item.seconds_delta_status is not TimeConversionStatus.UNAVAILABLE
            for item in analytics.trade_events
        ):
            issues.append(_fatal("trade_seconds_asserted_without_seconds_mode", 1, 0))

        for capability in (
            analytics.availability.trade_metrics,
            analytics.availability.kast_metrics,
        ):
            if (
                capability.trade_window_mode is not analytics.config.trade_window.mode
                or capability.resolved_ticks != analytics.config.trade_window.resolved_ticks
                or capability.tickrate != analytics.config.trade_window.tickrate
                or capability.tickrate_source != analytics.config.trade_window.tickrate_source
            ):
                issues.append(_fatal("trade_policy_availability_mismatch", 1, 0))
                break

        for row in analytics.player_matches:
            if row.kast_rounds is not None and row.kast_rounds > row.rounds_played:
                issues.append(_fatal("kast_exceeds_rounds", row.kast_rounds, row.rounds_played))
            if row.survival_rounds > row.rounds_played:
                issues.append(
                    _fatal(
                        "survival_exceeds_rounds",
                        row.survival_rounds,
                        row.rounds_played,
                    )
                )
        for round_row in analytics.player_rounds:
            if round_row.multikill_category is not multikill_category(round_row.multikill_count):
                issues.append(
                    _fatal(
                        "multikill_category_mismatch",
                        round_row.multikill_count,
                        round_row.multikill_count,
                    )
                )
        if any(
            min(
                item.t_alive_before,
                item.t_alive_after,
                item.ct_alive_before,
                item.ct_alive_after,
            )
            < 0
            for item in analytics.man_advantage_transitions
        ):
            issues.append(_fatal("negative_alive_count", -1, 0))

        player_rounds = {(item.round_id, item.player_id): item for item in analytics.player_rounds}
        for transition in analytics.man_advantage_transitions:
            victim = player_rounds.get((transition.round_id, transition.causing_victim_player_id))
            if victim is None:
                issues.append(_fatal("advantage_victim_not_participant", 0, 1))
                continue
            if transition.event_classification.value == "repeated":
                expected_t = transition.t_alive_before
                expected_ct = transition.ct_alive_before
            elif victim.side.value == "T":
                expected_t = max(0, transition.t_alive_before - 1)
                expected_ct = transition.ct_alive_before
            else:
                expected_t = transition.t_alive_before
                expected_ct = max(0, transition.ct_alive_before - 1)
            if (transition.t_alive_after, transition.ct_alive_after) != (
                expected_t,
                expected_ct,
            ):
                issues.append(_fatal("advantage_victim_team_mismatch", 1, 0))

        for team_round in analytics.team_rounds:
            if (
                team_round.traded_deaths is not None
                and team_round.untraded_deaths is not None
                and team_round.traded_deaths + team_round.untraded_deaths != team_round.deaths
            ):
                issues.append(
                    _fatal(
                        "team_trade_death_sum_mismatch",
                        team_round.traded_deaths + team_round.untraded_deaths,
                        team_round.deaths,
                    )
                )

        if analytics.availability.win_conversion_metrics.status is AnalyticsAvailability.AVAILABLE:
            wins = sum(item.round_won is True for item in analytics.team_rounds)
            if wins != analytics.summary.winner_covered_rounds:
                issues.append(
                    _fatal(
                        "team_round_win_coverage_mismatch",
                        wins,
                        analytics.summary.winner_covered_rounds,
                    )
                )
        else:
            if any(
                item.opening_kill_round_wins is not None
                or item.opening_kill_conversion_percentage is not None
                for item in analytics.player_matches
            ):
                issues.append(_fatal("opening_conversion_without_winner", 1, 0))
            if any(
                item.round_won is not None
                or item.opening_kill_converted is not None
                or item.recovered_after_opening_death is not None
                or item.converted_first_advantage is not None
                or item.recovered_after_first_disadvantage is not None
                or item.converted_plus_two is not None
                or item.post_plant_won is not None
                for item in analytics.team_rounds
            ):
                issues.append(_fatal("team_conversion_without_winner", 1, 0))
            if any(
                item.round_wins is not None
                or item.opening_conversion_percentage is not None
                or item.opening_death_recovery_percentage is not None
                or item.first_advantage_conversion_percentage is not None
                or item.first_disadvantage_recovery_percentage is not None
                or item.plus_two_conversion_percentage is not None
                or item.post_plant_conversion_percentage is not None
                for item in analytics.team_matches
            ):
                issues.append(_fatal("match_conversion_without_winner", 1, 0))

        if analytics.availability.trade_metrics.status is AnalyticsAvailability.UNAVAILABLE:
            if any(
                item.traded_kills is not None
                or item.traded_deaths is not None
                or item.trade_opportunities is not None
                or item.successful_trades is not None
                or item.kast_t is not None
                or item.kast is not None
                for item in analytics.player_rounds
            ):
                issues.append(_fatal("round_trade_metric_serialized_when_unavailable", 1, 0))
            if any(
                item.trade_success_percentage is not None
                or item.traded_kills is not None
                or item.traded_deaths is not None
                or item.kast_rounds is not None
                or item.kast_percentage is not None
                or item.kast_t_rounds is not None
                for item in analytics.player_matches
            ):
                issues.append(_fatal("trade_metric_serialized_when_unavailable", 1, 0))
            if any(
                item.trade_opportunities is not None
                or item.successful_trades is not None
                or item.traded_deaths is not None
                or item.untraded_deaths is not None
                for item in analytics.team_rounds
            ):
                issues.append(_fatal("team_trade_metric_serialized_when_unavailable", 1, 0))
            if any(
                item.trade_opportunities is not None
                or item.successful_trades is not None
                or item.trade_percentage is not None
                or item.traded_deaths is not None
                or item.untraded_deaths is not None
                for item in analytics.team_matches
            ):
                issues.append(_fatal("team_match_trade_serialized_when_unavailable", 1, 0))

        return tuple(
            sorted(
                issues,
                key=lambda item: (
                    item.severity.value,
                    item.code,
                    item.entity_type,
                    item.entity_id or "",
                ),
            )
        )


def _fatal(code: str, actual: int, expected: int) -> AnalyticsValidationIssue:
    return AnalyticsValidationIssue(
        code=code,
        severity=ValidationSeverity.ERROR,
        is_fatal=True,
        entity_type="analytics",
        message=code.replace("_", " ").capitalize() + ".",
        evidence={"actual": actual, "expected": expected},
    )
