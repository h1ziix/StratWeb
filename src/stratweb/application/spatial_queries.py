"""Indexed application queries for non-interpretive spatial exploration."""

from __future__ import annotations

from math import cos, dist, radians, sin
from uuid import UUID

from stratweb.analytics.models import OpeningDuel, TradeEvent
from stratweb.application.persistence_models import RoundEvents
from stratweb.application.playback import classify_motion
from stratweb.ports import (
    AnalyticsRepository,
    MatchRepository,
    SpatialRepository,
    TemporalRepository,
)
from stratweb.spatial.map_overviews import MapOverviewAsset, MapOverviewRegistry
from stratweb.spatial.models import SpatialRunSummary, SpatialSnapshot
from stratweb.spatial.projectiles import ProjectileSnapshot, SpatialProjectile, UtilityEffect
from stratweb.spatial.query_models import (
    EntityRenderStatus,
    MapProjection,
    MapViewDirection,
    NearestPlayer,
    NearestPlayersResult,
    PlaybackClockMetadata,
    PlaybackDiagnostics,
    PlaybackFilters,
    PlaybackNavigation,
    PlaybackSample,
    PlayerPath,
    ProjectileSnapshotView,
    SpatialEventMarker,
    SpatialEventMarkerKind,
    SpatialPlaybackChunk,
    SpatialPlayerView,
    SpatialTickSnapshot,
    TeamTickSnapshot,
    TickNavigation,
    TickResolutionStatus,
    UtilityEffectView,
)
from stratweb.temporal.models import RoundTimeline, TemporalEvent, TemporalEventKind


