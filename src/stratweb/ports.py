"""Hexagonal ports defining the MVP module boundaries."""

from __future__ import annotations

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
from stratweb.domain.models import AnalysisFinding, DemoFile

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
class ImportJobRepository(Protocol):
    """Durable checkpoint store for the local completed-demo import queue."""

    def initialize(self) -> tuple[int, ...]: ...

    def create(self, record: ImportJobRecord) -> None: ...

    def get(self, job_id: UUID) -> ImportJobRecord | None: ...

    def update(self, record: ImportJobRecord) -> None: ...

    def list_unfinished(self) -> tuple[ImportJobRecord, ...]: ...

    def list_recent(self, limit: int = 20) -> tuple[ImportJobRecord, ...]: ...


@runtime_checkable
class OpponentRepository(Protocol):
    """Persistence boundary for user-confirmed opponent profiles and match teams."""

    def initialize(self) -> tuple[int, ...]: ...

    def create_profile(self, profile: OpponentProfile) -> None: ...

    def get_profile(self, profile_id: UUID) -> OpponentProfile | None: ...

    def list_profiles(self) -> tuple[OpponentProfile, ...]: ...

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
