from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from stratweb.adapters.parsers.demoparser2_economy import (
    ECONOMY_PROPERTIES,
    Demoparser2EconomyExtractor,
)
from stratweb.adapters.persistence import DuckDBEconomyRepository, DuckDBMatchRepository
from stratweb.economy.engine import EconomyEngine
from stratweb.economy.models import (
    BuyType,
    EconomyComputeStatus,
    EconomyConfig,
    EconomyExtraction,
    EconomySourceSample,
    EvidenceAvailability,
)
from stratweb.main import create_app


class FakeEconomyBackend:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[tuple[str, ...], tuple[int, ...]]] = []

    def parse_ticks(
        self,
        wanted_props: tuple[str, ...],
        *,
        players: object = None,
        ticks: tuple[int, ...] | None = None,
        prop_states: object = None,
    ) -> pd.DataFrame:
        del players, prop_states
        self.calls.append((tuple(wanted_props), tuple(ticks or ())))
        return self.frame


def test_demoparser2_economy_extractor_uses_documented_freeze_fields(
    fake_demo_path: Path,
) -> None:
    backend = FakeEconomyBackend(
        pd.DataFrame(
            [
                {
                    "tick": 110,
                    "steamid": 76561198000000001,
                    "name": "Alpha",
                    "current_equip_value": 4200,
                    "round_start_equip_value": 800,
                    "cash_spent_this_round": 3400,
                    "balance": 200,
                    "inventory": ["weapon_ak47", "weapon_smokegrenade"],
                    "inventory_as_ids": [7, 45],
                    "armor_value": 100,
                    "has_helmet": True,
                    "has_defuser": False,
                    "team_num": 2,
                    "total_rounds_played": 1,
                }
            ]
        )
    )
    result = Demoparser2EconomyExtractor(
        parser_factory=lambda _: backend,
        installed_version="0.41.4",
    ).extract(
        fake_demo_path,
        (110,),
        expected_sha256=hashlib.sha256(fake_demo_path.read_bytes()).hexdigest(),
    )

    assert backend.calls == [(ECONOMY_PROPERTIES, (110,))]
    assert result.parser_version == "0.41.4"
    assert result.samples[0].current_equip_value == 4200
    assert result.samples[0].inventory == ("weapon_ak47", "weapon_smokegrenade")
    assert result.samples[0].has_helmet is True