class SpatialExplorerService:
    def __init__(
        self,
        match_repository: MatchRepository,
        temporal_repository: TemporalRepository,
        spatial_repository: SpatialRepository,
        overview_registry: MapOverviewRegistry,
        *,
        analytics_repository: AnalyticsRepository | None = None,
    ) -> None:
        self._matches = match_repository
        self._temporal = temporal_repository
        self._spatial = spatial_repository
        self._overviews = overview_registry
        self._analytics = analytics_repository
        self._summary_cache: dict[tuple[UUID, UUID | None], SpatialRunSummary] = {}
        self._tick_cache: dict[tuple[UUID, UUID, int], tuple[int, ...]] = {}
        self._player_label_cache: dict[UUID, dict[UUID, str]] = {}
        self._team_label_cache: dict[UUID, dict[UUID, str]] = {}
        self._timeline_cache: dict[tuple[UUID, UUID, int], RoundTimeline | None] = {}
        self._opening_cache: dict[UUID, tuple[OpeningDuel, ...]] = {}
        self._trade_cache: dict[tuple[UUID, int], tuple[TradeEvent, ...]] = {}
        self._round_events_cache: dict[tuple[UUID, int], RoundEvents | None] = {}

    def list_round_ticks(
        self,
        match_id: UUID,
        round_number: int,
        *,
        spatial_run_id: UUID | None = None,
    ) -> tuple[int, ...]:
        summary = self._require_summary(match_id, spatial_run_id)
        key = (match_id, summary.spatial_run_id, round_number)
        if key not in self._tick_cache:
            self._tick_cache[key] = self._spatial.list_round_ticks(
                match_id,
                round_number,
                spatial_run_id=summary.spatial_run_id,
            )
        return self._tick_cache[key]

    def get_tick_snapshot(
        self,
        match_id: UUID,
        round_number: int,
        tick: int,
        *,
        physical_team_id: UUID | None = None,
        participant_id: UUID | None = None,
        alive_only: bool = False,
        bomb_carrier_only: bool = False,
        include_events: bool = True,
        spatial_run_id: UUID | None = None,
    ) -> SpatialTickSnapshot:
        summary = self._require_summary(match_id, spatial_run_id)
        ticks = self.list_round_ticks(
            match_id,
            round_number,
            spatial_run_id=summary.spatial_run_id,
        )
        navigation = _navigation(ticks, tick)
        overview = self._overviews.get_for_run(summary.map_model.map_name, summary.map_semantics)
        labels = self._player_labels(match_id)
        teams = self._team_labels(match_id)
        rows = (
            self._spatial.get_tick_snapshots(
                match_id,
                round_number,
                tick,
                physical_team_id=physical_team_id,
                participant_id=participant_id,
                alive_only=alive_only,
                bomb_carrier_only=bomb_carrier_only,
                spatial_run_id=summary.spatial_run_id,
            )
            if navigation.status is TickResolutionStatus.EXACT
            else ()
        )
        players = tuple(_player_view(row, labels, teams, overview) for row in rows)
        bomb = self._spatial.get_bomb_position_at_tick(
            match_id,
            round_number,
            tick,
            spatial_run_id=summary.spatial_run_id,
        )
        bomb_projection = overview.project(bomb.x, bomb.y, bomb.z) if bomb is not None else None
        marker_rows = rows
        if any(
            (
                physical_team_id is not None,
                participant_id is not None,
                alive_only,
                bomb_carrier_only,
            )
        ):
            marker_rows = self._spatial.get_tick_snapshots(
                match_id,
                round_number,
                tick,
                spatial_run_id=summary.spatial_run_id,
            )
        events = (
            self._event_markers(
                match_id,
                summary.temporal_run_id,
                round_number,
                tick,
                marker_rows,
                labels,
                overview,
            )
            if include_events and navigation.status is TickResolutionStatus.EXACT
            else ()
        )
        warnings: list[str] = []
        if navigation.status is TickResolutionStatus.UNAVAILABLE:
            warnings.append("no spatial snapshot exists at the requested authoritative tick")
        if overview.model.status.value != "available":
            warnings.extend(overview.model.warnings)
        return SpatialTickSnapshot(
            match_id=match_id,
            spatial_run_id=summary.spatial_run_id,
            temporal_run_id=summary.temporal_run_id,
            round_number=round_number,
            navigation=navigation,
            players=players,
            bomb_position=bomb,
            bomb_projection=bomb_projection,
            bomb_carrier_id=bomb.carrier_participant_id if bomb else None,
            events=events,
            overview=overview.model,
            warnings=tuple(warnings),
        )

    def get_team_snapshot(
        self,
        match_id: UUID,
        round_number: int,
        tick: int,
        team_id: UUID,
        *,
        spatial_run_id: UUID | None = None,
    ) -> TeamTickSnapshot:
        item = self.get_tick_snapshot(
            match_id,
            round_number,
            tick,
            physical_team_id=team_id,
            include_events=False,
            spatial_run_id=spatial_run_id,
        )
        return TeamTickSnapshot(
            match_id=match_id,
            spatial_run_id=item.spatial_run_id,
            temporal_run_id=item.temporal_run_id,
            round_number=round_number,
            tick=tick,
            team_id=team_id,
            team_name=self._team_labels(match_id).get(team_id, str(team_id)),
            players=item.players,
            overview=item.overview,
        )

    def get_player_path(
        self,
        match_id: UUID,
        round_number: int,
        participant_id: UUID,
        *,
        spatial_run_id: UUID | None = None,
    ) -> PlayerPath:
        summary = self._require_summary(match_id, spatial_run_id)
        overview = self._overviews.get_for_run(summary.map_model.map_name, summary.map_semantics)
        labels = self._player_labels(match_id)
        teams = self._team_labels(match_id)
        rows = self._spatial.get_player_path(
            match_id,
            round_number,
            participant_id,
            spatial_run_id=summary.spatial_run_id,
        )
        points = tuple(_player_view(row, labels, teams, overview) for row in rows)
        first = rows[0] if rows else None
        warnings = () if rows else ("no reliable alive-player path points are available",)
        return PlayerPath(
            match_id=match_id,
            spatial_run_id=summary.spatial_run_id,
            temporal_run_id=summary.temporal_run_id,
            round_number=round_number,
            participant_id=participant_id,
            player_name=labels.get(participant_id, str(participant_id)),
            team_id=first.physical_team_id if first else None,
            side=first.side if first else "UNKNOWN",
            points=points,
            overview=overview.model,
            warnings=warnings,
        )

    def get_round_path(
        self,
        match_id: UUID,
        round_number: int,
        *,
        physical_team_id: UUID | None = None,
        participant_id: UUID | None = None,
        alive_only: bool = False,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialPlayerView, ...]:
        summary = self._require_summary(match_id, spatial_run_id)
        overview = self._overviews.get_for_run(summary.map_model.map_name, summary.map_semantics)
        labels = self._player_labels(match_id)
        teams = self._team_labels(match_id)
        rows = self._spatial.get_round_path(
            match_id,
            round_number,
            physical_team_id=physical_team_id,
            participant_id=participant_id,
            alive_only=alive_only,
            spatial_run_id=summary.spatial_run_id,
        )
        return tuple(_player_view(row, labels, teams, overview) for row in rows)

    def nearest_players(
        self,
        match_id: UUID,
        round_number: int,
        tick: int,
        participant_id: UUID,
        *,
        alive_only: bool = False,
        limit: int = 9,
        spatial_run_id: UUID | None = None,
    ) -> NearestPlayersResult:
        summary = self._require_summary(match_id, spatial_run_id)
        rows = self._spatial.get_tick_snapshots(
            match_id,
            round_number,
            tick,
            alive_only=alive_only,
            spatial_run_id=summary.spatial_run_id,
        )
        source = next((row for row in rows if row.participant_id == participant_id), None)
        labels = self._player_labels(match_id)
        if source is None or None in (source.x, source.y, source.z):
            return NearestPlayersResult(
                match_id=match_id,
                round_number=round_number,
                tick=tick,
                source_participant_id=participant_id,
                players=(),
                warnings=("source participant has no position at the requested tick",),
            )
        source_position = (source.x, source.y, source.z)
        assert all(value is not None for value in source_position)
        candidates: list[NearestPlayer] = []
        for row in rows:
            if row.participant_id == participant_id or None in (row.x, row.y, row.z):
                continue
            position = (row.x, row.y, row.z)
            assert all(value is not None for value in position)
            candidates.append(
                NearestPlayer(
                    participant_id=row.participant_id,
                    player_name=labels.get(row.participant_id, str(row.participant_id)),
                    distance_world_units=dist(source_position, position),  # type: ignore[arg-type]
                    same_physical_team=(
                        source.physical_team_id == row.physical_team_id
                        if source.physical_team_id is not None and row.physical_team_id is not None
                        else None
                    ),
                    alive=row.alive,
                )
            )
        ordered = tuple(
            sorted(candidates, key=lambda row: (row.distance_world_units, str(row.participant_id)))[
                : max(0, limit)
            ]
        )
        return NearestPlayersResult(
            match_id=match_id,
            round_number=round_number,
            tick=tick,
            source_participant_id=participant_id,
            players=ordered,
        )

    def get_playback_chunk(
        self,
        match_id: UUID,
        round_number: int,
        *,
        from_index: int = 0,
        limit: int = 64,
        spatial_run_id: UUID | None = None,
        physical_team_id: UUID | None = None,
        participant_id: UUID | None = None,
        alive_only: bool = False,
        bomb_carrier_only: bool = False,
    ) -> SpatialPlaybackChunk:
        """Return bounded authoritative samples; visual frames are never serialized here."""

        from stratweb.exceptions import PlaybackIndexError

        if from_index < 0 or limit < 1 or limit > 200:
            raise PlaybackIndexError("Playback index or chunk limit is outside the allowed range.")
        summary = self._require_summary(match_id, spatial_run_id)
        ticks = self.list_round_ticks(
            match_id,
            round_number,
            spatial_run_id=summary.spatial_run_id,
        )
        if ticks and from_index >= len(ticks):
            raise PlaybackIndexError(
                f"Playback index {from_index} is outside round sample range 0..{len(ticks) - 1}."
            )
        selected_ticks = ticks[from_index : from_index + limit]
        rows = self._spatial.get_playback_snapshots(
            match_id,
            round_number,
            selected_ticks,
            spatial_run_id=summary.spatial_run_id,
        )
        bombs = self._spatial.get_playback_bomb_positions(
            match_id,
            round_number,
            selected_ticks,
            spatial_run_id=summary.spatial_run_id,
        )
        interval_start = selected_ticks[0] if selected_ticks else 0
        interval_end = selected_ticks[-1] if selected_ticks else 0
        projectile_rows = (
            self._spatial.get_round_projectiles(
                match_id,
                round_number,
                spatial_run_id=summary.spatial_run_id,
            )
            if selected_ticks
            else ()
        )
        projectile_snapshots = (
            self._spatial.get_playback_projectile_snapshots(
                match_id,
                round_number,
                interval_start,
                interval_end,
                spatial_run_id=summary.spatial_run_id,
            )
            if selected_ticks
            else ()
        )
        utility_effect_rows = (
            self._spatial.get_playback_utility_effects(
                match_id,
                round_number,
                interval_start,
                interval_end,
                spatial_run_id=summary.spatial_run_id,
            )
            if selected_ticks
            else ()
        )
        rows_by_tick: dict[int, list[SpatialSnapshot]] = {}
        for row in rows:
            rows_by_tick.setdefault(row.tick, []).append(row)
        bombs_by_tick = {item.tick: item for item in bombs}
        overview = self._overviews.get_for_run(summary.map_model.map_name, summary.map_semantics)
        labels = self._player_labels(match_id)
        teams = self._team_labels(match_id)
        samples: list[PlaybackSample] = []
        for offset, tick in enumerate(selected_ticks):
            all_rows = tuple(rows_by_tick.get(tick, ()))
            filtered_rows = tuple(
                row
                for row in all_rows
                if _playback_filter_matches(
                    row,
                    physical_team_id=physical_team_id,
                    participant_id=participant_id,
                    alive_only=alive_only,
                    bomb_carrier_only=bomb_carrier_only,
                )
            )
            player_views = tuple(
                _player_view(row, labels, teams, overview) for row in filtered_rows
            )
            bomb = bombs_by_tick.get(tick)
            bomb_projection = overview.project(bomb.x, bomb.y, bomb.z) if bomb else None
            bomb_status, bomb_rejections = _projection_status(bomb_projection)
            samples.append(
                PlaybackSample(
                    sample_index=from_index + offset,
                    tick=tick,
                    players=player_views,
                    bomb_position=bomb,
                    bomb_projection=bomb_projection,
                    bomb_render_status=bomb_status,
                    bomb_rejection_reasons=bomb_rejections,
                    bomb_carrier_id=(bomb.carrier_participant_id if bomb else None),
                    events=self._event_markers(
                        match_id,
                        summary.temporal_run_id,
                        round_number,
                        tick,
                        all_rows,
                        labels,
                        overview,
                    ),
                    warnings=(),
                )
            )
        projectile_by_id = {item.projectile_id: item for item in projectile_rows}
        projectile_views = tuple(
            _projectile_view(item, projectile_by_id[item.projectile_id], labels, overview)
            for item in projectile_snapshots
            if item.projectile_id in projectile_by_id
            and (
                physical_team_id is None
                or projectile_by_id[item.projectile_id].owner_physical_team_id == physical_team_id
            )
            and (
                participant_id is None
                or projectile_by_id[item.projectile_id].owner_participant_id == participant_id
            )
        )
        selected_projectile_ids = {item.snapshot.projectile_id for item in projectile_views}
        selected_projectiles = tuple(
            item for item in projectile_rows if item.projectile_id in selected_projectile_ids
        )
        if ticks:
            sample_by_tick = {item.tick: item for item in samples}
            for projectile in selected_projectiles:
                thrown_tick = projectile.thrown_tick
                if thrown_tick is None:
                    continue
                target_tick = min(ticks, key=lambda item: abs(item - thrown_tick))
                sample = sample_by_tick.get(target_tick)
                if sample is None or abs(target_tick - thrown_tick) > 16:
                    continue
                throw_marker = _projectile_throw_marker(
                    projectile,
                    target_tick,
                    thrown_tick - target_tick,
                    sample.players,
                    match_id,
                    round_number,
                    summary.temporal_run_id,
                )
                updated = sample.model_copy(update={"events": (*sample.events, throw_marker)})
                sample_by_tick[target_tick] = updated
            samples = [sample_by_tick[item.tick] for item in samples]
        utility_views = tuple(
            _utility_effect_view(item, overview)
            for item in utility_effect_rows
            if (
                physical_team_id is None
                and participant_id is None
                or item.projectile_id in selected_projectile_ids
            )
        )
        event_markers = tuple(event for sample in samples for event in sample.events)
        diagnostics = _playback_diagnostics(
            tuple(samples), projectile_views, utility_views, event_markers
        )
        next_index = from_index + len(samples)
        return SpatialPlaybackChunk(
            match_id=match_id,
            spatial_run_id=summary.spatial_run_id,
            temporal_run_id=summary.temporal_run_id,
            round_number=round_number,
            ticks=selected_ticks,
            samples=tuple(samples),
            projectiles=selected_projectiles,
            projectile_samples=projectile_views,
            utility_effects=utility_views,
            clock=PlaybackClockMetadata(),
            navigation=PlaybackNavigation(
                from_index=from_index,
                returned_samples=len(samples),
                total_samples=len(ticks),
                previous_from_index=max(0, from_index - limit) if from_index > 0 else None,
                next_from_index=next_index if next_index < len(ticks) else None,
                has_more=next_index < len(ticks),
            ),
            filters=PlaybackFilters(
                physical_team_id=physical_team_id,
                participant_id=participant_id,
                alive_only=alive_only,
                bomb_carrier_only=bomb_carrier_only,
            ),
            overview=overview.model,
            position_availability=summary.capabilities.positions.status,
            view_angle_availability=summary.capabilities.view_angles.status,
            projectile_metadata=summary.projectile_metadata,
            projectile_capabilities=summary.projectile_capabilities,
            diagnostics=diagnostics,
            warnings=summary.warnings,
        )

    def _event_markers(
        self,
        match_id: UUID,
        temporal_run_id: UUID,
        round_number: int,
        tick: int,
        rows: tuple[SpatialSnapshot, ...],
        labels: dict[UUID, str],
        overview: MapOverviewAsset,
    ) -> tuple[SpatialEventMarker, ...]:
        timeline = self._round_timeline(match_id, temporal_run_id, round_number)
        by_player = {row.participant_id: row for row in rows}
        result: list[SpatialEventMarker] = []
        events_by_id = (
            {event.event_id: event for event in timeline.ordered_events}
            if timeline is not None
            else {}
        )
        if timeline is not None:
            for event in timeline.ordered_events:
                if event.time.tick != tick:
                    continue
                kind = _base_marker_kind(event)
                if kind is None:
                    continue
                player_id = (
                    event.victim_player_id
                    if kind is SpatialEventMarkerKind.DEATH
                    else event.actor_player_id
                )
                result.append(
                    _marker(
                        kind,
                        event.event_id,
                        tick,
                        player_id,
                        labels,
                        by_player,
                        overview,
                        match_id,
                        round_number,
                        temporal_run_id,
                        "temporal_event",
                    )
                )
        canonical = self._round_events(match_id, round_number)
        if canonical is not None:
            for shot in canonical.shots:
                if shot.tick == tick:
                    result.append(
                        _canonical_marker(
                            SpatialEventMarkerKind.SHOT,
                            shot.event_id,
                            tick,
                            shot.player_id,
                            labels,
                            by_player,
                            overview,
                            match_id,
                            round_number,
                            temporal_run_id,
                            "canonical:weapon_fire",
                        )
                    )
            for damage in canonical.damages:
                if damage.tick == tick:
                    result.append(
                        _canonical_marker(
                            SpatialEventMarkerKind.DAMAGE,
                            damage.event_id,
                            tick,
                            damage.victim_player_id,
                            labels,
                            by_player,
                            overview,
                            match_id,
                            round_number,
                            temporal_run_id,
                            "canonical:player_hurt",
                        )
                    )
            for grenade in canonical.grenades:
                if grenade.tick == tick:
                    result.append(
                        _canonical_marker(
                            SpatialEventMarkerKind.GRENADE,
                            grenade.event_id,
                            tick,
                            grenade.player_id,
                            labels,
                            by_player,
                            overview,
                            match_id,
                            round_number,
                            temporal_run_id,
                            f"canonical:{grenade.lifecycle_event}",
                            coordinates=(grenade.x, grenade.y, grenade.z),
                        )
                    )
        if self._analytics is not None:
            for opening in self._opening_duels(match_id):
                if opening.round_number == round_number and opening.tick == tick:
                    result.append(
                        _marker(
                            SpatialEventMarkerKind.OPENING_DUEL,
                            opening.event_id,
                            tick,
                            opening.opening_victim_player_id,
                            labels,
                            by_player,
                            overview,
                            match_id,
                            round_number,
                            temporal_run_id,
                            "analytics:opening_duel",
                        )
                    )
            for trade in self._trade_events(match_id, round_number):
                traded_event = events_by_id.get(trade.traded_kill_event_id)
                if traded_event is not None and traded_event.time.tick == tick:
                    result.append(
                        _marker(
                            SpatialEventMarkerKind.TRADE,
                            traded_event.event_id,
                            tick,
                            traded_event.victim_player_id,
                            labels,
                            by_player,
                            overview,
                            match_id,
                            round_number,
                            temporal_run_id,
                            "analytics:direct_trade",
                        )
                    )
        return tuple(sorted(result, key=lambda item: (item.kind.value, item.marker_id)))

    def _round_events(self, match_id: UUID, round_number: int) -> RoundEvents | None:
        key = (match_id, round_number)
        if key not in self._round_events_cache:
            self._round_events_cache[key] = self._matches.get_round_events(match_id, round_number)
        return self._round_events_cache[key]

    def _require_summary(
        self, match_id: UUID, spatial_run_id: UUID | None = None
    ) -> SpatialRunSummary:
        from stratweb.exceptions import SpatialNotFoundError

        key = (match_id, spatial_run_id)
        summary = self._summary_cache.get(key)
        if summary is None:
            summary = (
                self._spatial.get_summary_for_run(match_id, spatial_run_id)
                if spatial_run_id is not None
                else self._spatial.get_summary(match_id)
            )
        if summary is None:
            raise SpatialNotFoundError(f"Spatial run not found for match: {match_id}")
        self._summary_cache[key] = summary
        self._summary_cache[(match_id, summary.spatial_run_id)] = summary
        return summary

    def _player_labels(self, match_id: UUID) -> dict[UUID, str]:
        if match_id not in self._player_label_cache:
            self._player_label_cache[match_id] = {
                item.player_id: item.current_name for item in self._matches.get_players(match_id)
            }
        return self._player_label_cache[match_id]

    def _team_labels(self, match_id: UUID) -> dict[UUID, str]:
        if match_id not in self._team_label_cache:
            self._team_label_cache[match_id] = {
                item.team_id: item.display_name or item.internal_name
                for item in self._matches.get_teams(match_id)
            }
        return self._team_label_cache[match_id]

    def _round_timeline(
        self, match_id: UUID, temporal_run_id: UUID, round_number: int
    ) -> RoundTimeline | None:
        key = (match_id, temporal_run_id, round_number)
        if key not in self._timeline_cache:
            self._timeline_cache[key] = self._temporal.get_round_timeline_for_run(
                match_id, temporal_run_id, round_number
            )
        return self._timeline_cache[key]

    def _opening_duels(self, match_id: UUID) -> tuple[OpeningDuel, ...]:
        if match_id not in self._opening_cache:
            self._opening_cache[match_id] = (
                self._analytics.list_opening_duels(match_id) if self._analytics is not None else ()
            )
        return self._opening_cache[match_id]

    def _trade_events(self, match_id: UUID, round_number: int) -> tuple[TradeEvent, ...]:
        key = (match_id, round_number)
        if key not in self._trade_cache:
            self._trade_cache[key] = (
                self._analytics.list_trade_events(match_id, round_number)
                if self._analytics is not None
                else ()
            )
        return self._trade_cache[key]


