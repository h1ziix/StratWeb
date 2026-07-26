from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import polars as pl
import pytest

from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalMatch,
    CanonicalMatchDataset,
    CanonicalPlayer,
    CanonicalRound,
    CanonicalShot,
    CanonicalTeam,
    CapabilityCoverageStatus,
    DataAvailability,
    EventPhase,
    NormalizationMetadata,
    PlayerTeamMembership,
    ResultCapabilities,
    ResultCapability,
    RoundOutcomeStatus,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from stratweb.application.canonicalization import compute_dataset_fingerprint
from stratweb.application.inspection import DemoInspectionService
from stratweb.application.inspection_models import DemoInspectionReport
from stratweb.contracts import ParsedDemo, ParseRequest, ParserIdentity
from stratweb.domain.enums import Side


class FakeInspectionParser:
    def __init__(self) -> None:
        self._identity = ParserIdentity(name="demoparser2", version="0.41.4")

    @property
    def identity(self) -> ParserIdentity:
        return self._identity

    def parse(self, request: ParseRequest) -> ParsedDemo:
        return ParsedDemo(
            demo_file_id=request.demo_file_id,
            parser=self.identity,
            header={
                "map_name": "de_mirage",
                "server_name": "Fixture Server",
                "client_name": "SourceTV Demo",
                "demo_version_name": "valve_demo_2",
                "playback_ticks": 12_345,
                "playback_time": 192.89,
            },
            tables={
                "player_death": pl.DataFrame(
                    {
                        "tick": [100, 200],
                        "attacker_steamid": ["76561198000000001", "76561198000000002"],
                        "attacker_name": ["Alpha", "Bravo"],
                        "attacker_team_name": ["Team A", "Team B"],
                    }
                ),
                "round_end": pl.DataFrame({"tick": [1_000, 2_000], "total_rounds_played": [1, 2]}),
            },
            available_events=("player_death", "round_end"),
            player_info=pl.DataFrame(
                {
                    "name": ["Alpha", "Bravo"],
                    "steamid": ["76561198000000001", "76561198000000002"],
                    "team_name": ["Team A", "Team B"],
                }
            ),
        )


