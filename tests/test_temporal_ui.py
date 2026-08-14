from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import duckdb
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBTemporalRepository
from stratweb.application.canonicalization import compute_dataset_fingerprint
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.domain.enums import Side
from stratweb.main import create_app


def _persist_ui_fixture(tmp_path: Path, canonical_dataset_factory: Any) -> tuple[Path, Any]:
    dataset = canonical_dataset_factory("temporal-ui")
    original = dataset.kills[0]
    cross_kill = original.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:cross"),
            "attacker_player_id": original.victim_player_id,
            "victim_player_id": original.attacker_player_id,
            "attacker_team_id": original.victim_team_id,
            "victim_team_id": original.attacker_team_id,
            "attacker_side": Side.CT,
            "victim_side": Side.T,
        }
    )
    victimless = original.model_copy(
        update={
            "event_id": uuid5(dataset.match.match_id, "kill:victimless"),
            "tick": 150,
            "relative_tick": 50,
            "attacker_player_id": None,
            "victim_player_id": None,
            "attacker_team_id": None,
            "victim_team_id": None,
            "attacker_side": Side.UNKNOWN,
            "victim_side": Side.UNKNOWN,
            "weapon": "world",
            "is_suicide": False,
        }
    )
    provisional = dataset.model_copy(
        update={
            "dataset_fingerprint": "0" * 64,
            "kills": (original, cross_kill, victimless),
        }
    )
    dataset = provisional.model_copy(
        update={"dataset_fingerprint": compute_dataset_fingerprint(provisional)}
    )
    database = tmp_path / "temporal-ui.duckdb"
    matches = DuckDBMatchRepository(database)
    matches.save_match(dataset)
    ComputeTemporalStateService(matches, DuckDBTemporalRepository(database)).compute(
        dataset.match.match_id
    )
    return database, dataset