def _navigation(ticks: tuple[int, ...], requested: int) -> TickNavigation:
    exact = requested in ticks
    previous = next((tick for tick in reversed(ticks) if tick < requested), None)
    following = next((tick for tick in ticks if tick > requested), None)
    return TickNavigation(
        requested_tick=requested,
        status=TickResolutionStatus.EXACT if exact else TickResolutionStatus.UNAVAILABLE,
        previous_tick=previous,
        next_tick=following,
        minimum_tick=ticks[0] if ticks else None,
        maximum_tick=ticks[-1] if ticks else None,
        available_tick_count=len(ticks),
    )


def _playback_filter_matches(
    row: SpatialSnapshot,
    *,
    physical_team_id: UUID | None,
    participant_id: UUID | None,
    alive_only: bool,
    bomb_carrier_only: bool,
) -> bool:
    if physical_team_id is not None and row.physical_team_id != physical_team_id:
        return False
    if participant_id is not None and row.participant_id != participant_id:
        return False
    if alive_only and row.alive is not True:
        return False
    return not bomb_carrier_only or row.has_bomb is True


def _player_view(
    row: SpatialSnapshot,
    labels: dict[UUID, str],
    teams: dict[UUID, str],
    overview: MapOverviewAsset,
) -> SpatialPlayerView:
    projection = (
        overview.project(row.x, row.y, row.z) if row.x is not None and row.y is not None else None
    )
    direction = None
    if projection is not None and row.yaw is not None:
        angle = radians(row.yaw)
        direction = MapViewDirection(
            yaw_degrees=row.yaw,
            start_pixel_x=projection.pixel_x,
            start_pixel_y=projection.pixel_y,
            end_pixel_x=projection.pixel_x + cos(angle) * 34,
            end_pixel_y=projection.pixel_y - sin(angle) * 34,
        )
    render_status, rejection_reasons = _projection_status(projection)
    return SpatialPlayerView(
        snapshot=row,
        player_name=labels.get(row.participant_id, str(row.participant_id)),
        team_name=teams.get(row.physical_team_id) if row.physical_team_id else None,
        projection=projection,
        view_direction=direction,
        render_status=render_status,
        rejection_reasons=rejection_reasons,
    )


