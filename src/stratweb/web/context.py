"""Shared evidence-safe application-shell context."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from stratweb.application.canonical_models import CanonicalRound, CanonicalTeam
from stratweb.application.persistence_models import StoredMatch


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
