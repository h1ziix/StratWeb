"""Read-only UI and JSON API for persisted economy and equipment evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from stratweb.adapters.persistence import (
    DuckDBEconomyRepository,
    DuckDBMatchRepository,
    DuckDBTeamNameRepository,
)
from stratweb.application.economy import EconomyQueryService
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import EconomyNotFoundError
from stratweb.web.context import build_match_context
from stratweb.web.rendering import render_template
from stratweb.web.view_models import build_economy_page


def economy_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    service = EconomyQueryService(DuckDBEconomyRepository(database_path))
    matches = DuckDBMatchRepository(database_path)
    team_names = DuckDBTeamNameRepository(database_path)

    @router.get(
        "/ui/matches/{match_id}/economy",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def economy_page(
        match_id: UUID,
        run_id: UUID | None = None,
        round_number: Annotated[int | None, Query(alias="round", ge=1)] = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
    ) -> HTMLResponse:
        stored = matches.get_match(match_id)
        if stored is None:
            raise HTTPException(status_code=404, detail=f"Match not found: {match_id}")
        canonical_teams = matches.get_teams(match_id)
        canonical_rounds = matches.get_rounds(match_id)
        match_context = build_match_context(stored, canonical_teams, canonical_rounds)
        display_labels = {
            item.team_id: item.display_name for item in team_names.list_for_match(match_id)
        }
        match_context["team_names"] = tuple(
            display_labels.get(item.team_id, item.display_name or item.internal_name)
            for item in canonical_teams
        )
        try:
            selected_summary = service.get_summary(match_id, economy_run_id=run_id)
        except EconomyNotFoundError:
            return HTMLResponse(
                render_template(
                    "matches/economy.html",
                    economy=None,
                    match_context=match_context,
                    selected_side=side.value if side is not None else "",
                    selected_buy_type=buy_type.value if buy_type is not None else "",
                    selected_round=round_number,
                    buy_types=tuple(item.value for item in BuyType),
                )
            )

        pinned_run_id = selected_summary.economy_run_id
        team_snapshots = service.list_team_snapshots(
            match_id,
            economy_run_id=pinned_run_id,
            round_number=round_number,
            side=side,
            buy_type=buy_type,
            limit=5000,
        )
        player_snapshots = service.list_player_snapshots(
            match_id,
            economy_run_id=pinned_run_id,
            round_number=round_number,
            limit=5000,
        )
        visible_team_rounds = {(item.round_number, item.side) for item in team_snapshots}
        visible_players = tuple(
            item
            for item in player_snapshots
            if (item.round_number, item.side) in visible_team_rounds
        )
        economy = build_economy_page(
            selected_summary,
            team_snapshots,
            visible_players,
            {
                item.team_id: display_labels.get(
                    item.team_id, item.display_name or item.internal_name
                )
                for item in canonical_teams
            },
        )
        return HTMLResponse(
            render_template(
                "matches/economy.html",
                economy=economy,
                match_context=match_context,
                selected_side=side.value if side is not None else "",
                selected_buy_type=buy_type.value if buy_type is not None else "",
                selected_round=round_number,
                buy_types=tuple(item.value for item in BuyType),
            )
        )

    @router.get("/api/economy/{match_id}/summary", tags=["economy"])
    def summary(match_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        return service.get_summary(match_id, economy_run_id=run_id).model_dump(mode="json")

    @router.get("/api/economy/{match_id}/runs", tags=["economy"])
    def runs(match_id: UUID) -> dict[str, Any]:
        values = service.list_runs(match_id)
        return {
            "match_id": str(match_id),
            "runs": [item.model_dump(mode="json") for item in values],
        }

    @router.get("/api/economy/{match_id}/teams", tags=["economy"])
    def teams(
        match_id: UUID,
        run_id: UUID | None = None,
        round_number: Annotated[int | None, Query(alias="round", ge=1)] = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        values = service.list_team_snapshots(
            match_id,
            economy_run_id=run_id,
            round_number=round_number,
            side=side,
            buy_type=buy_type,
            limit=limit,
            offset=offset,
        )
        return {
            "match_id": str(match_id),
            "count": len(values),
            "team_snapshots": [item.model_dump(mode="json") for item in values],
        }

    @router.get("/api/economy/{match_id}/players", tags=["economy"])
    def players(
        match_id: UUID,
        run_id: UUID | None = None,
        round_number: Annotated[int | None, Query(alias="round", ge=1)] = None,
        participant_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        values = service.list_player_snapshots(
            match_id,
            economy_run_id=run_id,
            round_number=round_number,
            participant_id=participant_id,
            limit=limit,
            offset=offset,
        )
        return {
            "match_id": str(match_id),
            "count": len(values),
            "player_snapshots": [item.model_dump(mode="json") for item in values],
        }

    return router


__all__ = ["economy_router"]
