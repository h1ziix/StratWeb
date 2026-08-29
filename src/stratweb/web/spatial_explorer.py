"""Stage 7.2 productized spatial viewer and evidence JSON endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.application.cs2_demo_bridge import (
    CS2DemoBridgeError,
    CS2DemoBridgeService,
    CS2DemoCommand,
)
from stratweb.application.spatial_queries import SpatialExplorerService
from stratweb.exceptions import PlaybackIndexError, SpatialNotFoundError
from stratweb.maps.registry import MapRegistry
from stratweb.spatial.map_overviews import MapOverviewRegistry
from stratweb.spatial.models import SpatialAvailabilityStatus
from stratweb.web.context import build_match_context, require_localhost
from stratweb.web.rendering import render_template

PLAYBACK_CHUNK_SIZE = 64


def spatial_explorer_router(
    database_path: Path,
    asset_directory: Path,
    *,
    map_registry: MapRegistry | None = None,
    cs2_demo_directory: Path | None = None,
) -> APIRouter:
    router = APIRouter()
    registry = MapOverviewRegistry(asset_directory, map_registry)
    matches = DuckDBMatchRepository(database_path)
    temporal = DuckDBTemporalRepository(database_path)
    spatial = DuckDBSpatialRepository(database_path)
    analytics = DuckDBAnalyticsRepository(database_path)
    explorer = SpatialExplorerService(
        matches,
        temporal,
        spatial,
        registry,
        analytics_repository=analytics,
        zone_repository=DuckDBZoneAssignmentRepository(database_path),
    )
    cs2_bridge = CS2DemoBridgeService(database_path, cs2_demo_directory)

    @router.post(
        "/api/matches/{match_id}/cs2-demo-command",
        response_model=CS2DemoCommand,
        tags=["playback"],
    )
    def prepare_cs2_demo_command(
        request: Request,
        match_id: UUID,
        tick: Annotated[int, Query(ge=0)],
    ) -> CS2DemoCommand:
        require_localhost(request, "CS2 demo preparation")
        try:
            return cs2_bridge.prepare(match_id, tick)
        except CS2DemoBridgeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get(
        "/assets/map-overviews/{map_name}.png",
        response_class=FileResponse,
        include_in_schema=False,
    )
    def map_asset(map_name: str) -> FileResponse:
        asset = registry.get(map_name)
        if asset.image_path is None:
            raise HTTPException(status_code=404, detail="Official map overview is unavailable")
        return FileResponse(
            asset.image_path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @router.get(
        "/ui/spatial/{match_id}/rounds/{round_number}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def round_map(
        match_id: UUID,
        round_number: int,
        tick: Annotated[int | None, Query(ge=0)] = None,
        run_id: UUID | None = None,
        team_id: Annotated[UUID | None, Query(alias="team")] = None,
        participant_id: Annotated[UUID | None, Query(alias="player")] = None,
        alive_only: bool = False,
        bomb_carrier_only: bool = False,
        mode: Annotated[str, Query(pattern="^(smooth|exact)$")] = "smooth",
    ) -> HTMLResponse:
        try:
            ticks = explorer.list_round_ticks(
                match_id,
                round_number,
                spatial_run_id=run_id,
            )
            if not ticks:
                raise HTTPException(
                    status_code=404,
                    detail="No authoritative spatial samples exist for this round.",
                )
            initial_index = ticks.index(tick) if tick in ticks else 0
            initial_from = max(0, initial_index - 16)
            chunk = explorer.get_playback_chunk(
                match_id,
                round_number,
                from_index=initial_from,
                limit=PLAYBACK_CHUNK_SIZE,
                spatial_run_id=run_id,
                physical_team_id=team_id,
                participant_id=participant_id,
                alive_only=alive_only,
                bomb_carrier_only=bomb_carrier_only,
            )
        except SpatialNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        stored = matches.get_match(match_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Match not found")
        players = matches.get_players(match_id)
        teams = matches.get_teams(match_id)
        rounds = matches.get_rounds(match_id)
        team_by_player = {
            player_id: team.team_id
            for team in sorted(teams, key=lambda item: str(item.team_id))
            for player_id in team.starting_player_ids
        }
        available_ticks = set(ticks)
        events = tuple(
            event
            for event in _round_events(temporal, chunk.temporal_run_id, match_id, round_number)
            if event["tick"] in available_ticks
        )
        config = {
            "match_id": str(match_id),
            "round_number": round_number,
            "spatial_run_id": str(chunk.spatial_run_id),
            "temporal_run_id": str(chunk.temporal_run_id),
            "initial_index": initial_index,
            "total_samples": len(ticks),
            "chunk_limit": PLAYBACK_CHUNK_SIZE,
            "ticks": ticks,
            "event_ticks": tuple(item["tick"] for item in events),
            "playback_clock": chunk.clock.model_dump(mode="json"),
            "label_roster": tuple(
                {
                    "participant_id": str(player.player_id),
                    "player_name": player.current_name,
                    "physical_team_id": (
                        str(team_by_player[player.player_id])
                        if player.player_id in team_by_player
                        else None
                    ),
                }
                for player in sorted(players, key=lambda item: str(item.player_id))
            ),
            "mode": mode,
        }
        return HTMLResponse(
            render_template(
                "spatial/explorer.html",
                match_context=build_match_context(stored, teams, rounds),
                round_number=round_number,
                round_numbers=tuple(row.round_number for row in rounds),
                players=players,
                teams=teams,
                events=events,
                filters={
                    "team": team_id,
                    "player": participant_id,
                    "alive_only": alive_only,
                    "bomb_carrier_only": bomb_carrier_only,
                },
                overview=chunk.overview,
                overview_unavailable=(
                    chunk.overview.status is not SpatialAvailabilityStatus.AVAILABLE
                ),
                initial_index=initial_index,
                total_samples=len(ticks),
                initial_chunk=chunk,
                initial_chunk_json=_json_for_script(chunk.model_dump(mode="json")),
                config_json=_json_for_script(config),
            )
        )

    @router.get(
        "/ui/spatial/{match_id}/rounds/{round_number}/players/{participant_id}/path",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def player_path_page(
        match_id: UUID,
        round_number: int,
        participant_id: UUID,
        run_id: UUID | None = None,
    ) -> HTMLResponse:
        try:
            path = explorer.get_player_path(
                match_id,
                round_number,
                participant_id,
                spatial_run_id=run_id,
            )
        except SpatialNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        teams = matches.get_teams(match_id)
        rounds = matches.get_rounds(match_id)
        stored = matches.get_match(match_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="Match not found")
        points = tuple(item.projection for item in path.points if item.projection is not None)
        return HTMLResponse(
            render_template(
                "spatial/path.html",
                path=path,
                path_points=points,
                path_coordinates=" ".join(
                    f"{item.pixel_x:.2f},{item.pixel_y:.2f}" for item in points
                ),
                first_tick=path.points[0].snapshot.tick if path.points else "—",
                last_tick=path.points[-1].snapshot.tick if path.points else "—",
                run_query=f"?run_id={path.spatial_run_id}",
                match_context=build_match_context(stored, teams, rounds),
            )
        )

    @router.get("/api/spatial/{match_id}/rounds/{round_number}/playback", tags=["spatial-query"])
    def api_playback(
        match_id: UUID,
        round_number: int,
        from_index: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 64,
        run_id: UUID | None = None,
        team_id: Annotated[UUID | None, Query(alias="team")] = None,
        participant_id: Annotated[UUID | None, Query(alias="player")] = None,
        alive_only: bool = False,
        bomb_carrier_only: bool = False,
    ) -> dict[str, Any]:
        try:
            return explorer.get_playback_chunk(
                match_id,
                round_number,
                from_index=from_index,
                limit=limit,
                spatial_run_id=run_id,
                physical_team_id=team_id,
                participant_id=participant_id,
                alive_only=alive_only,
                bomb_carrier_only=bomb_carrier_only,
            ).model_dump(mode="json")
        except PlaybackIndexError as exc:
            raise HTTPException(status_code=416, detail=str(exc)) from exc

    @router.get("/api/spatial/{match_id}/rounds/{round_number}/ticks", tags=["spatial-query"])
    def api_ticks(match_id: UUID, round_number: int, run_id: UUID | None = None) -> dict[str, Any]:
        ticks = explorer.list_round_ticks(match_id, round_number, spatial_run_id=run_id)
        return {"match_id": str(match_id), "round_number": round_number, "ticks": ticks}

    @router.get(
        "/api/spatial/{match_id}/rounds/{round_number}/ticks/{tick}",
        tags=["spatial-query"],
    )
    def api_tick_snapshot(
        match_id: UUID,
        round_number: int,
        tick: int,
        run_id: UUID | None = None,
        team_id: Annotated[UUID | None, Query(alias="team")] = None,
        participant_id: Annotated[UUID | None, Query(alias="player")] = None,
        alive_only: bool = False,
        bomb_carrier_only: bool = False,
    ) -> dict[str, Any]:
        return explorer.get_tick_snapshot(
            match_id,
            round_number,
            tick,
            spatial_run_id=run_id,
            physical_team_id=team_id,
            participant_id=participant_id,
            alive_only=alive_only,
            bomb_carrier_only=bomb_carrier_only,
        ).model_dump(mode="json")

    @router.get("/api/spatial/{match_id}/map-snapshot", tags=["spatial-query"])
    def api_map_snapshot(
        match_id: UUID,
        round_number: Annotated[int, Query(alias="round", ge=1)],
        tick: Annotated[int, Query(ge=0)],
        run_id: UUID | None = None,
        team_id: Annotated[UUID | None, Query(alias="team")] = None,
        participant_id: Annotated[UUID | None, Query(alias="player")] = None,
        alive_only: bool = False,
        bomb_carrier_only: bool = False,
    ) -> dict[str, Any]:
        return api_tick_snapshot(
            match_id,
            round_number,
            tick,
            run_id,
            team_id,
            participant_id,
            alive_only,
            bomb_carrier_only,
        )

    @router.get(
        "/api/spatial/{match_id}/rounds/{round_number}/teams/{team_id}/ticks/{tick}",
        tags=["spatial-query"],
    )
    def api_team_snapshot(
        match_id: UUID,
        round_number: int,
        team_id: UUID,
        tick: int,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        return explorer.get_team_snapshot(
            match_id,
            round_number,
            tick,
            team_id,
            spatial_run_id=run_id,
        ).model_dump(mode="json")

    @router.get(
        "/api/spatial/{match_id}/rounds/{round_number}/players/{participant_id}/path",
        tags=["spatial-query"],
    )
    def api_player_path(
        match_id: UUID,
        round_number: int,
        participant_id: UUID,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        return explorer.get_player_path(
            match_id,
            round_number,
            participant_id,
            spatial_run_id=run_id,
        ).model_dump(mode="json")

    @router.get("/api/spatial/{match_id}/rounds/{round_number}/path", tags=["spatial-query"])
    def api_round_path(
        match_id: UUID,
        round_number: int,
        team_id: Annotated[UUID | None, Query(alias="team")] = None,
        participant_id: Annotated[UUID | None, Query(alias="player")] = None,
        alive_only: bool = False,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        rows = explorer.get_round_path(
            match_id,
            round_number,
            physical_team_id=team_id,
            participant_id=participant_id,
            alive_only=alive_only,
            spatial_run_id=run_id,
        )
        return {
            "match_id": str(match_id),
            "round_number": round_number,
            "point_count": len(rows),
            "points": [item.model_dump(mode="json") for item in rows],
        }

    @router.get(
        "/api/spatial/{match_id}/rounds/{round_number}/ticks/{tick}/nearest",
        tags=["spatial-query"],
    )
    def api_nearest(
        match_id: UUID,
        round_number: int,
        tick: int,
        participant_id: Annotated[UUID, Query(alias="player")],
        alive_only: bool = False,
        limit: Annotated[int, Query(ge=1, le=50)] = 9,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        return explorer.nearest_players(
            match_id,
            round_number,
            tick,
            participant_id,
            alive_only=alive_only,
            limit=limit,
            spatial_run_id=run_id,
        ).model_dump(mode="json")

    return router


def _round_events(
    temporal: DuckDBTemporalRepository,
    temporal_run_id: UUID,
    match_id: UUID,
    round_number: int,
) -> tuple[dict[str, Any], ...]:
    timeline = temporal.get_round_timeline_for_run(match_id, temporal_run_id, round_number)
    if timeline is None:
        return ()
    return tuple(
        {
            "event_id": str(event.event_id),
            "tick": event.time.tick,
            "label": event.event_type,
        }
        for event in timeline.ordered_events
        if event.state_affecting
    )


def _json_for_script(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return serialized.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
