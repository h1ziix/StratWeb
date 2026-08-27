"""Hexagonal ports defining the MVP module boundaries."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol, runtime_checkable
from uuid import UUID

from stratweb.contracts import (
    AnalysisConfiguration,
    AnalysisDataset,
    ParsedDemo,
    ParseRequest,
    ParserIdentity,
    ReportArtifact,
    ReportRequest,
    StoredDemoFile,
    UploadReceipt,
)
from stratweb.domain.enums import Side
from stratweb.domain.models import DemoFile
from stratweb.findings.models import AnalysisFinding

if TYPE_CHECKING:
    from stratweb.analytics.models import (
        AnalyticsRunSummary,
        AnalyticsSaveResult,
        ManAdvantageTransition,
        MatchAnalytics,
        OpeningDuel,
        PlayerMatchAnalytics,
        RoundAnalyticsView,
        TeamMatchAnalytics,
        TradeEvent,
    )
    from stratweb.application.analyst_notes import AnalystNote
    from stratweb.application.canonical_models import (
        CanonicalGrenade,
        CanonicalKill,
        CanonicalMatchDataset,
        CanonicalPlayer,
        CanonicalRound,
        CanonicalTeam,
        PlayerTeamMembership,
        ValidationIssue,
    )
    from stratweb.application.import_batch_models import ImportBatchItem, ImportBatchRecord
    from stratweb.application.import_job_models import ImportJobRecord
    from stratweb.application.opponent_models import (
        OpponentMatchSelection,
        OpponentProfile,
    )
    from stratweb.application.persistence_models import (
        MatchImportSummary,
        MatchQueryFilters,
        RepositorySaveResult,
        RoundEvents,
        StoredMatch,
    )
    from stratweb.application.team_names import TeamDisplayLabel, TeamNameSource
    from stratweb.counter_strategy.models import (
        CounterStrategyCategory,
        CounterStrategyRecommendation,
        CounterStrategyRun,
        CounterStrategyRunRecord,
        CounterStrategyRunSummary,
        CounterStrategySaveResult,
        SkippedStrategyFinding,
    )
    from stratweb.economy.models import (
        BuyType,
        EconomyExtraction,
        EconomyRunRecord,
        EconomyRunSummary,
        EconomySaveResult,
        EconomyState,
        PlayerEquipmentSnapshot,
        TeamEconomySnapshot,
    )
    from stratweb.features.models import (
        FeatureAvailability,
        RoundFeature,
        RoundFeatureRunRecord,
        RoundFeatureRunSummary,
        RoundFeatureSaveResult,
        RoundFeatureState,
        RoundFeatureType,
    )
    from stratweb.findings.models import (
        AnalysisRun,
        AnalysisRunRecord,
        AnalysisRunSummary,
        AnalysisSaveResult,
        EvidenceReference,
        FindingCategory,
    )
    from stratweb.patterns.models import (
        CrossMatchPattern,
        PatternAvailability,
        PatternRunInputRecord,
        PatternRunRecord,
        PatternRunSummary,
        PatternSaveResult,
        PatternState,
        PatternType,
    )
    from stratweb.spatial.models import (
        BombPositionSnapshot,
        SpatialExtraction,
        SpatialMatchState,
        SpatialRunRecord,
        SpatialRunSummary,
        SpatialSaveResult,
        SpatialSnapshot,
        SpatialValidationIssue,
    )
    from stratweb.spatial.projectiles import (
        ProjectileSnapshot,
        SpatialProjectile,
        UtilityEffect,
    )
    from stratweb.statistical_trust.models import (
        StatisticalTrustAssessment,
        StatisticalTrustRun,
        StatisticalTrustRunRecord,
        StatisticalTrustRunSummary,
        StatisticalTrustSaveResult,
        TrustDecision,
    )
    from stratweb.tactical_v2.models import (
        TacticalEvidenceReference,
        TacticalInsight,
        TacticalInsightType,
        TacticalV2Input,
        TacticalV2Run,
        TacticalV2RunRecord,
        TacticalV2RunSummary,
        TacticalV2SaveResult,
    )
    from stratweb.temporal.models import (
        BombTransition,
        ParticipantRoundState,
        RoundTimeline,
        SimultaneousEventGroup,
        TemporalEvent,
        TemporalMatchState,
        TemporalRunRecord,
        TemporalRunSummary,
        TemporalSaveResult,
        TemporalTransition,
    )
    from stratweb.zones.assignment_models import (
        ZoneAssignment,
        ZoneAssignmentRunRecord,
        ZoneAssignmentRunSummary,
        ZoneAssignmentSaveResult,
        ZoneAssignmentState,
        ZoneAssignmentStatus,
    )


@runtime_checkable
class DemoFileStorage(Protocol):
    """Streams one .dem into private storage and computes SHA-256 while writing."""

    def store(
        self,
        source: BinaryIO,
        *,
        original_filename: str,
        max_bytes: int,
    ) -> StoredDemoFile: ...

    def delete(self, storage_key: str) -> None: ...

    def resolve(self, storage_key: str) -> Path: ...


@runtime_checkable
class DemoFileCatalog(Protocol):
    """Registers uploads, detects SHA-256 duplicates and tracks per-file failures."""

    def register(self, stored: StoredDemoFile) -> UploadReceipt: ...

    def get(self, demo_file_id: UUID) -> DemoFile | None: ...

    def find_by_sha256(self, sha256: str) -> DemoFile | None: ...

    def mark_parsing(self, demo_file_id: UUID, parser: ParserIdentity) -> None: ...

    def mark_parsed(self, demo_file_id: UUID) -> None: ...

    def mark_failed(self, demo_file_id: UUID, *, code: str, message: str) -> None: ...


@runtime_checkable
class DemoParser(Protocol):
    """Adapter boundary around any completed-demo parser implementation."""

    @property
    def identity(self) -> ParserIdentity: ...

    def parse(self, request: ParseRequest) -> ParsedDemo: ...


@runtime_checkable
class SpatialExtractor(Protocol):
    """Extract sampled spatial source rows only at Temporal-requested ticks."""

    def extract(
        self,
        demo_path: Path,
        ticks: tuple[int, ...],
        *,
        expected_sha256: str,
    ) -> SpatialExtraction: ...


@runtime_checkable
class EconomyExtractor(Protocol):
    """Extract documented equipment fields at canonical freeze-end ticks."""

    def extract(
        self,
        demo_path: Path,
        ticks: tuple[int, ...],
        *,
        expected_sha256: str,
    ) -> EconomyExtraction: ...


@runtime_checkable
class EventNormalizer(Protocol):
    """Maps raw parser columns/events to the versioned canonical schema."""

    @property
    def schema_version(self) -> str: ...

    def normalize(
        self,
        parsed: ParsedDemo,
        *,
        source_demo_sha256: str,
    ) -> CanonicalMatchDataset: ...


@runtime_checkable
class MatchRepository(Protocol):
    """Persistence boundary for one complete canonical match dataset."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_match(
        self,
        dataset: CanonicalMatchDataset,
        *,
        source_original_name: str | None = None,
        replace: bool = False,
    ) -> RepositorySaveResult: ...

    def match_exists(self, match_id: UUID) -> bool: ...

    def get_match(self, match_id: UUID) -> StoredMatch | None: ...

    def get_match_by_fingerprint(self, fingerprint: str) -> StoredMatch | None: ...

    def list_matches(self, filters: MatchQueryFilters) -> tuple[StoredMatch, ...]: ...

    def delete_match(self, match_id: UUID) -> bool: ...

    def get_import_summary(self, match_id: UUID) -> MatchImportSummary | None: ...

    def get_players(self, match_id: UUID) -> tuple[CanonicalPlayer, ...]: ...

    def get_teams(self, match_id: UUID) -> tuple[CanonicalTeam, ...]: ...

    def get_memberships(self, match_id: UUID) -> tuple[PlayerTeamMembership, ...]: ...

    def get_rounds(self, match_id: UUID) -> tuple[CanonicalRound, ...]: ...

    def get_round_events(self, match_id: UUID, round_number: int) -> RoundEvents | None: ...

    def get_player_kills(self, match_id: UUID, player_id: UUID) -> tuple[CanonicalKill, ...]: ...

    def get_player_grenades(
        self, match_id: UUID, player_id: UUID
    ) -> tuple[CanonicalGrenade, ...]: ...

    def get_validation_issues(self, match_id: UUID) -> tuple[ValidationIssue, ...]: ...

    def get_table_counts(self, match_id: UUID) -> dict[str, int]: ...