def _base_marker_kind(event: TemporalEvent) -> SpatialEventMarkerKind | None:
    if event.kind is TemporalEventKind.DEATH:
        return SpatialEventMarkerKind.DEATH
    if event.kind is not TemporalEventKind.BOMB:
        return None
    event_type = event.event_type.casefold()
    if "planted" in event_type:
        return SpatialEventMarkerKind.PLANT
    if "defused" in event_type:
        return SpatialEventMarkerKind.DEFUSE
    if "exploded" in event_type:
        return SpatialEventMarkerKind.EXPLOSION
    return None


def _marker(
    kind: SpatialEventMarkerKind,
    event_id: UUID,
    tick: int,
    player_id: UUID | None,
    labels: dict[UUID, str],
    by_player: dict[UUID, SpatialSnapshot],
    overview: MapOverviewAsset,
    match_id: UUID,
    round_number: int,
    temporal_run_id: UUID,
    source: str,
) -> SpatialEventMarker:
    row = by_player.get(player_id) if player_id else None
    projection = (
        overview.project(row.x, row.y, row.z)
        if row is not None and row.x is not None and row.y is not None
        else None
    )
    render_status, rejection_reasons = _projection_status(projection)
    warnings = (
        ()
        if render_status is EntityRenderStatus.AVAILABLE
        else ("event participant has no safe projectable position",)
    )
    return SpatialEventMarker(
        marker_id=f"{kind.value}:{event_id}",
        event_id=event_id,
        kind=kind,
        tick=tick,
        player_id=player_id,
        player_name=labels.get(player_id) if player_id else None,
        projection=projection,
        source=source,
        temporal_url=(
            f"/ui/temporal/{match_id}/rounds/{round_number}/events/{event_id}"
            f"?run_id={temporal_run_id}"
        ),
        render_status=render_status,
        rejection_reasons=rejection_reasons,
        warnings=warnings,
    )


