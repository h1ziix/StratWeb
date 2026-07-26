"""Read-only map registry API, immutable assets, and developer calibration UI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBSpatialRepository
from stratweb.maps.models import MapDefinition, MapLevel, MapSelectionEvidence
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY, MapRegistry
from stratweb.maps.transforms import world_to_map
from stratweb.spatial.map_overviews import MapOverviewRegistry
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template
from stratweb.zones.definitions import zone_set_for
from stratweb.zones.engine import zone_area
from stratweb.zones.models import ZoneKind
from stratweb.zones.proposals import load_zone_proposal, proposal_zone_set
from stratweb.zones.validation import sampled_coverage, validate_zone_set


def map_router(
    database_path: Path,
    asset_directory: Path,
    *,
    map_registry: MapRegistry | None = None,
    developer_mode: bool = False,
) -> APIRouter:
    router = APIRouter()
    definitions = map_registry or DEFAULT_MAP_REGISTRY
    assets = MapOverviewRegistry(asset_directory, definitions)
    matches = DuckDBMatchRepository(database_path)
    spatial = DuckDBSpatialRepository(database_path)

    @router.get("/api/maps", tags=["maps"])
    def list_maps() -> dict[str, Any]:
        return {
            "maps": [
                _map_family_response(definitions, assets, canonical_name)
                for canonical_name in definitions.list_maps()
            ]
        }

    @router.get("/api/maps/{canonical_name}", tags=["maps"])
    def map_detail(canonical_name: str) -> dict[str, Any]:
        canonical = definitions.canonicalize(canonical_name)
        if canonical is None:
            raise HTTPException(status_code=404, detail="Unsupported map")
        return _map_family_response(definitions, assets, canonical)

    @router.get("/api/maps/{canonical_name}/revisions", tags=["maps"])
    def map_revisions(canonical_name: str) -> dict[str, Any]:
        canonical = definitions.canonicalize(canonical_name)
        if canonical is None:
            raise HTTPException(status_code=404, detail="Unsupported map")
        return {
            "canonical_name": canonical,
            "revisions": [
                _definition_response(item, assets) for item in definitions.revisions(canonical)
            ],
        }

    @router.get("/api/maps/{canonical_name}/transform", tags=["maps"])
    def transform(
        canonical_name: str,
        x: Annotated[float, Query(allow_inf_nan=False)],
        y: Annotated[float, Query(allow_inf_nan=False)],
        z: Annotated[float | None, Query(allow_inf_nan=False)] = None,
        revision: str | None = None,
    ) -> dict[str, Any]:
        definition = (
            definitions.get_revision(canonical_name, revision)
            if revision is not None
            else definitions.preferred_definition(canonical_name)
        )
        if definition is None:
            raise HTTPException(status_code=404, detail="Map revision is unavailable")
        return {
            "canonical_name": definition.canonical_name,
            "revision": definition.map_revision.revision_id,
            "result": world_to_map(definition, x, y, z).model_dump(mode="json"),
        }

    @router.get("/api/spatial/{match_id}/map", tags=["maps"])
    def match_map(match_id: UUID) -> dict[str, Any]:
        match = matches.get_match(match_id)
        if match is None:
            raise HTTPException(status_code=404, detail="Match not found")
        summary = spatial.get_summary(match_id)
        if summary is None:
            selection = definitions.select(
                MapSelectionEvidence(raw_map_name=match.map_name or "unknown")
            )
            return {
                "match_id": str(match_id),
                "canonical_name": selection.canonical_name,
                "display_name": selection.display_name,
                "selected_revision": None,
                "selection_status": selection.status,
                "selection_evidence": selection.evidence,
                "overview_urls": {"upper": None, "lower": None},
                "level_policy": None,
                "calibration_status": None,
                "legacy_map_semantics": False,
                "warnings": (*selection.warnings, "spatial_run_unavailable"),
            }
        overview = assets.get_for_run(summary.map_model.map_name, summary.map_semantics).model
        return {
            "match_id": str(match_id),
            "spatial_run_id": str(summary.spatial_run_id),
            "canonical_name": overview.canonical_name,
            "display_name": overview.display_name,
            "selected_revision": overview.selected_revision,
            "selection_status": overview.revision_selection_status,
            "selection_evidence": overview.selection_evidence,
            "overview_urls": {
                "upper": overview.image_url,
                "lower": overview.lower_image_url,
            },
            "level_policy": (
                overview.level_policy.model_dump(mode="json")
                if overview.level_policy is not None
                else None
            ),
            "calibration_status": overview.calibration_status,
            "legacy_map_semantics": overview.legacy_map_semantics,
            "warnings": overview.warnings,
        }

    @router.get(
        "/assets/map-overviews/{canonical_name}/{revision_id}/{level}.png",
        response_class=FileResponse,
        include_in_schema=False,
    )
    def versioned_map_asset(
        canonical_name: str,
        revision_id: str,
        level: MapLevel,
    ) -> FileResponse:
        if level not in {MapLevel.UPPER, MapLevel.LOWER}:
            raise HTTPException(status_code=404, detail="Unknown overview level")
        resolved = assets.asset_for_route(canonical_name, revision_id, level)
        if resolved is None:
            raise HTTPException(status_code=404, detail="Pinned overview asset unavailable")
        path, checksum = resolved
        return FileResponse(
            path,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "ETag": f'"{checksum}"',
            },
        )

    @router.get("/ui/maps/calibration", response_class=HTMLResponse, include_in_schema=False)
    def calibration_page(
        map_name: str = "de_mirage",
        revision: str | None = None,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> HTMLResponse:
        if not developer_mode:
            raise HTTPException(status_code=404, detail="Map calibration UI is disabled")
        definition = (
            definitions.get_revision(map_name, revision)
            if revision is not None
            else definitions.preferred_definition(map_name)
        )
        if definition is None:
            raise HTTPException(status_code=404, detail="Map revision unavailable")
        overview = assets.get_definition(definition).model
        result = world_to_map(definition, x, y, z)
        return HTMLResponse(
            render_template(
                "maps/calibration.html",
                maps=tuple(
                    _map_family_response(definitions, assets, item)
                    for item in definitions.list_maps()
                ),
                definition=_definition_response(definition, assets),
                definition_model=definition,
                definition_json=_json_for_script(definition.model_dump(mode="json")),
                overview=overview,
                point={"x": x, "y": y, "z": z},
                result=result,
                match_context=None,
            )
        )

    @router.get(
        "/ui/dev/zones/{canonical_name}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def zones_overlay_page(canonical_name: str) -> HTMLResponse:
        if not developer_mode:
            raise HTTPException(status_code=404, detail="Zone overlay UI is disabled")
        proposals_directory = asset_directory.parent / "zone_proposals"
        payload = _zone_overlay_payload(definitions, assets, proposals_directory, canonical_name)
        payload["editor_json"] = _json_for_script(
            {
                "map_name": payload["map_name"],
                "revision_id": payload["revision_id"],
                "editor": payload.get("editor"),
                "authored_ids": payload.get("authored_ids", []),
                "zones": [
                    {
                        key: zone[key]
                        for key in ("zone_id", "zone_name", "kind", "origin", "polygons_px")
                    }
                    for zone in payload["zones"]
                ],
            }
        )
        return HTMLResponse(render_template("zones/overlay.html", match_context=None, **payload))

    @router.post("/api/dev/zones/{canonical_name}/proposal", tags=["map-calibration"])
    def save_zone_proposal(
        request: Request,
        canonical_name: str,
        proposal: ZoneProposal,
    ) -> dict[str, Any]:
        if not developer_mode:
            raise HTTPException(status_code=404, detail="Zone overlay API is disabled")
        require_localhost(request, "Zone proposal save")
        canonical = definitions.canonicalize(canonical_name)
        if canonical is None:
            raise HTTPException(status_code=404, detail="Unknown map")
        definition = definitions.preferred_definition(canonical)
        if definition is None:
            raise HTTPException(status_code=404, detail="Map revision unavailable")
        revision_id = definition.map_revision.revision_id
        if proposal.map_name != canonical:
            raise HTTPException(
                status_code=409,
                detail=f"Proposal body targets map {proposal.map_name!r}, URL is {canonical!r}.",
            )
        if proposal.revision_id != revision_id:
            raise HTTPException(
                status_code=409,
                detail=f"Proposal targets revision {proposal.revision_id}, map is {revision_id}.",
            )
        zone_set = zone_set_for(canonical, revision_id)
        known = {zone.zone_id for zone in zone_set.zones} if zone_set else set()
        valid_kinds = {kind.value for kind in ZoneKind}
        for zone in proposal.zones:
            if zone.zone_id not in known and (zone.zone_name is None or not zone.zone_name.strip()):
                raise HTTPException(
                    status_code=422,
                    detail=f"New zone {zone.zone_id!r} requires zone_name.",
                )
            if zone.kind is not None and zone.kind not in valid_kinds:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown zone kind {zone.kind!r} for {zone.zone_id!r}.",
                )
            for x, y in zone.polygon:
                if not isfinite(x) or not isfinite(y):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Non-finite polygon coordinate in {zone.zone_id!r}.",
                    )
        duplicate_ids = sorted(
            {zone.zone_id for zone in proposal.zones if
             sum(1 for other in proposal.zones if other.zone_id == zone.zone_id) > 1}
        )
        if duplicate_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate zone ids: {', '.join(duplicate_ids)}.",
            )
        proposals_directory = asset_directory.parent / "zone_proposals"
        proposals_directory.mkdir(parents=True, exist_ok=True)
        target = proposals_directory / f"{canonical}.json"
        target.write_text(
            json.dumps(
                {
                    "map_name": canonical,
                    "revision_id": revision_id,
                    "saved_at": datetime.now(UTC).isoformat(),
                    "zones": [zone.model_dump() for zone in proposal.zones],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"saved": True, "file": target.name, "zone_count": len(proposal.zones)}

    @router.get("/api/dev/zones/{canonical_name}", tags=["map-calibration"])
    def zones_overlay_data(canonical_name: str) -> dict[str, Any]:
        if not developer_mode:
            raise HTTPException(status_code=404, detail="Zone overlay API is disabled")
        proposals_directory = asset_directory.parent / "zone_proposals"
        payload = _zone_overlay_payload(definitions, assets, proposals_directory, canonical_name)
        payload.pop("overview", None)
        return payload

    @router.get("/api/dev/maps/transform-candidate", tags=["map-calibration"])
    def candidate_transform(
        map_name: str,
        revision: str,
        x: Annotated[float, Query(allow_inf_nan=False)],
        y: Annotated[float, Query(allow_inf_nan=False)],
        z: Annotated[float | None, Query(allow_inf_nan=False)] = None,
        origin_x: Annotated[float | None, Query(allow_inf_nan=False)] = None,
        origin_y: Annotated[float | None, Query(allow_inf_nan=False)] = None,
        scale: Annotated[float | None, Query(gt=0, allow_inf_nan=False)] = None,
        level_split_z: Annotated[float | None, Query(allow_inf_nan=False)] = None,
    ) -> dict[str, Any]:
        if not developer_mode:
            raise HTTPException(status_code=404, detail="Map calibration API is disabled")
        definition = definitions.get_revision(map_name, revision)
        if definition is None:
            raise HTTPException(status_code=404, detail="Map revision unavailable")
        updates: dict[str, object] = {}
        if origin_x is not None:
            updates["world_origin_x"] = origin_x
        if origin_y is not None:
            updates["world_origin_y"] = origin_y
        if scale is not None:
            updates["scale"] = scale
        if level_split_z is not None:
            updates["level_split_z"] = level_split_z
            updates["level_policy"] = definition.level_policy.model_copy(
                update={"upper_min_z": level_split_z, "lower_max_z": level_split_z}
            )
        candidate = definition.model_copy(update=updates)
        return {
            "persisted": False,
            "candidate": {
                "world_origin_x": candidate.world_origin_x,
                "world_origin_y": candidate.world_origin_y,
                "scale": candidate.scale,
                "level_split_z": candidate.level_split_z,
            },
            "result": world_to_map(candidate, x, y, z).model_dump(mode="json"),
        }

    return router


def _map_family_response(
    registry: MapRegistry, assets: MapOverviewRegistry, canonical_name: str
) -> dict[str, Any]:
    revisions = registry.revisions(canonical_name)
    preferred = registry.preferred_definition(canonical_name)
    first = revisions[0]
    return {
        "canonical_name": canonical_name,
        "display_name": first.display_name,
        "aliases": first.aliases,
        "preferred_revision": (
            preferred.map_revision.revision_id if preferred is not None else None
        ),
        "revisions": [_definition_response(item, assets) for item in revisions],
    }


def _definition_response(definition: MapDefinition, assets: MapOverviewRegistry) -> dict[str, Any]:
    overview = assets.get_definition(definition).model
    return {
        "canonical_name": definition.canonical_name,
        "display_name": definition.display_name,
        "revision": definition.map_revision.model_dump(mode="json"),
        "supported_game": definition.supported_game,
        "definition_fingerprint": definition.definition_fingerprint,
        "source_coordinate_system": definition.source_coordinate_system,
        "image_width": definition.image_width,
        "image_height": definition.image_height,
        "rotation": definition.rotation,
        "axis_orientation": definition.axis_orientation,
        "level_policy": definition.level_policy.model_dump(mode="json"),
        "asset_version": definition.asset_version,
        "asset_available": overview.status.value == "available",
        "overview_urls": {"upper": overview.image_url, "lower": overview.lower_image_url},
        "calibration_status": definition.calibration_status,
        "validation_status": definition.validation_status,
        "warnings": tuple(dict.fromkeys((*definition.warnings, *overview.warnings))),
    }


def _json_for_script(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return serialized.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


class ZoneProposalZone(BaseModel):
    """One user-placed zone: hand-drawn or hand-adjusted world polygon."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    zone_name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: str | None = None
    origin: str = Field(default="authored", pattern=r"^(authored|user)$")
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=200)


class ZoneProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_name: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    zones: list[ZoneProposalZone] = Field(min_length=1, max_length=100)


def _zone_label_layout(
    zone_name: str,
    kind: str,
    pixel_points: list[tuple[float, float]],
) -> dict[str, Any]:
    """Callout-style label placement: inline when it fits, leader arrow when not.

    Mirrors the official callout maps: bombsites render as a single large
    letter, and a name wider than its zone is lifted above the boundary with
    an arrow down to the zone instead of overflowing it.
    """

    if not pixel_points:
        return {"label_mode": "inline", "short_label": None, "label_x": 0.0, "label_y": 0.0}
    center_x = sum(point[0] for point in pixel_points) / len(pixel_points)
    center_y = sum(point[1] for point in pixel_points) / len(pixel_points)
    if kind == "bombsite":
        return {
            "label_mode": "inline",
            "short_label": zone_name.split()[-1][:1].upper(),
            "label_x": round(center_x, 1),
            "label_y": round(center_y, 1),
        }
    box_width = max(point[0] for point in pixel_points) - min(point[0] for point in pixel_points)
    box_top = min(point[1] for point in pixel_points)
    box_bottom = max(point[1] for point in pixel_points)
    estimated_width = 9.0 * len(zone_name)
    if estimated_width <= box_width * 1.1:
        return {
            "label_mode": "inline",
            "short_label": None,
            "label_x": round(center_x, 1),
            "label_y": round(center_y, 1),
        }
    label_y = box_top - 20.0 if box_top >= 70.0 else box_bottom + 26.0
    label_x = min(max(center_x, 60.0), 964.0)
    return {
        "label_mode": "leader",
        "short_label": None,
        "label_x": round(label_x, 1),
        "label_y": round(label_y, 1),
        "leader_x1": round(label_x, 1),
        "leader_y1": round(label_y + (6.0 if label_y < center_y else -14.0), 1),
        "leader_x2": round(center_x, 1),
        "leader_y2": round(center_y, 1),
    }