def test_economy_engine_classifies_pistol_and_preserves_provenance(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    state, repository, _ = _state(tmp_path, canonical_dataset_factory)

    assert state.capability.classified_team_rounds == 2
    assert {item.buy_type for item in state.team_snapshots} == {BuyType.PISTOL}
    t_snapshot = next(item for item in state.team_snapshots if item.side.value == "T")
    assert t_snapshot.equipment_value.value == 800
    assert t_snapshot.equipment_value.source == "aggregate:freeze_end_players"
    assert t_snapshot.weapons.value == ("weapon_glock",)
    assert t_snapshot.utility.value == ("weapon_flashbang",)
    assert t_snapshot.team_source == "canonical_round.side_team_id"
    player = next(item for item in state.player_snapshots if item.side.value == "T")
    assert player.source_team_number.value == 2
    assert t_snapshot.classification_source is not None
    assert repository.get_match(state.match_id) is not None


def test_missing_equipment_never_becomes_eco(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    state, _, match = _state(tmp_path, canonical_dataset_factory, missing_equipment=True)

    assert all(item.buy_type is BuyType.UNKNOWN for item in state.team_snapshots)
    assert all(
        item.equipment_value.availability is EvidenceAvailability.MISSING_FROM_SOURCE
        for item in state.team_snapshots
    )
    assert state.capability.classified_team_rounds == 0
    assert match.match_id == state.match_id


def test_economy_persistence_filters_buy_type_and_is_idempotent(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    state, match_repository, _ = _state(tmp_path, canonical_dataset_factory)
    repository = DuckDBEconomyRepository(match_repository.database_path)

    saved = repository.save_economy(state)
    again = repository.save_economy(state)
    summary = repository.get_summary(state.match_id)
    teams = repository.list_team_snapshots(state.match_id, buy_type=BuyType.PISTOL)
    players = repository.list_player_snapshots(state.match_id, round_number=1)

    assert saved.status is EconomyComputeStatus.COMPUTED
    assert again.status is EconomyComputeStatus.ALREADY_EXISTS
    assert summary is not None
    assert summary.capability.classified_team_rounds == 2
    assert len(teams) == 2
    assert len(players) == 2
    assert teams[0].equipment_value.value == 800

    assert match_repository.delete_match(state.match_id) is True
    assert repository.get_summary(state.match_id) is None


def test_economy_api_exposes_summary_and_buy_filter(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    state, match_repository, _ = _state(tmp_path, canonical_dataset_factory)
    DuckDBEconomyRepository(match_repository.database_path).save_economy(state)
    client = TestClient(create_app(database_path=match_repository.database_path))

    summary = client.get(f"/api/economy/{state.match_id}/summary")
    teams = client.get(
        f"/api/economy/{state.match_id}/teams",
        params={"buy_type": "pistol", "side": "T"},
    )

    assert summary.status_code == 200
    assert summary.json()["economy_rule_version"] == "freeze_end_team_buy_v1"
    assert teams.status_code == 200
    assert teams.json()["count"] == 1
    assert teams.json()["team_snapshots"][0]["buy_type"] == "pistol"


def test_economy_ui_renders_rounds_filters_and_player_evidence(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    state, match_repository, _ = _state(tmp_path, canonical_dataset_factory)
    DuckDBEconomyRepository(match_repository.database_path).save_economy(state)
    client = TestClient(create_app(database_path=match_repository.database_path))

    response = client.get(f"/ui/matches/{state.match_id}/economy")
    filtered = client.get(
        f"/ui/matches/{state.match_id}/economy",
        params={"side": "T", "buy_type": "pistol", "round": 1},
    )

    assert response.status_code == 200
    assert "Экономика раундов" in response.text
    assert "100.0%" in response.text
    assert "Alpha" in response.text
    assert "Glock" in response.text
    assert "$800" in response.text
    assert "Как читать типы закупок" in response.text
    assert 'class="round-jump"' in response.text
    assert 'id="economy-round-1"' in response.text
    assert "Воспроизводимость и исходные данные" in response.text
    assert filtered.status_code == 200
    assert "Скрыто выбранным фильтром" in filtered.text
    assert "Alpha" in filtered.text


def test_economy_ui_explains_missing_run(tmp_path: Path, canonical_dataset_factory: Any) -> None:
    state, match_repository, _ = _state(tmp_path, canonical_dataset_factory)
    client = TestClient(create_app(database_path=match_repository.database_path))

    response = client.get(f"/ui/matches/{state.match_id}/economy")

    assert response.status_code == 200
    assert "Данные экономики недоступны" in response.text


def _state(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    *,
    missing_equipment: bool = False,
):  # type: ignore[no-untyped-def]
    dataset = canonical_dataset_factory("economy")
    database = tmp_path / "economy.duckdb"
    repository = DuckDBMatchRepository(database)
    repository.save_match(dataset)
    match = repository.get_match(dataset.match.match_id)
    assert match is not None
    fields = tuple(
        item
        for item in ECONOMY_PROPERTIES
        if not (missing_equipment and item == "current_equip_value")
    )
    extraction = EconomyExtraction(
        parser_name="demoparser2",
        parser_version="0.41.4",
        source_demo_sha256=match.source_demo_sha256,
        requested_ticks=(110,),
        requested_fields=ECONOMY_PROPERTIES,
        source_columns=("tick", "steamid", "name", *fields),
        samples=(
            EconomySourceSample(
                tick=110,
                steam_id="76561198000000001",
                player_name="Alpha",
                current_equip_value=None if missing_equipment else 800,
                round_start_equip_value=800,
                cash_spent_this_round=0,
                balance=800,
                inventory=("weapon_glock", "weapon_flashbang", "weapon_c4", "item_kevlar"),
                inventory_item_ids=(4, 43),
                armor_value=0,
                has_helmet=False,
                has_defuser=False,
                team_num=2,
                total_rounds_played=0,
            ),
            EconomySourceSample(
                tick=110,
                steam_id="76561198000000002",
                player_name="Bravo",
                current_equip_value=None if missing_equipment else 800,
                round_start_equip_value=800,
                cash_spent_this_round=0,
                balance=800,
                inventory=("weapon_hkp2000",),
                inventory_item_ids=(32,),
                armor_value=0,
                has_helmet=False,
                has_defuser=False,
                team_num=3,
                total_rounds_played=0,
            ),
        ),
    )
    state = EconomyEngine().compute(
        match,
        repository.get_rounds(match.match_id),
        repository.get_players(match.match_id),
        repository.get_memberships(match.match_id),
        extraction,
        EconomyConfig(
            expected_team_size=1,
            full_min_equipment_value=4000,
            eco_max_equipment_value=1000,
            eco_max_cash_spent=500,
            force_min_cash_spent=2000,
        ),
    )
    return state, repository, match