def _canonical_marker(
    kind: SpatialEventMarkerKind,
    event_id: UUID,
    tick: int,
    player_id: UUID | None,
    labels: dict[UUID, str],
    by_player: dict[UUID, SpatialSnapshot],
    overview: MapOverviewAsset,
    match_id: UUID,
    round_number: int,
    temporal_run_id: UUID,
    source: str,
    *,
    coordinates: tuple[float | None, float | None, float | None] | None = None,
) -> SpatialEventMarker:
    marker = _marker(
        kind,
        event_id,
        tick,
        player_id,
        labels,
        by_player,
        overview,
        match_id,
        round_number,
        temporal_run_id,
        source,
    )
    projection = marker.projection
    if coordinates is not None and coordinates[0] is not None and coordinates[1] is not None:
        projection = overview.project(coordinates[0], coordinates[1], coordinates[2])
    render_status, rejection_reasons = _projection_status(projection)
    return marker.model_copy(
        update={
            "projection": projection,
            "render_status": render_status,
            "rejection_reasons": rejection_reasons,
            "warnings": (
                ()
                if render_status is EntityRenderStatus.AVAILABLE
                else ("canonical event has no safe projectable position",)
            ),
            "temporal_url": (
                f"/ui/temporal/{match_id}/rounds/{round_number}/snapshots/{tick}"
                f"?run_id={temporal_run_id}"
            ),
        }
    )


