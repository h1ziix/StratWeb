"""Application services joining canonical persistence to pure analytics."""

from __future__ import annotations

from math import isfinite
from time import perf_counter
from uuid import UUID

from stratweb.analytics.engine import AnalyticsEngine
from stratweb.analytics.models import (
    DEFAULT_TRADE_WINDOW_TICKS,
    AnalyticsComputeResult,
    AnalyticsConfig,
    AnalyticsRunSummary,
    DeleteAnalyticsResult,
    ManAdvantageTransition,
    MatchAnalyticsInput,
    OpeningDuel,
    PlayerMatchAnalytics,
    RoundAnalyticsView,
    TeamMatchAnalytics,
    TickrateEvidence,
    TradeEvent,
    TradeWindowConfig,
)
from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalKill,
    CanonicalShot,
)
from stratweb.exceptions import (
    AnalyticsConfigurationError,
    AnalyticsIntegrityError,
    AnalyticsNotFoundError,
    MatchNotFoundError,
)
from stratweb.ports import AnalyticsRepository, MatchRepository


class ComputeMatchAnalyticsService:
    """Load typed canonical entities, compute V1 metrics and persist one run."""

    def __init__(
        self,
        match_repository: MatchRepository,
        analytics_repository: AnalyticsRepository,
        engine: AnalyticsEngine | None = None,
    ) -> None:
        self._matches = match_repository
        self._analytics = analytics_repository
        self._engine = engine or AnalyticsEngine()

    def compute(
        self,
        match_id: UUID,
        *,
        config: AnalyticsConfig | None = None,
        replace: bool = False,
    ) -> AnalyticsComputeResult:
        started = perf_counter()
        source = self._load_input(match_id)
        result = self._engine.compute(source, config)
        fatal = tuple(issue for issue in result.validation_issues if issue.is_fatal)
        if fatal:
            codes = ", ".join(issue.code for issue in fatal)
            raise AnalyticsIntegrityError(
                f"Analytics validation found structural contradictions: {codes}."
            )
        saved = self._analytics.save_analytics(result, replace=replace)
        return AnalyticsComputeResult(
            match_id=match_id,
            dataset_fingerprint=source.dataset_fingerprint,
            analytics_fingerprint=saved.analytics_fingerprint,
            status=saved.status,
            row_counts=saved.row_counts,
            config=result.config,
            availability=result.availability,
            warnings=result.warnings,
            duration_seconds=perf_counter() - started,
        )

    def _load_input(self, match_id: UUID) -> MatchAnalyticsInput:
        match = self._matches.get_match(match_id)
        if match is None:
            raise MatchNotFoundError(f"Canonical match not found: {match_id}")
        rounds = self._matches.get_rounds(match_id)
        kills: list[CanonicalKill] = []
        damages: list[CanonicalDamage] = []
        shots: list[CanonicalShot] = []
        bomb_events: list[CanonicalBombEvent] = []
        for round_item in rounds:
            events = self._matches.get_round_events(match_id, round_item.round_number)
            if events is None:
                continue
            kills.extend(events.kills)
            damages.extend(events.damages)
            shots.extend(events.shots)
            bomb_events.extend(events.bomb_events)
        return MatchAnalyticsInput(
            match_id=match_id,
            dataset_fingerprint=match.dataset_fingerprint,
            teams=tuple(
                sorted(self._matches.get_teams(match_id), key=lambda item: str(item.team_id))
            ),
            players=tuple(
                sorted(self._matches.get_players(match_id), key=lambda item: str(item.player_id))
            ),
            memberships=tuple(
                sorted(
                    self._matches.get_memberships(match_id),
                    key=lambda item: (
                        item.valid_from_tick,
                        item.valid_to_tick if item.valid_to_tick is not None else 2**63 - 1,
                        str(item.player_id),
                        str(item.team_id),
                    ),
                )
            ),
            rounds=tuple(sorted(rounds, key=lambda item: (item.round_number, str(item.round_id)))),
            kills=tuple(sorted(kills, key=_event_key)),
            damages=tuple(sorted(damages, key=_event_key)),
            shots=tuple(sorted(shots, key=_event_key)),
            bomb_events=tuple(sorted(bomb_events, key=_event_key)),
        )


