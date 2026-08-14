"""Application services for deterministic per-round tactical facts."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType, TeamEconomySnapshot
from stratweb.exceptions import (
    MatchNotFoundError,
    RoundFeatureConfigurationError,
    RoundFeatureNotFoundError,
)
from stratweb.features.engine import RoundFeatureEngine, RoundFeatureMatchInput
from stratweb.features.models import (
    ROUND_FEATURE_RULE_VERSION,
    ROUND_FEATURE_SCHEMA_VERSION,
    DeleteRoundFeaturesResult,
    FeatureAvailability,
    RoundFeature,
    RoundFeatureComputeResult,
    RoundFeatureConfig,
    RoundFeatureRunRecord,
    RoundFeatureRunSummary,
    RoundFeatureType,
)
from stratweb.ports import (
    AnalyticsRepository,
    EconomyRepository,
    MatchRepository,
    RoundFeatureRepository,
    SpatialRepository,
    TemporalRepository,
    ZoneAssignmentRepository,
)
from stratweb.spatial.models import SpatialSnapshot
from stratweb.zones.assignment_models import ZoneAssignment
from stratweb.zones.definitions import zone_set_for

_PAGE_SIZE = 5000


class ComputeRoundFeaturesService:
    def __init__(
        self,
        match_repository: MatchRepository,
        analytics_repository: AnalyticsRepository,
        temporal_repository: TemporalRepository,
        spatial_repository: SpatialRepository,
        zone_repository: ZoneAssignmentRepository,
        feature_repository: RoundFeatureRepository,
        *,
        economy_repository: EconomyRepository | None = None,
        engine: RoundFeatureEngine | None = None,
    ) -> None:
        self._matches = match_repository
        self._analytics = analytics_repository
        self._temporal = temporal_repository
        self._spatial = spatial_repository
        self._zones = zone_repository
        self._features = feature_repository
        self._economy = economy_repository
        self._engine = engine or RoundFeatureEngine()

    def compute(
        self,
        match_id: UUID,
        *,
        config: RoundFeatureConfig | None = None,
        replace: bool = False,
    ) -> RoundFeatureComputeResult:
        started = perf_counter()
        selected_config = config or RoundFeatureConfig()
        match = self._matches.get_match(match_id)
        if match is None:
            raise MatchNotFoundError(f"Match not found: {match_id}")
        analytics = self._analytics.get_summary(match_id)
        temporal = self._temporal.get_summary(match_id)
        spatial = self._spatial.get_summary(match_id)
        zones = self._zones.get_summary(match_id)
        missing = tuple(
            name
            for name, value in (
                ("analytics", analytics),
                ("temporal", temporal),
                ("spatial", spatial),
                ("zones", zones),
            )
            if value is None
        )
        if missing:
            raise RoundFeatureConfigurationError(
                "Stage 8.4 requires compatible input runs: " + ", ".join(missing)
            )
        assert analytics is not None
        assert temporal is not None
        assert spatial is not None
        assert zones is not None
        economy = self._economy.get_summary(match_id) if self._economy is not None else None
        rounds = self._matches.get_rounds(match_id)
        events = {}
        round_analytics = {}
        timelines = {}
        snapshots: list[SpatialSnapshot] = []
        assignments: list[ZoneAssignment] = []
        economy_snapshots: list[TeamEconomySnapshot] = []
        for round_item in rounds:
            if round_item.is_warmup or (
                not selected_config.include_incomplete_rounds and not round_item.is_complete
            ):
                continue
            round_events = self._matches.get_round_events(match_id, round_item.round_number)
            if round_events is not None:
                events[round_item.round_number] = round_events
            analytics_view = self._analytics.get_round_analytics_for_run(
                match_id,
                analytics.analytics_fingerprint,
                round_item.round_number,
            )
            if analytics_view is not None:
                round_analytics[round_item.round_number] = analytics_view
            timeline = self._temporal.get_round_timeline_for_run(
                match_id,
                temporal.temporal_run_id,
                round_item.round_number,
            )
            if timeline is not None:
                timelines[round_item.round_number] = timeline
            snapshots.extend(
                self._all_spatial_snapshots(
                    match_id,
                    spatial.spatial_run_id,
                    round_item.round_number,
                )
            )
            assignments.extend(
                self._all_zone_assignments(
                    match_id,
                    zones.zone_assignment_run_id,
                    round_item.round_number,
                )
            )
            if economy is not None and self._economy is not None:
                economy_snapshots.extend(
                    self._economy.list_team_snapshots(
                        match_id,
                        economy_run_id=economy.economy_run_id,
                        round_number=round_item.round_number,
                        limit=100,
                    )
                )
        zone_set = (
            zone_set_for(zones.canonical_map_name, zones.selected_map_revision)
            if zones.canonical_map_name is not None and zones.selected_map_revision is not None
            else None
        )
        state = self._engine.compute(
            RoundFeatureMatchInput(
                match_id=match_id,
                dataset_fingerprint=match.dataset_fingerprint,
                map_name=match.map_name or "unknown",
                rounds=rounds,
                events=events,
                analytics=analytics,
                round_analytics=round_analytics,
                temporal=temporal,
                timelines=timelines,
                spatial=spatial,
                snapshots=tuple(snapshots),
                zones=zones,
                assignments=tuple(assignments),
                zone_set=zone_set,
                economy=economy,
                economy_snapshots=tuple(economy_snapshots),
            ),
            selected_config,
        )
        saved = self._features.save_features(state, replace=replace)
        return RoundFeatureComputeResult(
            feature_run_id=saved.feature_run_id,
            feature_fingerprint=saved.feature_fingerprint,
            feature_schema_version=ROUND_FEATURE_SCHEMA_VERSION,
            feature_rule_version=ROUND_FEATURE_RULE_VERSION,
            match_id=match_id,
            status=saved.status,
            summary=state.summary,
            capabilities=state.capabilities,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
        )

    def _all_spatial_snapshots(
        self, match_id: UUID, spatial_run_id: UUID, round_number: int
    ) -> tuple[SpatialSnapshot, ...]:
        result: list[SpatialSnapshot] = []
        offset = 0
        while True:
            page = self._spatial.list_snapshots(
                match_id,
                spatial_run_id=spatial_run_id,
                round_number=round_number,
                limit=_PAGE_SIZE,
                offset=offset,
            )
            result.extend(page)
            if len(page) < _PAGE_SIZE:
                return tuple(result)
            offset += len(page)

    def _all_zone_assignments(
        self, match_id: UUID, zone_assignment_run_id: UUID, round_number: int
    ) -> tuple[ZoneAssignment, ...]:
        result: list[ZoneAssignment] = []
        offset = 0
        while True:
            page = self._zones.list_assignments(
                match_id,
                zone_assignment_run_id=zone_assignment_run_id,
                round_number=round_number,
                limit=_PAGE_SIZE,
                offset=offset,
            )
            result.extend(page)
            if len(page) < _PAGE_SIZE:
                return tuple(result)
            offset += len(page)


class RoundFeatureQueryService:
    def __init__(self, repository: RoundFeatureRepository) -> None:
        self._repository = repository

    def get_summary(
        self, match_id: UUID, *, feature_run_id: UUID | None = None
    ) -> RoundFeatureRunSummary:
        value = (
            self._repository.get_summary_for_run(match_id, feature_run_id)
            if feature_run_id is not None
            else self._repository.get_summary(match_id)
        )
        if value is None:
            raise RoundFeatureNotFoundError(
                f"Per-round feature run not found for match: {match_id}"
            )
        return value

    def list_runs(self, match_id: UUID) -> tuple[RoundFeatureRunRecord, ...]:
        return self._repository.list_runs(match_id)

    def list_features(
        self,
        match_id: UUID,
        *,
        feature_run_id: UUID | None = None,
        round_number: int | None = None,
        team_id: UUID | None = None,
        side: Side | None = None,
        feature_type: RoundFeatureType | None = None,
        availability: FeatureAvailability | None = None,
        buy_type: BuyType | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[RoundFeature, ...]:
        self.get_summary(match_id, feature_run_id=feature_run_id)
        return self._repository.list_features(
            match_id,
            feature_run_id=feature_run_id,
            round_number=round_number,
            team_id=team_id,
            side=side,
            feature_type=feature_type,
            availability=availability,
            buy_type=buy_type,
            limit=limit,
            offset=offset,
        )

    def delete(self, match_id: UUID) -> DeleteRoundFeaturesResult:
        runs = self._repository.delete_features(match_id)
        return DeleteRoundFeaturesResult(
            match_id=match_id,
            deleted=runs > 0,
            deleted_runs=runs,
        )


__all__ = ["ComputeRoundFeaturesService", "RoundFeatureQueryService"]