def _projectile_throw_marker(
    projectile: SpatialProjectile,
    sample_tick: int,
    tick_offset: int,
    players: tuple[SpatialPlayerView, ...],
    match_id: UUID,
    round_number: int,
    temporal_run_id: UUID,
) -> SpatialEventMarker:
    owner = next(
        (
            item
            for item in players
            if item.snapshot.participant_id == projectile.owner_participant_id
        ),
        None,
    )
    projection = owner.projection if owner is not None else None
    render_status, rejection_reasons = _projection_status(projection)
    warnings = ["throw action tick is weapon_fire; marker position is the owner SpatialSnapshot"]
    if tick_offset:
        warnings.append(f"owner_spatial_sample_tick_offset:{tick_offset}")
    return SpatialEventMarker(
        marker_id=f"grenade-throw:{projectile.projectile_id}",
        event_id=projectile.projectile_id,
        kind=SpatialEventMarkerKind.GRENADE,
        tick=projectile.thrown_tick or sample_tick,
        player_id=projectile.owner_participant_id,
        player_name=owner.player_name if owner is not None else None,
        projection=projection,
        source="projectile:weapon_fire_owner_position_association",
        temporal_url=(
            f"/ui/temporal/{match_id}/rounds/{round_number}/snapshots/{sample_tick}"
            f"?run_id={temporal_run_id}"
        ),
        render_status=render_status,
        rejection_reasons=rejection_reasons,
        warnings=tuple(warnings),
    )