@runtime_checkable
class TeamNameRepository(Protocol):
    """User-facing aliases, separate from immutable canonical team identity."""

    def list_for_match(self, match_id: UUID) -> tuple[TeamDisplayLabel, ...]: ...

    def save(
        self,
        match_id: UUID,
        team_id: UUID,
        display_name: str,
        *,
        source: TeamNameSource,
        source_reference: str | None = None,
    ) -> TeamDisplayLabel: ...

    def delete(self, match_id: UUID, team_id: UUID) -> bool: ...


@runtime_checkable
class ImportJobRepository(Protocol):
    """Durable checkpoint store for the local completed-demo import queue."""

    def initialize(self) -> tuple[int, ...]: ...

    def create(self, record: ImportJobRecord) -> None: ...

    def get(self, job_id: UUID) -> ImportJobRecord | None: ...

    def update(self, record: ImportJobRecord) -> None: ...

    def list_unfinished(self) -> tuple[ImportJobRecord, ...]: ...

    def list_recent(self, limit: int = 20) -> tuple[ImportJobRecord, ...]: ...

    def find_by_sha256(self, sha256: str) -> ImportJobRecord | None: ...


@runtime_checkable
class ImportBatchRepository(Protocol):
    """Durable grouping above independent import jobs."""

    def initialize(self) -> tuple[int, ...]: ...

    def create(self, record: ImportBatchRecord) -> None: ...

    def add_item(self, item: ImportBatchItem) -> None: ...

    def get(self, batch_id: UUID) -> ImportBatchRecord | None: ...

    def list_items(self, batch_id: UUID) -> tuple[ImportBatchItem, ...]: ...

    def list_recent(self, limit: int = 10) -> tuple[ImportBatchRecord, ...]: ...


