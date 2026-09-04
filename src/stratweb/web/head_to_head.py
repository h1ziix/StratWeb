"""Product UI and JSON endpoints for opponent-versus-own-team comparisons."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from stratweb.adapters.persistence import (
    DuckDBHeadToHeadRepository,
    DuckDBOpponentRepository,
    DuckDBTacticalV2Repository,
)
from stratweb.application.head_to_head import HeadToHeadService
from stratweb.application.opponent_models import OpponentProfile, OpponentSubjectType
from stratweb.application.tactical_v2 import TacticalV2QueryService
from stratweb.exceptions import (
    HeadToHeadConfigurationError,
    HeadToHeadNotFoundError,
    OpponentNotFoundError,
)
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template


def head_to_head_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    opponents = DuckDBOpponentRepository(database_path)
    tactical_repository = DuckDBTacticalV2Repository(database_path)
    service = HeadToHeadService(
        opponents,
        TacticalV2QueryService(tactical_repository),
        DuckDBHeadToHeadRepository(database_path),
    )

    @router.post(
        "/api/opponents/{opponent_profile_id}/head-to-head/compute",
        tags=["head-to-head"],
        response_model=None,
    )
    def compute_head_to_head(
        request: Request,
        opponent_profile_id: UUID,
        our_profile_id: Annotated[UUID, Form()],
    ) -> Response:
        require_localhost(request, "Head-to-head computation")
        _require_team_profile(opponents, opponent_profile_id)
        _require_team_profile(opponents, our_profile_id)
        try:
            state, saved = service.compute(opponent_profile_id, our_profile_id)
        except HeadToHeadConfigurationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OpponentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(
                f"/ui/opponents/{opponent_profile_id}/head-to-head?our_profile_id={our_profile_id}",
                status_code=303,
            )
        return JSONResponse(
            content={
                "result": saved.model_dump(mode="json"),
                "summary": state.summary.model_dump(mode="json"),
                "warnings": list(state.warnings),
            }
        )

    @router.get(
        "/api/opponents/{opponent_profile_id}/head-to-head/summary",
        tags=["head-to-head"],
    )
    def head_to_head_summary(
        opponent_profile_id: UUID,
        our_profile_id: UUID,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        _require_team_profile(opponents, opponent_profile_id)
        _require_team_profile(opponents, our_profile_id)
        try:
            result = (
                service.get_run(opponent_profile_id, our_profile_id, run_id)
                if run_id is not None
                else service.get_current(opponent_profile_id, our_profile_id)
            )
        except HeadToHeadConfigurationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @router.get(
        "/api/opponents/{opponent_profile_id}/head-to-head/runs",
        tags=["head-to-head"],
    )
    def head_to_head_runs(opponent_profile_id: UUID, our_profile_id: UUID) -> dict[str, Any]:
        _require_team_profile(opponents, opponent_profile_id)
        _require_team_profile(opponents, our_profile_id)
        values = service.list_runs(opponent_profile_id, our_profile_id)
        return {
            "opponent_profile_id": str(opponent_profile_id),
            "our_profile_id": str(our_profile_id),
            "count": len(values),
            "runs": [item.model_dump(mode="json") for item in values],
        }

    @router.get(
        "/ui/opponents/{opponent_profile_id}/head-to-head",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def head_to_head_page(
        opponent_profile_id: UUID,
        our_profile_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> HTMLResponse:
        opponent = _require_team_profile(opponents, opponent_profile_id)
        profiles = tuple(
            profile
            for profile in opponents.list_profiles()
            if profile.profile_id != opponent_profile_id
            and profile.subject_type is OpponentSubjectType.TEAM
        )
        own_profile = (
            _require_team_profile(opponents, our_profile_id) if our_profile_id is not None else None
        )
        comparison = None
        unavailable_reason = None
        if our_profile_id is not None:
            if own_profile is None:
                unavailable_reason = "Профиль нашей команды не найден."
            else:
                try:
                    comparison = (
                        service.get_run(opponent_profile_id, our_profile_id, run_id)
                        if run_id is not None
                        else service.get_current(opponent_profile_id, our_profile_id)
                    )
                except (HeadToHeadConfigurationError, HeadToHeadNotFoundError) as exc:
                    unavailable_reason = str(exc)
        return HTMLResponse(
            render_template(
                "opponents/head_to_head.html",
                opponent=opponent,
                profiles=profiles,
                our_profile=own_profile,
                selected_our_profile_id=our_profile_id,
                comparison=comparison,
                unavailable_reason=unavailable_reason,
                match_context=None,
            )
        )

    return router


def _require_team_profile(opponents: DuckDBOpponentRepository, profile_id: UUID) -> OpponentProfile:
    profile = opponents.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль соперника не найден.")
    if profile.subject_type is OpponentSubjectType.PLAYER:
        raise HTTPException(
            status_code=409,
            detail="Сравнение «мы против них» доступно только для командных профилей.",
        )
    return profile


__all__ = ["head_to_head_router"]