def _projection_status(
    projection: MapProjection | None,
) -> tuple[EntityRenderStatus, tuple[str, ...]]:
    if projection is None:
        return EntityRenderStatus.UNAVAILABLE, ("projection_unavailable",)
    if projection.inside_image is not True:
        return EntityRenderStatus.REJECTED, ("projection_outside_map_image",)
    return EntityRenderStatus.AVAILABLE, ()


def _projectile_view(
    snapshot: ProjectileSnapshot,
    projectile: SpatialProjectile,
    labels: dict[UUID, str],
    overview: MapOverviewAsset,
) -> ProjectileSnapshotView:
    projection = overview.project(snapshot.x, snapshot.y, snapshot.z)
    render_status, rejection_reasons = _projection_status(projection)
    return ProjectileSnapshotView(
        projectile=projectile,
        snapshot=snapshot,
        owner_name=(
            labels.get(projectile.owner_participant_id)
            if projectile.owner_participant_id is not None
            else None
        ),
        projection=projection,
        render_status=render_status,
        rejection_reasons=rejection_reasons,
    )


def _utility_effect_view(effect: UtilityEffect, overview: MapOverviewAsset) -> UtilityEffectView:
    projection = (
        overview.project(effect.center_x, effect.center_y, effect.center_z)
        if effect.center_x is not None and effect.center_y is not None
        else None
    )
    render_status, rejection_reasons = _projection_status(projection)
    return UtilityEffectView(
        effect=effect,
        projection=projection,
        render_status=render_status,
        rejection_reasons=rejection_reasons,
    )


