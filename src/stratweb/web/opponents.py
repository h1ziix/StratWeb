"""Server-rendered and JSON endpoints for opponent workspace management."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBOpponentRepository
from stratweb.application.opponent_models import OpponentWorkspace
from stratweb.application.opponents import OpponentWorkspaceService
from stratweb.exceptions import (
    MatchNotFoundError,
    OpponentConflictError,
    OpponentNotFoundError,
    OpponentSelectionError,
)
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template


def opponent_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    service = OpponentWorkspaceService(
        DuckDBOpponentRepository(database_path),
        DuckDBMatchRepository(database_path),
    )

    @router.get("/ui/opponents", response_class=HTMLResponse, include_in_schema=False)
    def opponent_library() -> HTMLResponse:
        return HTMLResponse(
            render_template(
                "opponents/library.html",
                profiles=service.list_profiles(),
                match_context=None,
            )
        )

    @router.get(
        "/ui/opponents/{profile_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def opponent_workspace(profile_id: UUID) -> HTMLResponse:
        workspace = _workspace(service, profile_id)
        return HTMLResponse(
            render_template(
                "opponents/workspace.html",
                workspace=workspace,
                match_context=None,
            )
        )

    @router.get("/api/opponents", tags=["opponents"])
    def list_opponents() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in service.list_profiles()]

    @router.get("/api/opponents/{profile_id}", tags=["opponents"])
    def get_opponent(profile_id: UUID) -> dict[str, Any]:
        return _workspace(service, profile_id).model_dump(mode="json")

    @router.post("/api/opponents", status_code=201, tags=["opponents"], response_model=None)
    def create_opponent(
        request: Request,
        display_name: Annotated[str, Form(min_length=1, max_length=100)],
    ) -> Response:
        _require_localhost(request)
        try:
            profile = service.create_profile(display_name)
        except OpponentConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OpponentSelectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/opponents/{profile.profile_id}", status_code=303)
        return JSONResponse(status_code=201, content=profile.model_dump(mode="json"))

    @router.post(
        "/api/opponents/{profile_id}/matches",
        status_code=200,
        tags=["opponents"],
        response_model=None,
    )
    def assign_match(
        request: Request,
        profile_id: UUID,
        match_id: Annotated[UUID, Form()],
        team_id: Annotated[UUID, Form()],
    ) -> Response:
        _require_localhost(request)
        try:
            selection = service.assign_match(profile_id, match_id, team_id)
        except OpponentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MatchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OpponentSelectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/opponents/{profile_id}", status_code=303)
        return JSONResponse(status_code=200, content=selection.model_dump(mode="json"))

    @router.post(
        "/api/opponents/{profile_id}/rename",
        status_code=200,
        tags=["opponents"],
        response_model=None,
    )
    def rename_opponent(
        request: Request,
        profile_id: UUID,
        display_name: Annotated[str, Form(min_length=1, max_length=100)],
    ) -> Response:
        _require_localhost(request)
        try:
            profile = service.rename_profile(profile_id, display_name)
        except OpponentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OpponentConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OpponentSelectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/opponents/{profile_id}", status_code=303)
        return JSONResponse(status_code=200, content=profile.model_dump(mode="json"))

    @router.post(
        "/api/opponents/{profile_id}/delete",
        status_code=200,
        tags=["opponents"],
        response_model=None,
    )
    def delete_opponent(request: Request, profile_id: UUID) -> Response:
        _require_localhost(request)
        try:
            service.delete_profile(profile_id)
        except OpponentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OpponentConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/ui/opponents", status_code=303)
        return JSONResponse(
            status_code=200,
            content={"profile_id": str(profile_id), "deleted": True},
        )

    @router.post(
        "/api/opponents/{profile_id}/matches/{match_id}/remove",
        status_code=200,
        tags=["opponents"],
        response_model=None,
    )
    def remove_match(request: Request, profile_id: UUID, match_id: UUID) -> Response:
        _require_localhost(request)
        try:
            removed = service.remove_match(profile_id, match_id)
        except OpponentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail="Opponent match selection not found.")
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/opponents/{profile_id}", status_code=303)
        return JSONResponse(
            status_code=200,
            content={"profile_id": str(profile_id), "match_id": str(match_id), "removed": True},
        )

    return router


def _workspace(
    service: OpponentWorkspaceService,
    profile_id: UUID,
) -> OpponentWorkspace:
    try:
        return service.get_workspace(profile_id)
    except OpponentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _require_localhost(request: Request) -> None:
    require_localhost(request, "Opponent workspace change")


__all__ = ["opponent_router"]