@runtime_checkable
class OpponentRepository(Protocol):
    """Persistence boundary for user-confirmed opponent profiles and match teams."""

    def initialize(self) -> tuple[int, ...]: ...

    def create_profile(self, profile: OpponentProfile) -> None: ...

    def get_profile(self, profile_id: UUID) -> OpponentProfile | None: ...

    def list_profiles(self) -> tuple[OpponentProfile, ...]: ...

    def rename_profile(self, profile_id: UUID, display_name: str, updated_at: datetime) -> None: ...

    def delete_profile(self, profile_id: UUID) -> bool: ...

    def save_selection(self, selection: OpponentMatchSelection) -> None: ...

    def list_selections(self, profile_id: UUID) -> tuple[OpponentMatchSelection, ...]: ...

    def remove_selection(self, profile_id: UUID, match_id: UUID) -> bool: ...


@runtime_checkable
class AnalyticsRepository(Protocol):
    """Persistence boundary for derived analytics runs, separate from canonical data."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_analytics(
        self, analytics: MatchAnalytics, *, replace: bool = False
    ) -> AnalyticsSaveResult: ...

    def get_summary(self, match_id: UUID) -> AnalyticsRunSummary | None: ...

    def list_player_stats(self, match_id: UUID) -> tuple[PlayerMatchAnalytics, ...]: ...

    def get_player_stats(self, match_id: UUID, player_id: UUID) -> PlayerMatchAnalytics | None: ...

    def list_team_stats(self, match_id: UUID) -> tuple[TeamMatchAnalytics, ...]: ...

    def get_round_analytics(
        self, match_id: UUID, round_number: int
    ) -> RoundAnalyticsView | None: ...

    def get_round_analytics_for_run(
        self,
        match_id: UUID,
        analytics_fingerprint: str,
        round_number: int,
    ) -> RoundAnalyticsView | None: ...

    def list_opening_duels(self, match_id: UUID) -> tuple[OpeningDuel, ...]: ...

    def list_trade_events(
        self, match_id: UUID, round_number: int | None = None
    ) -> tuple[TradeEvent, ...]: ...

    def get_man_advantage_timeline(
        self, match_id: UUID, round_number: int
    ) -> tuple[ManAdvantageTransition, ...]: ...

    def delete_analytics(self, match_id: UUID) -> bool: ...


@runtime_checkable
class TemporalRepository(Protocol):
    """Persistence boundary for temporal runs, separate from canonical and analytics."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_temporal(
        self, state: TemporalMatchState, *, replace: bool = False
    ) -> TemporalSaveResult: ...

    def get_summary(self, match_id: UUID) -> TemporalRunSummary | None: ...

    def list_runs(self, match_id: UUID) -> tuple[TemporalRunRecord, ...]: ...

    def get_summary_for_run(
        self, match_id: UUID, temporal_run_id: UUID
    ) -> TemporalRunSummary | None: ...

    def get_round_timeline_for_run(
        self, match_id: UUID, temporal_run_id: UUID, round_number: int
    ) -> RoundTimeline | None: ...

    def find_event_for_run(
        self, match_id: UUID, temporal_run_id: UUID, event_id: UUID
    ) -> tuple[int, TemporalEvent] | None: ...

    def get_round_timeline(self, match_id: UUID, round_number: int) -> RoundTimeline | None: ...

    def list_round_events(self, match_id: UUID, round_number: int) -> tuple[TemporalEvent, ...]: ...

    def list_round_transitions(
        self, match_id: UUID, round_number: int
    ) -> tuple[TemporalTransition, ...]: ...

    def list_simultaneous_groups(
        self, match_id: UUID, round_number: int | None = None
    ) -> tuple[SimultaneousEventGroup, ...]: ...

    def get_simultaneous_group(
        self, match_id: UUID, group_id: UUID
    ) -> SimultaneousEventGroup | None: ...

    def list_round_participants(
        self, match_id: UUID, round_number: int
    ) -> tuple[ParticipantRoundState, ...]: ...

    def list_bomb_transitions(
        self, match_id: UUID, round_number: int
    ) -> tuple[BombTransition, ...]: ...

    def find_event(self, match_id: UUID, event_id: UUID) -> tuple[int, TemporalEvent] | None: ...

    def delete_temporal(self, match_id: UUID) -> bool: ...


