from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid5

import pytest

from stratweb.adapters.persistence import DuckDBMatchRepository
from stratweb.web.context import build_match_context
from stratweb.web.rendering import static_asset


def test_static_asset_url_changes_with_file_metadata_and_rejects_traversal() -> None:
    url = static_asset("js/spatial-player.js")

    assert url.startswith("/static/js/spatial-player.js?v=")
    assert len(url.partition("?v=")[2]) > 3
    with pytest.raises(ValueError, match="inside"):
        static_asset("../templates/base.html")


def test_match_context_score_follows_physical_teams_across_side_swap(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("match-context-score")
    repository = DuckDBMatchRepository(tmp_path / "context.duckdb")
    repository.save_match(dataset, source_original_name="score.dem")
    stored = repository.get_match(dataset.match.match_id)
    assert stored is not None
    first = dataset.rounds[0]
    second = first.model_copy(
        update={
            "round_id": uuid5(dataset.match.match_id, "round:2"),
            "round_number": 2,
            "start_tick": 300,
            "freeze_end_tick": 310,
            "end_tick": 390,
            "official_end_tick": 400,
            "t_team_id": dataset.teams[1].team_id,
            "ct_team_id": dataset.teams[0].team_id,
            "score_t_before": 0,
            "score_ct_before": 1,
            "score_t_after": 0,
            "score_ct_after": 2,
        }
    )

    context = build_match_context(stored, dataset.teams, (first, second))

    assert context["team_names"] == ("TeamAlpha", "TeamBravo")
    assert context["score"] == "2:0"
