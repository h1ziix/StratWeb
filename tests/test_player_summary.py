from __future__ import annotations

from uuid import UUID

import polars as pl

from stratweb.application.inspection import _summarize_players
from stratweb.contracts import ParsedDemo, ParserIdentity


def test_player_summary_deduplicates_same_steam_id_across_team_labels() -> None:
    parsed = ParsedDemo(
        demo_file_id=UUID("00000000-0000-0000-0000-000000000001"),
        parser=ParserIdentity(name="fake", version="1"),
        header={},
        tables={
            "player_team": pl.DataFrame(
                {
                    "player_steamid": ["76561198000000001", "76561198000000001"],
                    "player_name": ["Alpha", "Alpha"],
                    "player_team": ["T", "CT"],
                }
            )
        },
    )

    players, _teams, count, _warnings = _summarize_players(parsed)

    assert count == 1
    assert len(players) == 1
