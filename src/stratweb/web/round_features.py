"""Read-only API for version-pinned Stage 8.4 per-round facts."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBRoundFeatureRepository
from stratweb.application.round_features import RoundFeatureQueryService
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import RoundFeatureNotFoundError
from stratweb.features.models import FeatureAvailability, RoundFeatureType
from stratweb.web.context import build_match_context
from stratweb.web.rendering import render_template
from stratweb.web.view_models import build_round_feature_page, feature_type_options

_UI_PAGE_SIZE = 100


def round_feature_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    service = RoundFeatureQueryService(DuckDBRoundFeatureRepository(database_path))
    matches = DuckDBMatchRepository(database_path)

    @router.get(
        "/ui/matches/{match_id}/features",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def feature_page(
        match_id: UUID,
        run_id: UUID | None = None,
        round_number: Annotated[int | None, Query(alias="round", ge=1)] = None,
        team_id: Annotated[UUID | None, Query(alias="team")] = None,
        side: Side | None = None,
        feature_type: Annotated[RoundFeatureType | None, Query(alias="type")] = None,
        availability: FeatureAvailability | None = None,
        buy_type: BuyType | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> HTMLResponse:
        stored = matches.get_match(match_id)
        if stored is None:
            raise HTTPException(status_code=404, detail=f"Match not found: {match_id}")
        canonical_teams = matches.get_teams(match_id)
        canonical_rounds = matches.get_rounds(match_id)
        match_context = build_match_context(stored, canonical_teams, canonical_rounds)
        common = {
            "match_context": match_context,
            "feature_types": feature_type_options(),
            "availability_values": tuple(item.value for item in FeatureAvailability),
            "buy_types": tuple(item.value for item in BuyType),
            "team_options": tuple(
                (
                    str(item.team_id),
                    item.display_name or item.internal_name,
                )
                for item in canonical_teams
            ),
            "selected_round": round_number,
            "selected_team": str(team_id) if team_id is not None else "",
            "selected_side": side.value if side is not None else "",
            "selected_type": feature_type.value if feature_type is not None else "",
            "selected_availability": availability.value if availability is not None else "",
            "selected_buy_type": buy_type.value if buy_type is not None else "",
        }
        try:
            selected_summary = service.get_summary(match_id, feature_run_id=run_id)
        except RoundFeatureNotFoundError:
            return HTMLResponse(
                render_template("matches/round_features.html", features=None, **common)
            )
        pinned_run_id = selected_summary.feature_run_id
        offset = (page - 1) * _UI_PAGE_SIZE
        selected = service.list_features(
            match_id,
            feature_run_id=pinned_run_id,
            round_number=round_number,
            team_id=team_id,
            side=side,
            feature_type=feature_type,
            availability=availability,
            buy_type=buy_type,
            limit=_UI_PAGE_SIZE + 1,
            offset=offset,
        )
        has_next = len(selected) > _UI_PAGE_SIZE
        visible = selected[:_UI_PAGE_SIZE]
        query_values: dict[str, str | int] = {"run_id": str(pinned_run_id)}
        for key, value in (
            ("round", round_number),
            ("team", str(team_id) if team_id is not None else None),
            ("side", side.value if side is not None else None),
            ("type", feature_type.value if feature_type is not None else None),
            (
                "availability",
                availability.value if availability is not None else None,
            ),
            ("buy_type", buy_type.value if buy_type is not None else None),
        ):
            if value is not None:
                query_values[key] = value

        def page_href(target_page: int) -> str:
            return f"/ui/matches/{match_id}/features?" + urlencode(
                {**query_values, "page": target_page}
            )

        features = build_round_feature_page(
            selected_summary,
            visible,
            team_names={
                item.team_id: item.display_name or item.internal_name for item in canonical_teams
            },
            player_names={
                item.player_id: item.current_name for item in matches.get_players(match_id)
            },
            page=page,
            page_size=_UI_PAGE_SIZE,
            previous_href=page_href(page - 1) if page > 1 else None,
            next_href=page_href(page + 1) if has_next else None,
        )
        return HTMLResponse(
            render_template(
                "matches/round_features.html",
                features=features,
                **common,
            )
        )

    @router.get("/api/features/{match_id}/summary", tags=["round-features"])
    def summary(match_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        return service.get_summary(match_id, feature_run_id=run_id).model_dump(mode="json")

    @router.get("/api/features/{match_id}/runs", tags=["round-features"])
    def runs(match_id: UUID) -> dict[str, Any]:
        values = service.list_runs(match_id)
        return {
            "match_id": str(match_id),
            "runs": [item.model_dump(mode="json") for item in values],
        }

    @router.get("/api/features/{match_id}/records", tags=["round-features"])
    def records(
        match_id: UUID,
        run_id: UUID | None = None,
        round_number: Annotated[int | None, Query(alias="round", ge=1)] = None,
        team_id: UUID | None = None,
        side: Side | None = None,
        feature_type: Annotated[RoundFeatureType | None, Query(alias="type")] = None,
        availability: FeatureAvailability | None = None,
        buy_type: BuyType | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        values = service.list_features(
            match_id,
            feature_run_id=run_id,
            round_number=round_number,
            team_id=team_id,
            side=side,
            feature_type=feature_type,
            availability=availability,
            buy_type=buy_type,
            limit=limit,
            offset=offset,
        )
        return {
            "match_id": str(match_id),
            "count": len(values),
            "features": [item.model_dump(mode="json") for item in values],
        }

    return router


__all__ = ["round_feature_router"]