@runtime_checkable
class SpatialRepository(Protocol):
    """Persistence boundary for versioned spatial runs."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_spatial(
        self, state: SpatialMatchState, *, replace: bool = False
    ) -> SpatialSaveResult: ...

    def get_summary(self, match_id: UUID) -> SpatialRunSummary | None: ...

    def get_summary_for_run(
        self, match_id: UUID, spatial_run_id: UUID
    ) -> SpatialRunSummary | None: ...

    def list_runs(self, match_id: UUID) -> tuple[SpatialRunRecord, ...]: ...

    def list_snapshots(
        self,
        match_id: UUID,
        *,
        round_number: int | None = None,
        participant_id: UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialSnapshot, ...]: ...

    def list_round_ticks(
        self,
        match_id: UUID,
        round_number: int,
        *,
        spatial_run_id: UUID | None = None,
    ) -> tuple[int, ...]: ...

    def get_tick_snapshots(
        self,
        match_id: UUID,
        round_number: int,
        tick: int,
        *,
        physical_team_id: UUID | None = None,
        participant_id: UUID | None = None,
        alive_only: bool = False,
        bomb_carrier_only: bool = False,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialSnapshot, ...]: ...

    def get_player_path(
        self,
        match_id: UUID,
        round_number: int,
        participant_id: UUID,
        *,
        reliable_alive_only: bool = True,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialSnapshot, ...]: ...

    def get_round_path(
        self,
        match_id: UUID,
        round_number: int,
        *,
        physical_team_id: UUID | None = None,
        participant_id: UUID | None = None,
        alive_only: bool = False,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialSnapshot, ...]: ...

    def get_bomb_position_at_tick(
        self,
        match_id: UUID,
        round_number: int,
        tick: int,
        *,
        spatial_run_id: UUID | None = None,
    ) -> BombPositionSnapshot | None: ...

    def get_playback_snapshots(
        self,
        match_id: UUID,
        round_number: int,
        ticks: tuple[int, ...],
        *,
        spatial_run_id: UUID,
    ) -> tuple[SpatialSnapshot, ...]: ...

    def get_playback_bomb_positions(
        self,
        match_id: UUID,
        round_number: int,
        ticks: tuple[int, ...],
        *,
        spatial_run_id: UUID,
    ) -> tuple[BombPositionSnapshot, ...]: ...

    def get_round_projectiles(
        self,
        match_id: UUID,
        round_number: int,
        *,
        spatial_run_id: UUID,
    ) -> tuple[SpatialProjectile, ...]: ...

    def get_playback_projectile_snapshots(
        self,
        match_id: UUID,
        round_number: int,
        start_tick: int,
        end_tick: int,
        *,
        spatial_run_id: UUID,
    ) -> tuple[ProjectileSnapshot, ...]: ...

    def get_playback_utility_effects(
        self,
        match_id: UUID,
        round_number: int,
        start_tick: int,
        end_tick: int,
        *,
        spatial_run_id: UUID,
    ) -> tuple[UtilityEffect, ...]: ...

    def list_bomb_positions(
        self, match_id: UUID, *, round_number: int | None = None
    ) -> tuple[BombPositionSnapshot, ...]: ...

    def list_validation_issues(self, match_id: UUID) -> tuple[SpatialValidationIssue, ...]: ...

    def delete_spatial(self, match_id: UUID) -> int: ...


@runtime_checkable
class ZoneAssignmentRepository(Protocol):
    """Persistence boundary for versioned point-to-zone evidence."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_zone_assignments(
        self, state: ZoneAssignmentState, *, replace: bool = False
    ) -> ZoneAssignmentSaveResult: ...

    def get_summary(self, match_id: UUID) -> ZoneAssignmentRunSummary | None: ...

    def get_summary_for_spatial_run(
        self, match_id: UUID, spatial_run_id: UUID
    ) -> ZoneAssignmentRunSummary | None: ...

    def get_summary_for_run(
        self, match_id: UUID, zone_assignment_run_id: UUID
    ) -> ZoneAssignmentRunSummary | None: ...

    def list_runs(self, match_id: UUID) -> tuple[ZoneAssignmentRunRecord, ...]: ...

    def list_assignments(
        self,
        match_id: UUID,
        *,
        zone_assignment_run_id: UUID | None = None,
        round_number: int | None = None,
        status: ZoneAssignmentStatus | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[ZoneAssignment, ...]: ...

    def get_assignments(
        self,
        zone_assignment_run_id: UUID,
        spatial_snapshot_ids: tuple[UUID, ...],
    ) -> tuple[ZoneAssignment, ...]: ...

    def delete_zone_assignments(self, match_id: UUID) -> int: ...


@runtime_checkable
class EconomyRepository(Protocol):
    """Persistence boundary for immutable freeze-end economy evidence."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_economy(self, state: EconomyState, *, replace: bool = False) -> EconomySaveResult: ...

    def get_summary(self, match_id: UUID) -> EconomyRunSummary | None: ...

    def get_summary_for_run(
        self, match_id: UUID, economy_run_id: UUID
    ) -> EconomyRunSummary | None: ...

    def list_runs(self, match_id: UUID) -> tuple[EconomyRunRecord, ...]: ...

    def list_team_snapshots(
        self,
        match_id: UUID,
        *,
        economy_run_id: UUID | None = None,
        round_number: int | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[TeamEconomySnapshot, ...]: ...

    def list_player_snapshots(
        self,
        match_id: UUID,
        *,
        economy_run_id: UUID | None = None,
        round_number: int | None = None,
        participant_id: UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[PlayerEquipmentSnapshot, ...]: ...

    def delete_economy(self, match_id: UUID) -> int: ...


@runtime_checkable
class RoundFeatureRepository(Protocol):
    """Persistence boundary for immutable, version-pinned per-round facts."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_features(
        self, state: RoundFeatureState, *, replace: bool = False
    ) -> RoundFeatureSaveResult: ...

    def get_summary(self, match_id: UUID) -> RoundFeatureRunSummary | None: ...

    def get_summary_for_run(
        self, match_id: UUID, feature_run_id: UUID
    ) -> RoundFeatureRunSummary | None: ...

    def list_runs(self, match_id: UUID) -> tuple[RoundFeatureRunRecord, ...]: ...

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
    ) -> tuple[RoundFeature, ...]: ...

    def delete_features(self, match_id: UUID) -> int: ...


