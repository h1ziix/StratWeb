"""Read-only map registry API, immutable assets, and developer calibration UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBSpatialRepository
from stratweb.maps.models import MapDefinition, MapLevel, MapSelectionEvidence
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY, MapRegistry
from stratweb.maps.transforms import world_to_map
from stratweb.spatial.map_overviews import MapOverviewRegistry
from stratweb.web.rendering import render_template
from stratweb.zones.definitions import zone_set_for
from stratweb.zones.engine import zone_area
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
        payload = _zone_overlay_payload(definitions, assets, canonical_name)
        return HTMLResponse(render_template("zones/overlay.html", match_context=None, **payload))

    @router.get("/api/dev/zones/{canonical_name}", tags=["map-calibration"])
    def zones_overlay_data(canonical_name: str) -> dict[str, Any]:
        if not developer_mode:
            raise HTTPException(status_code=404, detail="Zone overlay API is disabled")
        payload = _zone_overlay_payload(definitions, assets, canonical_name)
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


def _zone_overlay_payload(
    definitions: MapRegistry,
    assets: MapOverviewRegistry,
    canonical_name: str,
) -> dict[str, Any]:
    canonical = definitions.canonicalize(canonical_name)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Unknown map")
    definition = definitions.preferred_definition(canonical)
    if definition is None:
        raise HTTPException(status_code=404, detail="Map revision unavailable")
    overview = assets.get_definition(definition).model
    zone_set = zone_set_for(canonical, definition.map_revision.revision_id)
    if zone_set is None:
        return {
            "map_name": canonical,
            "revision_id": definition.map_revision.revision_id,
            "display_name": definition.display_name,
            "overview": overview,
            "zone_set": None,
            "zones": [],
            "fingerprint": None,
            "issues": [],
            "coverage": None,
        }
    zones: list[dict[str, Any]] = []
    for zone in zone_set.zones:
        polygons: list[str] = []
        label_x = label_y = 0.0
        vertex_count = 0
        for polygon in zone.polygons:
            points: list[str] = []
            for world_x, world_y in polygon.vertices:
                projected = world_to_map(definition, world_x, world_y, None)
                if projected.pixel_x is None or projected.pixel_y is None:
                    continue
                points.append(f"{projected.pixel_x:.1f},{projected.pixel_y:.1f}")
                label_x += projected.pixel_x
                label_y += projected.pixel_y
                vertex_count += 1
            if points:
                polygons.append(" ".join(points))
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
                "label_x": round(label_x / vertex_count, 1) if vertex_count else 0.0,
                "label_y": round(label_y / vertex_count, 1) if vertex_count else 0.0,
            }
        )
    return {
        "map_name": canonical,
        "revision_id": definition.map_revision.revision_id,
        "display_name": definition.display_name,
        "overview": overview,
        "zone_set": zone_set,
        "zones": zones,
        "fingerprint": zone_set.fingerprint(),
        "issues": list(validate_zone_set(zone_set)),
        "coverage": round(sampled_coverage(zone_set, definition, samples_per_axis=48), 4),
    }
