from __future__ import annotations

from uuid import UUID, uuid4

import polars as pl

from stratweb.application.canonical_models import (
    CanonicalRound,
    DataAvailability,
    EventPhase,
)
from stratweb.application.canonicalization import CanonicalMatchNormalizer
from stratweb.application.identity_resolution import (
    PlayerResolutionResult,
    SideObservation,
    TeamResolver,
)
from stratweb.application.normalization_utils import normalize_side
from stratweb.application.round_assignment import RoundAssignmentService
from stratweb.application.round_resolution import RoundResolver
from stratweb.application.validation import CanonicalDatasetValidator, ValidationInput
from stratweb.contracts import ParsedDemo, ParserIdentity
from stratweb.domain.enums import Side
from stratweb.ports import EventNormalizer

_MATCH_ID = UUID("00000000-0000-0000-0000-000000000111")
_DEMO_ID = UUID("00000000-0000-0000-0000-000000000222")
_SHA = "a" * 64


def _parsed(tables: dict[str, pl.DataFrame], player_info: pl.DataFrame | None = None) -> ParsedDemo:
    return ParsedDemo(
        demo_file_id=_DEMO_ID,
        parser=ParserIdentity(name="demoparser2", version="0.41.4"),
        header={"map_name": "de_test", "server_name": "Fixture"},
        tables=tables,
        available_events=tuple(sorted(tables)),
        player_info=player_info,
    )


def _two_round_demo() -> ParsedDemo:
    return _parsed(
        {
            "round_prestart": pl.DataFrame({"tick": [100, 200], "total_rounds_played": [0, 1]}),
            "round_freeze_end": pl.DataFrame({"tick": [120, 220], "total_rounds_played": [0, 1]}),
            "round_officially_ended": pl.DataFrame(
                {"tick": [200, 300], "total_rounds_played": [1, 2]}
            ),
            "player_death": pl.DataFrame(
                {
                    "tick": [150, 250],
                    "total_rounds_played": [0, 1],
                    "attacker_steamid": ["11", "11"],
                    "attacker_name": ["Alpha", "Alpha"],
                    "attacker_team_name": ["TERRORIST", "CT"],
                    "user_steamid": ["22", "22"],
                    "user_name": ["Bravo", "Bravo"],
                    "user_team_name": ["CT", "TERRORIST"],
                    "assister_steamid": [None, None],
                    "assister_name": [None, None],
                    "weapon": ["ak47", "m4a1"],
                    "headshot": [True, False],
                }
            ),
            "player_hurt": pl.DataFrame(
                {
                    "tick": [145, 245],
                    "attacker_steamid": ["11", "11"],
                    "attacker_name": ["Alpha", "Alpha"],
                    "attacker_team_name": ["T", "CT"],
                    "user_steamid": ["22", "22"],
                    "user_name": ["Bravo", "Bravo"],
                    "user_team_name": ["CT", "T"],
                    "dmg_health": [30, 40],
                    "dmg_armor": [5, 6],
                    "health": [70, 60],
                    "weapon": ["ak47", "m4a1"],
                }
            ),
            "weapon_fire": pl.DataFrame(
                {
                    "tick": [140, 240],
                    "user_steamid": ["11", "11"],
                    "user_name": ["Alpha", "Alpha"],
                    "user_team_name": ["T", "CT"],
                    "weapon": ["ak47", "m4a1"],
                    "silenced": [False, True],
                }
            ),
            "flashbang_detonate": pl.DataFrame(
                {
                    "tick": [160],
                    "user_steamid": ["11"],
                    "user_name": ["Alpha"],
                    "user_team_name": ["T"],
                    "entityid": [7],
                }
            ),
            "bomb_planted": pl.DataFrame(
                {
                    "tick": [170],
                    "user_steamid": ["11"],
                    "user_name": ["Alpha"],
                    "user_team_name": ["T"],
                    "site": [999],
                }
            ),
        },
        player_info=pl.DataFrame(
            {
                "steamid": ["11", "22"],
                "name": ["Alpha", "Bravo"],
                "team_name": ["CT", "T"],
            }
        ),
    )