def _zone_overlay_payload(
    definitions: MapRegistry,
    assets: MapOverviewRegistry,
    proposals_directory: Path,
    canonical_name: str,
) -> dict[str, Any]:
    canonical = definitions.canonicalize(canonical_name)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Unknown map")
    definition = definitions.preferred_definition(canonical)
    if definition is None:
        raise HTTPException(status_code=404, detail="Map revision unavailable")
    overview = assets.get_definition(definition).model
    revision_id = definition.map_revision.revision_id
    authored_set = zone_set_for(canonical, revision_id)
    authored_ids = {zone.zone_id for zone in authored_set.zones} if authored_set else set()

    zone_set = authored_set
    proposal_active = False
    proposal_saved_at: str | None = None
    proposal_issues: tuple[str, ...] = ()
    user_zone_ids: set[str] = set()
    proposal_file = proposals_directory / f"{canonical}.json"
    proposal_payload = load_zone_proposal(proposal_file)
    if proposal_payload is None:
        if proposal_file.exists():
            proposal_issues = ("proposal_file_unreadable",)
    else:
        effective, proposal_issues = proposal_zone_set(
            proposal_payload, authored_set, canonical, revision_id
        )
        if effective is not None:
            zone_set = effective
            proposal_active = True
            saved_at = proposal_payload.get("saved_at")
            proposal_saved_at = saved_at if isinstance(saved_at, str) else None
            raw_zones = proposal_payload.get("zones")
            if isinstance(raw_zones, list):
                user_zone_ids = {
                    entry["zone_id"]
                    for entry in raw_zones
                    if isinstance(entry, dict)
                    and isinstance(entry.get("zone_id"), str)
                    and entry.get("origin") == "user"
                }

    editor = {
        "world_origin_x": definition.world_origin_x,
        "world_origin_y": definition.world_origin_y,
        "scale": definition.scale,
        "image_width": definition.image_width,
        "image_height": definition.image_height,
        "kinds": [kind.value for kind in ZoneKind],
    }
    if zone_set is None:
        return {
            "map_name": canonical,
            "revision_id": revision_id,
            "display_name": definition.display_name,
            "overview": overview,
            "zone_set": None,
            "zones": [],
            "fingerprint": None,
            "issues": list(proposal_issues),
            "coverage": None,
            "editor": editor if definition.transform_available else None,
            "proposal_active": False,
            "proposal_saved_at": None,
        }
    zones: list[dict[str, Any]] = []
    for zone in zone_set.zones:
        polygons: list[str] = []
        polygons_px: list[list[tuple[float, float]]] = []
        pixel_points: list[tuple[float, float]] = []
        for polygon in zone.polygons:
            points: list[str] = []
            ring: list[tuple[float, float]] = []
            for world_x, world_y in polygon.vertices:
                projected = world_to_map(definition, world_x, world_y, None)
                if projected.pixel_x is None or projected.pixel_y is None:
                    continue
                points.append(f"{projected.pixel_x:.1f},{projected.pixel_y:.1f}")
                ring.append((round(projected.pixel_x, 1), round(projected.pixel_y, 1)))
                pixel_points.append((projected.pixel_x, projected.pixel_y))
            if points:
                polygons.append(" ".join(points))
                polygons_px.append(ring)
        bbox = (
            {
                "px_x1": round(min(point[0] for point in pixel_points), 1),
                "px_y1": round(min(point[1] for point in pixel_points), 1),
                "px_x2": round(max(point[0] for point in pixel_points), 1),
                "px_y2": round(max(point[1] for point in pixel_points), 1),
            }
            if pixel_points
            else None
        )
        zones.append(
            {
                "zone_id": zone.zone_id,
                "zone_name": zone.zone_name,
                "kind": zone.kind.value,
                "level": zone.level.value,
                "priority": zone.priority,
                "verification": zone.verification.value,
                "source": zone.source,
                "area": round(zone_area(zone), 1),
                "svg_polygons": polygons,
                "polygons_px": polygons_px,
                "bbox": bbox,
                "origin": (
                    "user"
                    if zone.zone_id in user_zone_ids or zone.zone_id not in authored_ids
                    else "authored"
                ),
                **_zone_label_layout(zone.zone_name, zone.kind.value, pixel_points),
            }
        )
    return {
        "map_name": canonical,
        "revision_id": revision_id,
        "display_name": definition.display_name,
        "overview": overview,
        "zone_set": zone_set,
        "zones": zones,
        "fingerprint": zone_set.fingerprint(),
        "issues": list(validate_zone_set(zone_set)) + list(proposal_issues),
        "coverage": round(sampled_coverage(zone_set, definition, samples_per_axis=48), 4),
        "editor": editor if definition.transform_available else None,
        "authored_ids": sorted(authored_ids),
        "proposal_active": proposal_active,
        "proposal_saved_at": proposal_saved_at,
    }