def test_ui_exposes_group_snapshots_without_inventing_event_order(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset = _persist_ui_fixture(tmp_path, canonical_dataset_factory)
    repository = DuckDBTemporalRepository(database)
    summary = repository.get_summary(dataset.match.match_id)
    assert summary is not None
    timeline = repository.get_round_timeline(dataset.match.match_id, 1)
    assert timeline is not None
    group = timeline.simultaneous_groups[0]
    client = TestClient(create_app(database))

    overview = client.get(f"/ui/temporal/{dataset.match.match_id}")
    round_page = client.get(f"/ui/temporal/{dataset.match.match_id}/rounds/1")
    raw_round_page = client.get(
        f"/ui/temporal/{dataset.match.match_id}/rounds/1?show_raw_events=true"
    )
    group_page = client.get(
        f"/ui/temporal/{dataset.match.match_id}/rounds/1/groups/{group.group_id}"
    )
    event_page = client.get(
        f"/ui/temporal/{dataset.match.match_id}/rounds/1/events/{original_id}"
        if (original_id := dataset.kills[0].event_id)
        else ""
    )
    tick_page = client.get(f"/ui/temporal/{dataset.match.match_id}/rounds/1/snapshots/120")
    final_page = client.get(f"/ui/temporal/{dataset.match.match_id}/rounds/1/final")

    assert overview.status_code == 200
    assert all(
        label in overview.text
        for label in (
            "Состояние группы тика",
            "Состояние отдельных событий",
            "Промежуточный порядок",
            "Финальное число живых",
            "Схема 1.1.0",
        )
    )
    assert round_page.status_code == 200
    assert "Малозначимых событий свёрнуто" in round_page.text
    assert "Показать все исходные события" in round_page.text
    assert raw_round_page.status_code == 200
    assert "Скрыть все исходные события" in raw_round_page.text
    assert raw_round_page.text.count('class="event-row') >= round_page.text.count(
        'class="event-row'
    )
    assert "Одновременная группа" in round_page.text
    assert "порядок: порядок неоднозначен" in round_page.text
    assert "промежуточное: неоднозначно" in round_page.text
    assert "финальное: детерминировано" in round_page.text
    assert "Возможные промежуточные состояния" in round_page.text
    assert "Alpha" in round_page.text and "Bravo" in round_page.text
    assert "физический порядок не определяется по event ID" in round_page.text
    assert group_page.status_code == 200
    assert "До группы тика" in group_page.text
    assert "После группы тика" in group_page.text
    assert "Порядок событий внутри тика не доказан" in group_page.text
    assert "кандидат на первую смерть" in group_page.text
    assert event_page.status_code == 200
    assert "До события" in event_page.text and "После события" in event_page.text
    assert event_page.text.count("состояние: неоднозначно") >= 2
    assert tick_page.status_code == 200
    assert "Снимок на тике означает состояние после всей группы" in tick_page.text
    assert "0T" in tick_page.text and "0CT" in tick_page.text
    assert final_page.status_code == 200
    assert "Финальное состояние раунда" in final_page.text


def test_victimless_death_and_diagnostics_use_evidence_safe_wording(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset = _persist_ui_fixture(tmp_path, canonical_dataset_factory)
    victimless_id = uuid5(dataset.match.match_id, "kill:victimless")
    client = TestClient(create_app(database))

    event_page = client.get(
        f"/ui/temporal/{dataset.match.match_id}/rounds/1/events/{victimless_id}"
    )
    diagnostics = client.get(f"/ui/temporal/{dataset.match.match_id}/diagnostics")
    victimless_list = client.get(
        f"/ui/temporal/{dataset.match.match_id}/diagnostics/deaths_without_victim"
    )
    payload = client.get(f"/api/temporal/{dataset.match.match_id}/diagnostics").json()

    assert event_page.status_code == 200
    assert "Смерть от мира / жертва не установлена" in event_page.text
    assert "Жертва не установлена" in event_page.text
    assert "не изменяет число живых" in event_page.text
    assert "влияние смерти</dt><dd>unavailable" in event_page.text
    assert "unknown player died" not in event_page.text.lower()
    assert diagnostics.status_code == 200
    assert "Смерти без установленной жертвы" in diagnostics.text
    assert "death_effect_unavailable" in diagnostics.text
    assert victimless_list.status_code == 200
    assert "Раунд 1" in victimless_list.text
    assert str(victimless_id) in victimless_list.text
    assert payload["counters"] == {
        "simultaneous_groups": 1,
        "ambiguous_order_groups": 1,
        "ambiguous_intermediate_groups": 1,
        "ambiguous_final_groups": 0,
        "conflicting_groups": 0,
        "deaths_without_victim": 1,
    }


def test_latest_current_run_wins_over_newer_legacy_run_and_pages_pin_run_id(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset = _persist_ui_fixture(tmp_path, canonical_dataset_factory)
    repository = DuckDBTemporalRepository(database)
    current = repository.get_summary(dataset.match.match_id)
    assert current is not None
    legacy_run_id = uuid4()
    legacy_summary = current.summary.model_dump(mode="json")
    for field in (
        "ambiguous_order_groups",
        "ambiguous_intermediate_groups",
        "ambiguous_final_groups",
        "conflicting_groups",
        "death_events_without_victim",
    ):
        legacy_summary.pop(field)
    for field in (
        "tick_group_state",
        "per_event_state",
        "intermediate_ordering",
        "final_alive_state",
    ):
        legacy_summary["availability"].pop(field)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO temporal_runs (
                temporal_run_id, temporal_fingerprint, match_id, dataset_fingerprint,
                temporal_schema_version, temporal_rule_version, temporal_config_hash,
                config, summary, row_counts, warnings
            ) VALUES (?, ?, ?, ?, '1.0.0', '1.0.0', ?, ?, ?, '{}', '[]')
            """,
            [
                legacy_run_id,
                "f" * 64,
                dataset.match.match_id,
                dataset.dataset_fingerprint,
                current.temporal_config_hash,
                json.dumps(current.config.model_dump(mode="json")),
                json.dumps(legacy_summary),
            ],
        )
        connection.execute(
            """
            INSERT INTO round_timelines
            SELECT ? AS temporal_run_id, * EXCLUDE (temporal_run_id)
            FROM round_timelines WHERE temporal_run_id = ?
            """,
            [legacy_run_id, current.temporal_run_id],
        )
    client = TestClient(create_app(database))

    default_page = client.get(f"/ui/temporal/{dataset.match.match_id}")
    legacy_page = client.get(f"/ui/temporal/{dataset.match.match_id}?run_id={legacy_run_id}")
    unknown_page = client.get(f"/ui/temporal/{dataset.match.match_id}?run_id={UUID(int=0)}")
    legacy_round = client.get(
        f"/ui/temporal/{dataset.match.match_id}/rounds/1?run_id={legacy_run_id}"
    )
    legacy_event = client.get(
        f"/ui/temporal/{dataset.match.match_id}/rounds/1/events/{dataset.kills[0].event_id}"
        f"?run_id={legacy_run_id}"
    )
    legacy_tick = client.get(
        f"/ui/temporal/{dataset.match.match_id}/rounds/1/snapshots/120?run_id={legacy_run_id}"
    )
    legacy_final = client.get(
        f"/ui/temporal/{dataset.match.match_id}/rounds/1/final?run_id={legacy_run_id}"
    )

    assert default_page.status_code == 200
    assert "Схема 1.1.0 · правило 1.1.0" in default_page.text
    assert f"?run_id={current.temporal_run_id}" in default_page.text
    assert str(legacy_run_id) in default_page.text
    assert legacy_page.status_code == 200
    assert "Устаревший расчёт Temporal 1.0" in legacy_page.text
    assert "данные Temporal 1.1 на этой странице не смешиваются" in legacy_page.text
    assert "Состояние группы тика</span><strong>unavailable" in legacy_page.text
    assert legacy_round.status_code == 200
    assert "Одновременная группа" not in legacy_round.text
    assert legacy_event.status_code == 200
    assert legacy_event.text.count("состояние: недоступно") >= 2
    assert "Temporal 1.0 не подтверждает" in legacy_event.text
    assert legacy_tick.status_code == 200 and "состояние: недоступно" in legacy_tick.text
    assert legacy_final.status_code == 200 and "состояние: недоступно" in legacy_final.text
    assert unknown_page.status_code == 404