def test_full_dataset_is_deterministic_and_parser_independent() -> None:
    parsed = _two_round_demo()
    normalizer = CanonicalMatchNormalizer()

    first = normalizer.normalize(parsed, source_demo_sha256=_SHA)
    second = normalizer.normalize(parsed, source_demo_sha256=_SHA)

    assert isinstance(normalizer, EventNormalizer)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert first.match.round_count == 2
    assert len(first.players) == 2
    assert len(first.teams) == 2
    assert first.validation_report.has_fatal_errors is False
    assert first.kills[0].assister_player_id is None
    assert first.grenades[0].x is None
    assert first.bomb_events[0].site_raw == 999
    assert first.bomb_events[0].site_normalized is None


def test_faceit_duplicate_ends_and_terminal_fallback() -> None:
    start_markers = list(range(30))
    official_markers = [marker for marker in range(1, 30) for _duplicate in range(2)]
    parsed = _parsed(
        {
            "round_prestart": pl.DataFrame(
                {
                    "tick": [100 + marker * 100 for marker in start_markers],
                    "total_rounds_played": start_markers,
                }
            ),
            "round_freeze_end": pl.DataFrame(
                {
                    "tick": [10, *[120 + marker * 100 for marker in start_markers]],
                    "total_rounds_played": [0, *start_markers],
                }
            ),
            "round_officially_ended": pl.DataFrame(
                {
                    "tick": [100 + marker * 100 for marker in official_markers],
                    "total_rounds_played": official_markers,
                }
            ),
            "cs_win_panel_match": pl.DataFrame({"tick": [3_100], "total_rounds_played": [30]}),
            "announce_phase_end": pl.DataFrame(
                {"tick": [1_300, 2_500, 2_800], "total_rounds_played": [12, 24, 27]}
            ),
        }
    )

    result = RoundResolver().resolve(parsed, _MATCH_ID)

    assert result.selected_round_count == 30
    assert result.round_count_candidates == {
        "max_total_rounds_played": 30,
        "canonical_round_end_count": 29,
        "canonical_round_start_count": 30,
    }
    assert len(result.rounds) == 30
    assert result.rounds[0].freeze_end_tick == 120
    assert result.rounds[-1].official_end_tick is None
    assert result.rounds[-1].end_tick == 3_100
    assert result.rounds[-1].end_source == "fallback:cs_win_panel_match"
    assert result.rounds[-1].is_complete is True
    assert result.rounds[24].is_overtime is True
    assert "final round has no observed official end" in " ".join(result.warnings).lower()


def test_valve_alias_precedence_and_warmup_filtering() -> None:
    parsed = _parsed(
        {
            "round_start": pl.DataFrame(
                {
                    "tick": [5, 100],
                    "total_rounds_played": [0, 0],
                    "is_warmup_period": [True, False],
                }
            ),
            "round_freeze_end": pl.DataFrame({"tick": [120], "total_rounds_played": [0]}),
            "round_end": pl.DataFrame({"tick": [180], "total_rounds_played": [1], "winner": [2]}),
            "round_officially_ended": pl.DataFrame({"tick": [190], "total_rounds_played": [1]}),
        }
    )

    result = RoundResolver().resolve(parsed, _MATCH_ID)

    assert len(result.rounds) == 1
    assert result.rounds[0].start_tick == 100
    assert result.rounds[0].start_source == "round_start"
    assert result.rounds[0].end_tick == 180
    assert result.rounds[0].end_source == "round_end"
    assert result.rounds[0].official_end_tick == 190
    assert result.rounds[0].winner_side is Side.T
    assert result.rounds[0].score_t_before is None
    assert result.rounds[0].score_t_after is None
    assert result.rounds[0].score_status is DataAvailability.MISSING_FROM_SOURCE


def test_explicit_round_number_is_not_shifted_like_total_rounds_played() -> None:
    parsed = _parsed(
        {
            "round_start": pl.DataFrame({"tick": [100], "round_number": [1]}),
            "round_end": pl.DataFrame({"tick": [180], "round_number": [1]}),
        }
    )

    result = RoundResolver().resolve(parsed, _MATCH_ID)

    assert len(result.rounds) == 1
    assert result.rounds[0].round_number == 1


def test_alias_disagreement_is_preserved_in_validation_report() -> None:
    parsed = _parsed(
        {
            "round_start": pl.DataFrame({"tick": [100, 200], "total_rounds_played": [0, 1]}),
            "round_freeze_end": pl.DataFrame({"tick": [120], "total_rounds_played": [0]}),
            "round_end": pl.DataFrame({"tick": [180, 280], "total_rounds_played": [1, 2]}),
        }
    )

    dataset = CanonicalMatchNormalizer().normalize(parsed, source_demo_sha256=_SHA)

    assert any(issue.code == "alias_disagreement" for issue in dataset.validation_report.issues)


