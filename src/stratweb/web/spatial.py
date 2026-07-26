"""Read-only Spatial Engine 1.0 evidence table and JSON endpoints."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBSpatialRepository
from stratweb.application.spatial import SpatialQueryService
from stratweb.exceptions import SpatialNotFoundError
from stratweb.spatial.models import SpatialRunRecord, SpatialRunSummary, SpatialSnapshot
from stratweb.web.rendering import render_legacy_content


def spatial_ui_router(database_path: Path) -> APIRouter:
    router = APIRouter()

    def service() -> SpatialQueryService:
        return SpatialQueryService(DuckDBSpatialRepository(database_path))

    def labels(match_id: UUID) -> dict[UUID, str]:
        return {
            player.player_id: player.current_name
            for player in DuckDBMatchRepository(database_path).get_players(match_id)
        }

    @router.get("/ui/spatial/{match_id}", response_class=HTMLResponse, include_in_schema=False)
    def spatial_table(
        match_id: UUID,
        round_number: Annotated[int | None, Query(alias="round", ge=1)] = None,
        participant_id: Annotated[UUID | None, Query(alias="player")] = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 500,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> HTMLResponse:
        query = service()
        summary = _summary(query, match_id)
        snapshots = query.list_snapshots(
            match_id,
            round_number=round_number,
            participant_id=participant_id,
            limit=limit,
            offset=offset,
        )
        return HTMLResponse(
            _page(
                f"Spatial snapshots · {match_id}",
                _table_page(
                    summary,
                    query.list_runs(match_id),
                    snapshots,
                    labels(match_id),
                    round_number,
                    participant_id,
                ),
            )
        )

    @router.get("/api/spatial/{match_id}/summary", tags=["spatial-ui"])
    def api_summary(match_id: UUID) -> dict[str, Any]:
        query = service()
        return {
            "selected_run": _summary(query, match_id).model_dump(mode="json"),
            "runs": [item.model_dump(mode="json") for item in query.list_runs(match_id)],
        }

    @router.get("/api/spatial/{match_id}/snapshots", tags=["spatial-ui"])
    def api_snapshots(
        match_id: UUID,
        round_number: Annotated[int | None, Query(alias="round", ge=1)] = None,
        participant_id: Annotated[UUID | None, Query(alias="player")] = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        query = service()
        summary = _summary(query, match_id)
        rows = query.list_snapshots(
            match_id,
            round_number=round_number,
            participant_id=participant_id,
            limit=limit,
            offset=offset,
        )
        return {
            "spatial_run_id": str(summary.spatial_run_id),
            "spatial_schema_version": summary.spatial_schema_version,
            "spatial_rule_version": summary.spatial_rule_version,
            "limit": limit,
            "offset": offset,
            "snapshots": [item.model_dump(mode="json") for item in rows],
        }

    @router.get("/api/spatial/{match_id}/validation", tags=["spatial-ui"])
    def api_validation(match_id: UUID) -> dict[str, Any]:
        query = service()
        summary = _summary(query, match_id)
        issues = query.validate(match_id)
        return {
            "spatial_run_id": str(summary.spatial_run_id),
            "count": len(issues),
            "issues": [item.model_dump(mode="json") for item in issues],
        }

    return router


def _summary(service: SpatialQueryService, match_id: UUID) -> SpatialRunSummary:
    try:
        return service.get_summary(match_id)
    except SpatialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _table_page(
    summary: SpatialRunSummary,
    run_records: tuple[SpatialRunRecord, ...],
    snapshots: tuple[SpatialSnapshot, ...],
    labels: dict[UUID, str],
    round_number: int | None,
    participant_id: UUID | None,
) -> str:
    capabilities = "".join(
        _capability(name.replace("_", " "), capability) for name, capability in summary.capabilities
    )
    rows = "".join(_snapshot_row(item, labels) for item in snapshots)
    if not rows:
        rows = '<tr><td colspan="15">No snapshots match these filters.</td></tr>'
    warnings = "".join(f"<li>{escape(item)}</li>" for item in summary.warnings) or "<li>None</li>"
    runs = "".join(
        f"<tr><td class=mono>{item.spatial_run_id}</td><td>{item.spatial_schema_version}</td>"
        f"<td>{item.spatial_rule_version}</td><td>{item.compatible}</td>"
        f"<td>{item.selected_by_default}</td><td>{item.created_at}</td></tr>"
        for item in run_records
    )
    filters = (
        f"round={round_number if round_number is not None else 'all'} · "
        f"player={escape(str(participant_id or 'all'))}"
    )
    return f"""
    <nav><a href="/ui/temporal/{summary.match_id}">Temporal match</a> · Spatial table</nav>
    <header><p class="eyebrow">Offline evidence · no live data</p>
      <h1>Spatial snapshots</h1>
      <p class="mono">match {summary.match_id}</p>
      <p>Spatial schema {escape(summary.spatial_schema_version)} · rule
      {escape(summary.spatial_rule_version)} · parser {escape(summary.parser_name)}
      {escape(summary.parser_version)}</p>
      <p>Temporal run <span class="mono">{summary.temporal_run_id}</span></p>
      <a class="button" href="/ui/spatial/{summary.match_id}/rounds/1">Open map explorer</a>
      <a class="button" href="/api/spatial/{summary.match_id}/summary">Summary JSON</a>
      <a class="button" href="/api/spatial/{summary.match_id}/validation">Validation JSON</a>
    </header>
    <h2>Capabilities</h2><section class="cards">{capabilities}</section>
    <h2>Snapshots</h2><p>{filters} · showing {len(snapshots)} rows</p>
    <div class="scroll"><table><thead><tr>
      <th>round</th><th>tick</th><th>player</th><th>x</th><th>y</th><th>z</th>
      <th>pitch</th><th>yaw</th><th>alive</th><th>C4</th><th>team</th><th>side</th>
      <th>position</th><th>view</th><th>alive link</th>
    </tr></thead><tbody>{rows}</tbody></table></div>
    <p class="notice">Rows are sampled at ticks proven by the selected Temporal run. Coordinates
    are raw Source 2 world units. No zone, trajectory, heatmap, or tactical meaning is inferred.</p>
    <h2>Warnings</h2><ul>{warnings}</ul>
    <h2>Run selection</h2><p>The newest compatible Spatial run is selected. Run history and
    compatibility are included below and in Summary JSON; rows from different runs are never
    mixed.</p><div class="scroll"><table><thead><tr><th>run</th><th>schema</th><th>rule</th>
    <th>compatible</th><th>selected</th><th>created</th></tr></thead><tbody>{runs}</tbody></table></div>
    """


def _capability(label: str, capability: Any) -> str:
    warnings = "; ".join(capability.warnings) or "none"
    return f"""
    <article><span>{escape(label)}</span><strong>{escape(capability.status.value)}</strong>
      <small>{capability.covered}/{capability.population} ·
      {escape(capability.authority.value)}</small><small>{escape(warnings)}</small></article>
    """


def _snapshot_row(snapshot: SpatialSnapshot, labels: dict[UUID, str]) -> str:
    def value(item: Any) -> str:
        if item is None:
            return "—"
        if isinstance(item, float):
            return f"{item:.2f}"
        return escape(str(item))

    player = escape(labels.get(snapshot.participant_id, str(snapshot.participant_id)))
    return f"""
    <tr><td>{snapshot.round_number}</td><td>{snapshot.tick}</td><td>{player}</td>
      <td>{value(snapshot.x)}</td><td>{value(snapshot.y)}</td><td>{value(snapshot.z)}</td>
      <td>{value(snapshot.pitch)}</td><td>{value(snapshot.yaw)}</td>
      <td>{value(snapshot.alive)}</td><td>{value(snapshot.has_bomb)}</td>
      <td class="mono">{value(snapshot.physical_team_id)}</td><td>{snapshot.side.value}</td>
      <td>{snapshot.availability.position.value}</td>
      <td>{snapshot.availability.view_angles.value}</td>
      <td>{snapshot.availability.alive_link.value}</td></tr>
    """


def _page(title: str, content: str) -> str:
    return render_legacy_content(title, content, match_context=None)
