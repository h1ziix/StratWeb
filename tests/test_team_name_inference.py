from __future__ import annotations

from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid5

import polars as pl

from stratweb.application.canonical_models import CanonicalPlayer, CanonicalRound, CanonicalTeam
from stratweb.application.team_name_inference import apply_inferred_team_names, infer_team_names
from stratweb.contracts import ParsedDemo, ParserIdentity

_MATCH_ID = UUID("00000000-0000-0000-0000-000000000901")


def _player(key: str, name: str) -> CanonicalPlayer:
    player_id = uuid5(NAMESPACE_URL, f"player:{key}")
    return CanonicalPlayer(
        player_id=player_id,
        steam_id=str(player_id.int % 10**17 + 1),
        current_name=name,
        known_names=(name,),
    )


def _fixture() -> tuple[
    ParsedDemo,
    tuple[CanonicalTeam, ...],
    tuple[CanonicalRound, ...],
    tuple[CanonicalPlayer, ...],
]:
    captain = _player("captain", "Captain")
    alpha_two = _player("alpha-two", "AlphaTwo")
    bravo_one = _player("bravo-one", "BravoOne")
    bravo_two = _player("bravo-two", "BravoTwo")
    team_alpha_id = uuid5(_MATCH_ID, "team-alpha")
    team_bravo_id = uuid5(_MATCH_ID, "team-bravo")
    teams = (
        CanonicalTeam(
            team_id=team_alpha_id,
            match_id=_MATCH_ID,
            internal_name="TeamAlpha",
            starting_player_ids=(captain.player_id, alpha_two.player_id),
            identity_confidence=1,
        ),
        CanonicalTeam(
            team_id=team_bravo_id,
            match_id=_MATCH_ID,
            internal_name="TeamBravo",
            starting_player_ids=(bravo_one.player_id, bravo_two.player_id),
            identity_confidence=1,
        ),
    )
    rounds = (
        CanonicalRound(
            round_id=uuid5(_MATCH_ID, "round-1"),
            match_id=_MATCH_ID,
            round_number=1,
            start_tick=100,
            freeze_end_tick=120,
            end_tick=190,
            t_team_id=team_alpha_id,
            ct_team_id=team_bravo_id,
            is_complete=True,
        ),
        CanonicalRound(
            round_id=uuid5(_MATCH_ID, "round-2"),
            match_id=_MATCH_ID,
            round_number=2,
            start_tick=200,
            freeze_end_tick=220,
            end_tick=290,
            t_team_id=team_alpha_id,
            ct_team_id=team_bravo_id,
            is_complete=True,
        ),
        CanonicalRound(
            round_id=uuid5(_MATCH_ID, "round-3"),
            match_id=_MATCH_ID,
            round_number=3,
            start_tick=300,
            freeze_end_tick=320,
            end_tick=390,
            t_team_id=team_bravo_id,
            ct_team_id=team_alpha_id,
            is_complete=True,
        ),
    )
    parsed = ParsedDemo(
        demo_file_id=uuid5(_MATCH_ID, "demo"),
        parser=ParserIdentity(name="demoparser2", version="0.41.4"),
        header={"map_name": "de_dust2"},
        tables={
            "round_freeze_end": pl.DataFrame(
                {
                    "tick": [120, 220, 320],
                    "t_team_clan_name": ["team_Captain", "team_Captain", "Falcons"],
                    "ct_team_clan_name": ["Falcons", "Falcons", "team_Captain"],
                }
            )
        },
        available_events=("round_freeze_end",),
    )
    return parsed, teams, rounds, (captain, alpha_two, bravo_one, bravo_two)


def test_demo_clan_name_follows_physical_team_across_side_switch() -> None:
    parsed, teams, rounds, players = _fixture()

    inferred = {item.team_id: item for item in infer_team_names(parsed, teams, rounds, players)}

    assert inferred[teams[0].team_id].display_name == "team_Captain"
    assert inferred[teams[0].team_id].source == "round_team_clan_name"
    assert inferred[teams[0].team_id].numerator == 3
    assert inferred[teams[0].team_id].denominator == 3
    assert inferred[teams[1].team_id].display_name == "Falcons"
    applied = apply_inferred_team_names(parsed, teams, rounds, players)
    assert any("support=3/3" in warning for warning in applied[0].warnings)


def test_generated_faceit_name_requires_suffix_to_match_roster_nickname() -> None:
    parsed, teams, rounds, players = _fixture()
    frame = parsed.tables["round_freeze_end"].with_columns(
        pl.lit("team_123456").alias("t_team_clan_name"),
        pl.when(pl.col("tick") == 320)
        .then(pl.lit("team_123456"))
        .otherwise(pl.col("ct_team_clan_name"))
        .alias("ct_team_clan_name"),
    )
    parsed = replace(parsed, tables={"round_freeze_end": frame})

    inferred = {item.team_id: item for item in infer_team_names(parsed, teams, rounds, players)}

    assert inferred[teams[0].team_id].display_name is None
    assert inferred[teams[1].team_id].display_name == "Falcons"


def test_explicit_nickname_tag_requires_roster_majority() -> None:
    parsed, teams, rounds, players = _fixture()
    tagged = (
        _player("tag-a", "[NAVI] alice"),
        _player("tag-b", "[NAVI] bob"),
        _player("tag-c", "[NAVI] carol"),
        _player("tag-d", "plain"),
    )
    team = teams[0].model_copy(
        update={"starting_player_ids": tuple(item.player_id for item in tagged)}
    )
    parsed = replace(parsed, tables={})

    inferred = infer_team_names(parsed, (team,), rounds, (*players, *tagged))[0]

    assert inferred.display_name == "NAVI"
    assert inferred.source == "player_nickname_clan_tag"
    assert (inferred.numerator, inferred.denominator, inferred.frequency) == (3, 4, 0.75)


def test_conflicting_round_names_are_not_guessed() -> None:
    parsed, teams, rounds, players = _fixture()
    frame = parsed.tables["round_freeze_end"].with_columns(
        pl.Series("t_team_clan_name", ["One", "Two", "Falcons"]),
        pl.Series("ct_team_clan_name", ["Falcons", "Falcons", "Three"]),
    )
    parsed = replace(parsed, tables={"round_freeze_end": frame})

    inferred = {item.team_id: item for item in infer_team_names(parsed, teams, rounds, players)}

    assert inferred[teams[0].team_id].display_name is None
    assert inferred[teams[1].team_id].display_name == "Falcons"