def test_missing_final_end_without_terminal_is_preserved_as_incomplete() -> None:
    parsed = _parsed(
        {
            "round_start": pl.DataFrame({"tick": [100, 200], "total_rounds_played": [0, 1]}),
            "round_end": pl.DataFrame({"tick": [180], "total_rounds_played": [1]}),
            "player_death": pl.DataFrame({"tick": [250], "total_rounds_played": [2]}),
        }
    )

    result = RoundResolver().resolve(parsed, _MATCH_ID)

    assert len(result.rounds) == 2
    assert result.rounds[-1].end_tick is None
    assert result.rounds[-1].is_complete is False
    assert result.rounds[-1].exclusion_reason == "missing_final_round_end"


def test_round_assignment_boundary_and_between_rounds() -> None:
    rounds = (
        CanonicalRound(
            round_id=uuid4(),
            match_id=_MATCH_ID,
            round_number=1,
            start_tick=100,
            freeze_end_tick=120,
            end_tick=180,
            official_end_tick=180,
            is_complete=True,
        ),
        CanonicalRound(
            round_id=uuid4(),
            match_id=_MATCH_ID,
            round_number=2,
            start_tick=200,
            freeze_end_tick=220,
            end_tick=280,
            official_end_tick=280,
            is_complete=True,
        ),
    )
    service = RoundAssignmentService(rounds)

    assert service.assign(50).round_id is None
    assert service.assign(190).round_number == 1
    assert service.assign(190).phase is EventPhase.POST_ROUND
    assert service.assign(200).round_number == 2
    assert service.assign(200).phase is EventPhase.FREEZE_TIME


def test_player_reconnect_nickname_change_and_missing_steam_are_safe() -> None:
    parsed = _parsed(
        {
            "player_team": pl.DataFrame(
                {
                    "tick": [100, 200],
                    "user_steamid": ["11", "11"],
                    "user_name": ["OldName", "NewName"],
                    "team": [2, 3],
                }
            ),
            "player_disconnect": pl.DataFrame(
                {
                    "tick": [150],
                    "user_steamid": ["11"],
                    "user_name": ["OldName"],
                }
            ),
            "player_connect_full": pl.DataFrame(
                {
                    "tick": [200],
                    "user_steamid": ["11"],
                    "user_name": ["NewName"],
                }
            ),
            "player_spawn": pl.DataFrame(
                {
                    "tick": [150, 250],
                    "user_steamid": [None, None],
                    "user_name": ["SharedNick", "SharedNick"],
                }
            ),
        },
        player_info=pl.DataFrame({"steamid": ["11"], "name": ["OldName"]}),
    )
    from stratweb.application.identity_resolution import PlayerResolver

    result = PlayerResolver().resolve(parsed, _MATCH_ID)
    real = next(player for player in result.players if player.steam_id == "11")
    unknown = [player for player in result.players if player.steam_id is None]

    assert real.current_name == "NewName"
    assert real.known_names == ("NewName", "OldName")
    assert "reconnect_observed" in real.warnings
    assert len(unknown) == 2
    assert normalize_side(2) is Side.T
    assert normalize_side(3) is Side.CT


