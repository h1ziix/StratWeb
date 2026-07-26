"""Shared evidence-safe application-shell context."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException, Request

from stratweb.application.canonical_models import CanonicalRound, CanonicalTeam
from stratweb.application.persistence_models import StoredMatch

# "testclient" is the synthetic client host set by the ASGI test transport;
# the app is a localhost-only tool with no auth, so real remote hosts stay out.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "testclient"})
_LOOPBACK_ORIGIN_HOSTNAMES = frozenset({"127.0.0.1", "::1", "localhost"})


def require_localhost(request: Request, action: str) -> None:
    """Reject mutations from non-loopback clients and cross-site browser origins."""

    host = request.client.host if request.client else ""
    if host not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail=f"{action} is localhost-only.")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).hostname not in _LOOPBACK_ORIGIN_HOSTNAMES:
        raise HTTPException(
            status_code=403,
            detail=f"Cross-origin {action.lower()} is not allowed.",
        )


def build_match_context(
    stored: StoredMatch,
    teams: tuple[CanonicalTeam, ...],
    rounds: tuple[CanonicalRound, ...],
) -> dict[str, Any]:
    """Build a physical-team score instead of exposing post-swap side totals."""

    scores: dict[UUID, int] = {}
    for round_item in rounds:
        if round_item.t_team_id is not None and round_item.score_t_after is not None:
            scores[round_item.t_team_id] = round_item.score_t_after
        if round_item.ct_team_id is not None and round_item.score_ct_after is not None:
            scores[round_item.ct_team_id] = round_item.score_ct_after
    score = "Score unavailable"
    if teams and all(team.team_id in scores for team in teams):
        score = ":".join(str(scores[team.team_id]) for team in teams)
    return {
        "match_id": stored.match_id,
        "short_id": str(stored.match_id).split("-")[0],
        "map_name": stored.map_name or "Unknown map",
        "team_names": tuple(team.display_name or team.internal_name for team in teams),
        "score": score,
    }
