"""Read-only JSON API for persisted zone-assignment evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query

from stratweb.adapters.persistence import DuckDBZoneAssignmentRepository
from stratweb.application.zone_assignments import ZoneAssignmentQueryService
from stratweb.zones.assignment_models import ZoneAssignmentStatus


def zone_assignment_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    service = ZoneAssignmentQueryService(DuckDBZoneAssignmentRepository(database_path))

    @router.get("/api/zones/{match_id}/summary", tags=["zone-assignment"])
    def summary(match_id: UUID, spatial_run_id: UUID | None = None) -> dict[str, Any]:
        return service.get_summary(match_id, spatial_run_id=spatial_run_id).model_dump(mode="json")

    @router.get("/api/zones/{match_id}/runs", tags=["zone-assignment"])
    def runs(match_id: UUID) -> dict[str, Any]:
        values = service.list_runs(match_id)
        return {
            "match_id": str(match_id),
            "runs": [item.model_dump(mode="json") for item in values],
        }

    @router.get("/api/zones/{match_id}/assignments", tags=["zone-assignment"])
    def assignments(
        match_id: UUID,
        run_id: UUID | None = None,
        round_number: Annotated[int | None, Query(alias="round", ge=1)] = None,
        status: ZoneAssignmentStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        values = service.list_assignments(
            match_id,
            zone_assignment_run_id=run_id,
            round_number=round_number,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "match_id": str(match_id),
            "count": len(values),
            "assignments": [item.model_dump(mode="json") for item in values],
        }

    return router


__all__ = ["zone_assignment_router"]