@runtime_checkable
class PatternRepository(Protocol):
    """Persistence boundary for immutable cross-match pattern runs."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_patterns(self, state: PatternState, *, replace: bool = False) -> PatternSaveResult: ...

    def get_summary(self, profile_id: UUID) -> PatternRunSummary | None: ...

    def get_summary_for_run(
        self, profile_id: UUID, pattern_run_id: UUID
    ) -> PatternRunSummary | None: ...

    def list_runs(self, profile_id: UUID) -> tuple[PatternRunRecord, ...]: ...

    def list_inputs(
        self, profile_id: UUID, pattern_run_id: UUID
    ) -> tuple[PatternRunInputRecord, ...]: ...

    def list_patterns(
        self,
        profile_id: UUID,
        *,
        pattern_run_id: UUID | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        pattern_type: PatternType | None = None,
        availability: PatternAvailability | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[CrossMatchPattern, ...]: ...

    def delete_patterns(self, profile_id: UUID) -> int: ...


@runtime_checkable
class StatisticalTrustRepository(Protocol):
    """Persistence boundary for immutable Stage 9.4 trust assessments."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_trust(
        self, state: StatisticalTrustRun, *, replace: bool = False
    ) -> StatisticalTrustSaveResult: ...

    def get_summary(
        self, profile_id: UUID, *, source_pattern_run_id: UUID
    ) -> StatisticalTrustRunSummary | None: ...

    def get_summary_for_run(
        self, profile_id: UUID, trust_run_id: UUID
    ) -> StatisticalTrustRunSummary | None: ...

    def list_runs(
        self, profile_id: UUID, *, current_pattern_run_id: UUID | None
    ) -> tuple[StatisticalTrustRunRecord, ...]: ...

    def list_assessments(
        self,
        profile_id: UUID,
        *,
        trust_run_id: UUID,
        decision: TrustDecision | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[StatisticalTrustAssessment, ...]: ...

    def delete_trust(self, profile_id: UUID) -> int: ...


@runtime_checkable
class TacticalV2SourceRepository(Protocol):
    """Read boundary for an exact Stage 9.5 source lineage."""

    def initialize(self) -> tuple[int, ...]: ...

    def load_input(
        self, profile_id: UUID, selections: tuple[OpponentMatchSelection, ...]
    ) -> TacticalV2Input: ...


@runtime_checkable
class TacticalV2Repository(Protocol):
    """Persistence boundary for immutable Tactical Intelligence V2 runs."""

    def initialize(self) -> tuple[int, ...]: ...

    def save(self, state: TacticalV2Run, *, replace: bool = False) -> TacticalV2SaveResult: ...

    def get_summary(self, profile_id: UUID) -> TacticalV2RunSummary | None: ...

    def get_summary_for_run(
        self, profile_id: UUID, tactical_run_id: UUID
    ) -> TacticalV2RunSummary | None: ...

    def list_runs(self, profile_id: UUID) -> tuple[TacticalV2RunRecord, ...]: ...

    def list_insights(
        self,
        profile_id: UUID,
        *,
        tactical_run_id: UUID | None = None,
        insight_type: TacticalInsightType | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[TacticalInsight, ...]: ...

    def get_insight(
        self,
        profile_id: UUID,
        insight_id: UUID,
        *,
        tactical_run_id: UUID | None = None,
    ) -> TacticalInsight | None: ...

    def list_evidence(
        self, profile_id: UUID, insight_id: UUID, *, tactical_run_id: UUID | None = None
    ) -> tuple[TacticalEvidenceReference, ...]: ...

    def delete(self, profile_id: UUID) -> int: ...


@runtime_checkable
class AnalystNoteRepository(Protocol):
    """Local annotations pinned to immutable Tactical V2 observations."""

    def get(
        self, profile_id: UUID, tactical_run_id: UUID, insight_id: UUID
    ) -> AnalystNote | None: ...

    def save(
        self,
        profile_id: UUID,
        tactical_run_id: UUID,
        insight_id: UUID,
        body: str,
    ) -> AnalystNote: ...

    def delete(self, profile_id: UUID, tactical_run_id: UUID, insight_id: UUID) -> bool: ...


@runtime_checkable
class AnalysisRepository(Protocol):
    """Persistence boundary for immutable Stage 8.6 findings."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_analysis(self, state: AnalysisRun, *, replace: bool = False) -> AnalysisSaveResult: ...

    def get_summary(
        self, profile_id: UUID, *, source_pattern_run_id: UUID
    ) -> AnalysisRunSummary | None: ...

    def get_summary_for_run(
        self, profile_id: UUID, analysis_run_id: UUID
    ) -> AnalysisRunSummary | None: ...

    def list_runs(
        self, profile_id: UUID, *, current_pattern_run_id: UUID | None
    ) -> tuple[AnalysisRunRecord, ...]: ...

    def list_findings(
        self,
        profile_id: UUID,
        *,
        analysis_run_id: UUID,
        map_name: str | None = None,
        side: Side | None = None,
        category: FindingCategory | None = None,
        pattern_type: PatternType | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[AnalysisFinding, ...]: ...

    def get_finding(
        self, profile_id: UUID, analysis_run_id: UUID, finding_id: UUID
    ) -> AnalysisFinding | None: ...

    def list_evidence(
        self, analysis_run_id: UUID, finding_id: UUID
    ) -> tuple[EvidenceReference, ...]: ...

    def delete_analysis(self, profile_id: UUID) -> int: ...


@runtime_checkable
class CounterStrategyRepository(Protocol):
    """Persistence boundary for immutable Stage 8.7 recommendation runs."""

    @property
    def database_path(self) -> Path: ...

    def initialize(self) -> tuple[int, ...]: ...

    def save_strategy(
        self, state: CounterStrategyRun, *, replace: bool = False
    ) -> CounterStrategySaveResult: ...

    def get_summary(
        self, profile_id: UUID, *, source_analysis_run_id: UUID
    ) -> CounterStrategyRunSummary | None: ...

    def get_summary_for_run(
        self, profile_id: UUID, strategy_run_id: UUID
    ) -> CounterStrategyRunSummary | None: ...

    def list_runs(
        self, profile_id: UUID, *, current_analysis_run_id: UUID | None
    ) -> tuple[CounterStrategyRunRecord, ...]: ...

    def list_recommendations(
        self,
        profile_id: UUID,
        *,
        strategy_run_id: UUID,
        map_name: str | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        category: CounterStrategyCategory | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[CounterStrategyRecommendation, ...]: ...

    def get_recommendation(
        self, profile_id: UUID, strategy_run_id: UUID, recommendation_id: UUID
    ) -> CounterStrategyRecommendation | None: ...

    def list_skipped(self, strategy_run_id: UUID) -> tuple[SkippedStrategyFinding, ...]: ...

    def delete_strategies(self, profile_id: UUID) -> int: ...


@runtime_checkable
class Analyzer(Protocol):
    """Pure deterministic computation over an immutable dataset snapshot."""

    @property
    def version(self) -> str: ...

    def analyze(
        self,
        dataset: AnalysisDataset,
        configuration: AnalysisConfiguration,
    ) -> tuple[AnalysisFinding, ...]: ...


@runtime_checkable
class ReportGenerator(Protocol):
    """Renders already computed findings without inventing or changing statistics."""

    def generate(self, request: ReportRequest) -> ReportArtifact: ...