def test_team_side_switch_and_overtime_use_observed_transitions() -> None:
    player_a = uuid4()
    player_b = uuid4()
    substitute = uuid4()
    from stratweb.application.canonical_models import CanonicalPlayer

    players = PlayerResolutionResult(
        players=(
            CanonicalPlayer(
                player_id=player_a, steam_id="11", current_name="A", known_names=("A",)
            ),
            CanonicalPlayer(
                player_id=player_b, steam_id="22", current_name="B", known_names=("B",)
            ),
            CanonicalPlayer(
                player_id=substitute,
                steam_id="33",
                current_name="Sub",
                known_names=("Sub",),
            ),
        ),
        by_steam_id={"11": player_a, "22": player_b, "33": substitute},
        reference_player_ids={},
        side_observations=(
            SideObservation(player_a, 120, Side.T, "fixture"),
            SideObservation(player_b, 120, Side.CT, "fixture"),
            SideObservation(player_a, 220, Side.CT, "fixture"),
            SideObservation(player_b, 220, Side.T, "fixture"),
            SideObservation(substitute, 220, Side.CT, "fixture"),
            SideObservation(player_a, 320, Side.T, "fixture"),
            SideObservation(player_b, 320, Side.CT, "fixture"),
        ),
    )
    rounds = tuple(
        CanonicalRound(
            round_id=uuid4(),
            match_id=_MATCH_ID,
            round_number=number,
            start_tick=number * 100,
            freeze_end_tick=number * 100 + 10,
            end_tick=number * 100 + 80,
            is_complete=True,
        )
        for number in range(1, 4)
    )

    result = TeamResolver().resolve(_MATCH_ID, players, rounds)

    assert len(result.teams) == 2
    assert result.rounds[0].t_team_id == result.rounds[1].ct_team_id
    assert result.rounds[2].is_overtime is True
    assert result.side_for(player_a, 220) is Side.CT
    assert result.side_for(player_a, 320) is Side.T
    assert result.team_for(substitute) == result.team_for(player_a)
    assert any("Substitution" in warning for warning in result.warnings)


def test_suicide_teamkill_corrupt_row_and_duplicate_detection() -> None:
    parsed = _two_round_demo()
    death = parsed.tables["player_death"]
    extra = pl.DataFrame(
        {
            "tick": [160, 170],
            "total_rounds_played": [0, 0],
            "attacker_steamid": ["11", "11"],
            "attacker_name": ["Alpha", "Alpha"],
            "attacker_team_name": ["T", "T"],
            "user_steamid": ["11", "33"],
            "user_name": ["Alpha", "AlphaTwo"],
            "user_team_name": ["T", "T"],
            "assister_steamid": [None, None],
            "assister_name": [None, None],
            "weapon": ["world", "ak47"],
            "headshot": [False, False],
        }
    )
    tables = dict(parsed.tables)
    tables["player_death"] = pl.concat([death, extra], how="diagonal_relaxed")
    tables["player_hurt"] = pl.concat(
        [
            parsed.tables["player_hurt"],
            pl.DataFrame(
                {
                    "tick": [None],
                    "attacker_steamid": ["11"],
                    "user_steamid": ["22"],
                    "dmg_health": [10],
                }
            ),
        ],
        how="diagonal_relaxed",
    )
    assert parsed.player_info is not None
    player_info = pl.concat(
        [
            parsed.player_info,
            pl.DataFrame({"steamid": ["33"], "name": ["AlphaTwo"], "team_name": ["CT"]}),
        ],
        how="diagonal_relaxed",
    )
    dataset = CanonicalMatchNormalizer().normalize(
        _parsed(tables, player_info), source_demo_sha256=_SHA
    )

    assert any(kill.is_suicide for kill in dataset.kills)
    assert any(kill.is_teamkill for kill in dataset.kills)
    assert any(issue.code == "invalid_event_tick" for issue in dataset.validation_report.issues)

    duplicate = dataset.shots[0]
    report = CanonicalDatasetValidator().validate(
        ValidationInput(
            match=dataset.match,
            teams=dataset.teams,
            players=dataset.players,
            memberships=dataset.player_team_memberships,
            rounds=dataset.rounds,
            events=(duplicate, duplicate),
        )
    )
    duplicate_issue = next(issue for issue in report.issues if issue.code == "duplicate_event_id")
    assert duplicate_issue.is_fatal is True


def test_death_victim_is_preserved_or_explicitly_unavailable_from_source() -> None:
    parsed = _two_round_demo()
    source = parsed.tables["player_death"]
    rows = source.to_dicts()
    rows[0]["user_steamid"] = None
    rows[0]["user_name"] = None
    tables = dict(parsed.tables)
    tables["player_death"] = pl.DataFrame(rows)

    dataset = CanonicalMatchNormalizer().normalize(
        _parsed(tables, parsed.player_info), source_demo_sha256=_SHA
    )
    missing = next(kill for kill in dataset.kills if kill.tick == rows[0]["tick"])
    retained = next(kill for kill in dataset.kills if kill.tick == rows[1]["tick"])

    assert missing.victim_player_id is None
    assert "victim player could not be resolved" in missing.warnings
    assert retained.victim_player_id is not None