class AnalyticsQueryService:
    """Read-only, deterministically ordered analytics queries."""

    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository

    def get_analytics_summary(self, match_id: UUID) -> AnalyticsRunSummary:
        result = self._repository.get_summary(match_id)
        if result is None:
            raise AnalyticsNotFoundError(f"Analytics run not found for match: {match_id}")
        return result

    def list_player_stats(self, match_id: UUID) -> tuple[PlayerMatchAnalytics, ...]:
        self.get_analytics_summary(match_id)
        return self._repository.list_player_stats(match_id)

    def get_player_stats(self, match_id: UUID, player_id: UUID) -> PlayerMatchAnalytics:
        self.get_analytics_summary(match_id)
        result = self._repository.get_player_stats(match_id, player_id)
        if result is None:
            raise AnalyticsNotFoundError(
                f"Player analytics not found for match {match_id}: {player_id}"
            )
        return result

    def list_team_stats(self, match_id: UUID) -> tuple[TeamMatchAnalytics, ...]:
        self.get_analytics_summary(match_id)
        return self._repository.list_team_stats(match_id)

    def get_round_analytics(self, match_id: UUID, round_number: int) -> RoundAnalyticsView:
        self.get_analytics_summary(match_id)
        result = self._repository.get_round_analytics(match_id, round_number)
        if result is None:
            raise AnalyticsNotFoundError(
                f"Round analytics not found for match {match_id}: {round_number}"
            )
        return result

    def list_opening_duels(self, match_id: UUID) -> tuple[OpeningDuel, ...]:
        self.get_analytics_summary(match_id)
        return self._repository.list_opening_duels(match_id)

    def list_trade_events(
        self, match_id: UUID, round_number: int | None = None
    ) -> tuple[TradeEvent, ...]:
        self.get_analytics_summary(match_id)
        return self._repository.list_trade_events(match_id, round_number)

    def get_man_advantage_timeline(
        self, match_id: UUID, round_number: int
    ) -> tuple[ManAdvantageTransition, ...]:
        self.get_round_analytics(match_id, round_number)
        return self._repository.get_man_advantage_timeline(match_id, round_number)

    def delete_analytics(self, match_id: UUID) -> DeleteAnalyticsResult:
        summary = self._repository.get_summary(match_id)
        return DeleteAnalyticsResult(
            analytics_fingerprint=(summary.analytics_fingerprint if summary is not None else None),
            deleted=self._repository.delete_analytics(match_id),
        )


def _event_key(
    item: CanonicalKill | CanonicalDamage | CanonicalShot | CanonicalBombEvent,
) -> tuple[int, int, str]:
    return item.round_number if item.round_number is not None else -1, item.tick, str(item.event_id)


def resolve_analytics_config(
    *,
    requested_ticks: int | None,
    requested_seconds: float | None,
    tickrate_evidence: TickrateEvidence | None,
) -> AnalyticsConfig:
    """Resolve one explicit policy without inventing timing metadata."""

    if requested_ticks is not None and requested_seconds is not None:
        raise AnalyticsConfigurationError("Trade-window ticks and seconds are mutually exclusive.")
    if requested_ticks is not None and requested_ticks <= 0:
        raise AnalyticsConfigurationError("Trade-window ticks must be greater than zero.")
    if requested_seconds is not None and (
        not isfinite(requested_seconds) or requested_seconds <= 0
    ):
        raise AnalyticsConfigurationError("Trade-window seconds must be a positive finite value.")
    if requested_seconds is not None:
        if tickrate_evidence is None:
            raise AnalyticsConfigurationError(
                "Seconds trade-window mode requires proven canonical tickrate metadata; "
                "this dataset does not provide it."
            )
        if tickrate_evidence.conflicting_sources:
            sources = ", ".join(
                sorted({tickrate_evidence.source, *tickrate_evidence.conflicting_sources})
            )
            raise AnalyticsConfigurationError(
                f"Seconds trade-window mode cannot resolve conflicting tickrate "
                f"evidence: {sources}."
            )
        return AnalyticsConfig(
            trade_window=TradeWindowConfig.seconds(
                requested_seconds,
                tickrate=tickrate_evidence.tickrate,
                tickrate_source=tickrate_evidence.source,
            )
        )
    ticks = DEFAULT_TRADE_WINDOW_TICKS if requested_ticks is None else requested_ticks
    return AnalyticsConfig(trade_window=TradeWindowConfig.ticks(ticks))