def _playback_diagnostics(
    samples: tuple[PlaybackSample, ...],
    projectiles: tuple[ProjectileSnapshotView, ...],
    effects: tuple[UtilityEffectView, ...],
    events: tuple[SpatialEventMarker, ...],
) -> PlaybackDiagnostics:
    player_views = tuple(player for sample in samples for player in sample.players)
    repeated = 0
    suspicious = 0
    previous_by_player: dict[UUID, SpatialPlayerView] = {}
    for player in player_views:
        previous = previous_by_player.get(player.snapshot.participant_id)
        if previous is not None:
            transition = classify_motion(
                previous.snapshot,
                player.snapshot,
                previous_inside_map=(
                    previous.projection.inside_image if previous.projection is not None else None
                ),
                following_inside_map=(
                    player.projection.inside_image if player.projection is not None else None
                ),
                previous_level=(
                    previous.projection.level.value if previous.projection is not None else None
                ),
                following_level=(
                    player.projection.level.value if player.projection is not None else None
                ),
            )
            repeated += int(transition.repeated_identical_sample)
            suspicious += int("suspicious_spatial_jump" in transition.warnings)
        previous_by_player[player.snapshot.participant_id] = player
    return PlaybackDiagnostics(
        authoritative_player_samples=len(player_views),
        unavailable_player_samples=sum(
            item.render_status is EntityRenderStatus.UNAVAILABLE for item in player_views
        ),
        rejected_player_markers=sum(
            item.render_status is EntityRenderStatus.REJECTED for item in player_views
        ),
        authoritative_projectile_samples=len(projectiles),
        rejected_projectile_markers=sum(
            item.render_status is EntityRenderStatus.REJECTED for item in projectiles
        ),
        utility_effects=len(effects),
        rejected_utility_effects=sum(
            item.render_status is EntityRenderStatus.REJECTED for item in effects
        ),
        event_markers=len(events),
        rejected_event_markers=sum(
            item.render_status is EntityRenderStatus.REJECTED for item in events
        ),
        repeated_player_samples=repeated,
        suspicious_player_jumps=suspicious,
    )
