"""Coach-first critical mistakes page and JSON endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from stratweb.adapters.persistence import (
    DuckDBCriticalMistakesRepository,
    DuckDBOpponentRepository,
)
from stratweb.application.critical_mistakes import CriticalMistakesService
from stratweb.critical_mistakes.models import CriticalMistakeType
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template


def critical_mistakes_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    opponents = DuckDBOpponentRepository(database_path)
    service = CriticalMistakesService(DuckDBCriticalMistakesRepository(database_path))

    @router.post(
        "/api/opponents/{profile_id}/critical-mistakes/compute",
        tags=["critical-mistakes"],
        response_model=None,
    )
    def compute(request: Request, profile_id: UUID) -> Response:
        require_localhost(request, "Critical mistakes computation")
        if opponents.get_profile(profile_id) is None:
            raise HTTPException(status_code=404, detail="Профиль соперника не найден.")
        state, result = service.compute(profile_id)
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(
                f"/ui/opponents/{profile_id}/critical-mistakes", status_code=303
            )
        return JSONResponse(
            {"result": result.model_dump(mode="json"), "summary": state.summary.model_dump()}
        )

    @router.get(
        "/api/opponents/{profile_id}/critical-mistakes",
        tags=["critical-mistakes"],
    )
    def summary(profile_id: UUID) -> dict[str, Any]:
        state = service.get_latest(profile_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Фильтр ещё не рассчитан.")
        return state.model_dump(mode="json")

    @router.get(
        "/ui/opponents/{profile_id}/critical-mistakes",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def page(
        profile_id: UUID,
        mistake_type: CriticalMistakeType | None = None,
    ) -> HTMLResponse:
        profile = opponents.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Профиль соперника не найден.")
        state = service.get_latest(profile_id)
        mistakes = (
            tuple(
                item
                for item in state.mistakes
                if mistake_type is None or item.mistake_type is mistake_type
            )
            if state
            else ()
        )
        selected_capability = (
            state.capabilities.get(mistake_type)
            if state is not None and mistake_type is not None
            else None
        )
        unavailable_types = (
            tuple(
                kind for kind, status in state.capabilities.items() if status.value == "unavailable"
            )
            if state is not None
            else ()
        )
        return HTMLResponse(
            render_template(
                "opponents/critical_mistakes.html",
                profile=profile,
                result=state,
                mistakes=mistakes,
                selected_type=mistake_type,
                selected_capability=selected_capability,
                unavailable_types=unavailable_types,
                mistake_types=tuple(CriticalMistakeType),
                match_context=None,
            )
        )

    return router


__all__ = ["critical_mistakes_router"]