@pytest.fixture
def fake_demo_path(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.dem"
    path.write_bytes(b"PBDEMS2\x00fixture-data")
    return path


@pytest.fixture
def inspection_report(fake_demo_path: Path) -> DemoInspectionReport:
    return DemoInspectionService(FakeInspectionParser()).inspect(fake_demo_path)


@pytest.fixture
def canonical_dataset_factory():  # type: ignore[no-untyped-def]
    def build(seed: str = "primary") -> CanonicalMatchDataset:
        source_sha = hashlib.sha256(seed.encode()).hexdigest()
        match_id = uuid5(NAMESPACE_URL, f"test-match:{seed}")
        demo_id = uuid5(NAMESPACE_URL, f"test-demo:{seed}")
        player_a = uuid5(match_id, "player:a")
        player_b = uuid5(match_id, "player:b")
        team_a = uuid5(match_id, "team:a")
        team_b = uuid5(match_id, "team:b")
        round_id = uuid5(match_id, "round:1")
        players = (
            CanonicalPlayer(
                player_id=player_a,
                steam_id="76561198000000001",
                current_name="Alpha",
                known_names=("Alpha",),
            ),
            CanonicalPlayer(
                player_id=player_b,
                steam_id="76561198000000002",
                current_name="Bravo",
                known_names=("Bravo",),
            ),
        )
        teams = (
            CanonicalTeam(
                team_id=team_a,
                match_id=match_id,
                internal_name="TeamAlpha",
                starting_player_ids=(player_a,),
                identity_confidence=1,
            ),
            CanonicalTeam(
                team_id=team_b,
                match_id=match_id,
                internal_name="TeamBravo",
                starting_player_ids=(player_b,),
                identity_confidence=1,
            ),
        )
        memberships = (
            PlayerTeamMembership(
                player_id=player_a,
                team_id=team_a,
                side=Side.T,
                valid_from_tick=100,
                source="fixture",
                confidence=1,
            ),
            PlayerTeamMembership(
                player_id=player_b,
                team_id=team_b,
                side=Side.CT,
                valid_from_tick=100,
                source="fixture",
                confidence=1,
            ),
        )
        rounds = (
            CanonicalRound(
                round_id=round_id,
                match_id=match_id,
                round_number=1,
                start_tick=100,
                freeze_end_tick=110,
                end_tick=190,
                official_end_tick=200,
                start_source="round_start",
                end_source="round_end",
                t_team_id=team_a,
                ct_team_id=team_b,
                winner_side=Side.T,
                outcome_status=RoundOutcomeStatus.SOURCE_EVENT,
                outcome_source="fixture:winner",
                end_reason="9",
                end_reason_status=DataAvailability.AVAILABLE,
                end_reason_source="fixture:reason",
                score_t_before=0,
                score_ct_before=0,
                score_t_after=1,
                score_ct_after=0,
                score_status=DataAvailability.AVAILABLE,
                score_source="fixture:score",
                is_complete=True,
            ),
        )
        common = {
            "match_id": match_id,
            "round_id": round_id,
            "round_number": 1,
            "phase": EventPhase.LIVE,
        }
        kills = (
            CanonicalKill(
                event_id=uuid5(match_id, "kill:1"),
                tick=120,
                relative_tick=20,
                source_event="player_death",
                attacker_player_id=player_a,
                victim_player_id=player_b,
                attacker_team_id=team_a,
                victim_team_id=team_b,
                attacker_side=Side.T,
                victim_side=Side.CT,
                weapon="ak47",
                headshot=True,
                **common,
            ),
        )
        damages = (
            CanonicalDamage(
                event_id=uuid5(match_id, "damage:1"),
                tick=115,
                relative_tick=15,
                source_event="player_hurt",
                attacker_player_id=player_a,
                victim_player_id=player_b,
                attacker_team_id=team_a,
                victim_team_id=team_b,
                attacker_side=Side.T,
                victim_side=Side.CT,
                weapon="ak47",
                damage_health=100,
                victim_health_after=0,
                **common,
            ),
        )
        shots = (
            CanonicalShot(
                event_id=uuid5(match_id, "shot:1"),
                tick=112,
                relative_tick=12,
                source_event="weapon_fire",
                player_id=player_a,
                team_id=team_a,
                side=Side.T,
                weapon="ak47",
                **common,
            ),
        )
        grenades = (
            CanonicalGrenade(
                event_id=uuid5(match_id, "grenade:1"),
                tick=130,
                relative_tick=30,
                source_event="flashbang_detonate",
                player_id=player_a,
                team_id=team_a,
                side=Side.T,
                grenade_type="flashbang",
                lifecycle_event="detonate",
                entity_id=7,
                x=1.5,
                y=2.5,
                z=3.5,
                **common,
            ),
        )
        bomb_events = (
            CanonicalBombEvent(
                event_id=uuid5(match_id, "bomb:1"),
                tick=140,
                relative_tick=40,
                source_event="bomb_planted",
                player_id=player_a,
                team_id=team_a,
                side=Side.T,
                event_type="planted",
                site_raw=999,
                **common,
            ),
        )
        issue = ValidationIssue(
            code="fixture_warning",
            severity=ValidationSeverity.WARNING,
            entity_type="dataset",
            message="Synthetic fixture warning.",
            rule_version="1.0.0",
        )
        provisional = CanonicalMatchDataset(
            dataset_fingerprint="0" * 64,
            match=CanonicalMatch(
                match_id=match_id,
                demo_file_id=demo_id,
                map_name="de_mirage",
                server_name="Synthetic Fixture",
                round_count=1,
                complete_round_count=1,
                incomplete_round_count=0,
                round_count_candidates={"max_total_rounds_played": 1},
                selected_round_count=1,
                selected_round_count_source="max_total_rounds_played",
            ),
            teams=teams,
            players=players,
            player_team_memberships=memberships,
            rounds=rounds,
            kills=kills,
            damages=damages,
            shots=shots,
            grenades=grenades,
            bomb_events=bomb_events,
            validation_report=ValidationReport(
                is_valid=True,
                has_fatal_errors=False,
                fatal_error_count=0,
                issue_counts={
                    ValidationSeverity.INFO: 0,
                    ValidationSeverity.WARNING: 1,
                    ValidationSeverity.ERROR: 0,
                },
                unassigned_event_count=0,
                unknown_player_count=0,
                incomplete_round_count=0,
                issues=(issue,),
            ),
            normalization_metadata=NormalizationMetadata(
                parser_name="demoparser2",
                parser_version="0.41.4",
                normalization_config_hash=hashlib.sha256(b"fixture-config").hexdigest(),
                source_demo_sha256=source_sha,
                source_event_counts={"player_death": 1},
                selected_event_aliases={"CanonicalKill": "player_death"},
                result_capabilities=ResultCapabilities(
                    round_winner=ResultCapability(
                        status=CapabilityCoverageStatus.AVAILABLE,
                        source_events_checked=("round_end",),
                        detected_fields=("winner",),
                        authoritative_source_found=True,
                        total_round_count=1,
                        rounds_available=1,
                        rounds_missing=0,
                        rounds_unresolved=0,
                    ),
                    round_score=ResultCapability(
                        status=CapabilityCoverageStatus.AVAILABLE,
                        source_events_checked=("round_end",),
                        detected_fields=("t_score", "ct_score"),
                        authoritative_source_found=True,
                        total_round_count=1,
                        rounds_available=1,
                        rounds_missing=0,
                        rounds_unresolved=0,
                    ),
                    round_end_reason=ResultCapability(
                        status=CapabilityCoverageStatus.AVAILABLE,
                        source_events_checked=("round_end",),
                        detected_fields=("reason",),
                        authoritative_source_found=True,
                        total_round_count=1,
                        rounds_available=1,
                        rounds_missing=0,
                        rounds_unresolved=0,
                    ),
                ),
                warnings=("synthetic normalization warning",),
            ),
        )
        return provisional.model_copy(
            update={"dataset_fingerprint": compute_dataset_fingerprint(provisional)}
        )

    return build
