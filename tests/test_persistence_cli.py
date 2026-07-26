from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stratweb import cli


def test_persistence_cli_init_import_query_and_delete(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    dataset = canonical_dataset_factory()
    artifact = tmp_path / "canonical.json"
    artifact.write_text(dataset.model_dump_json(), encoding="utf-8")
    database = tmp_path / "matches.duckdb"

    assert cli.main(["db", "init", "--db", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["applied_migrations"] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
            11,
            12,
            13,
            14,
            15,
            16,
        ]

    import_args = [
        "import",
        "--canonical-json",
        str(artifact),
        "--db",
        str(database),
    ]
    assert cli.main(import_args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "imported"
    assert cli.main(import_args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already_exists"

    match_id = str(dataset.match.match_id)
    assert cli.main(["matches", "show", match_id, "--db", str(database)]) == 0
    match_output = json.loads(capsys.readouterr().out)
    assert match_output["row_counts"]["kills"] == 1
    assert match_output["round_outcome"] == {
        "status": "available",
        "available_rounds": 1,
        "unavailable_rounds": 0,
        "coverage": 1.0,
        "can_compute_win_metrics": True,
        "unavailable_reason": None,
    }
    assert cli.main(["rounds", "list", match_id, "--db", str(database)]) == 0
    round_list = json.loads(capsys.readouterr().out)
    assert len(round_list) == 1
    assert round_list[0]["winner_side"] == "T"
    assert round_list[0]["outcome_status"] == "source_event"
    assert round_list[0]["outcome_source"] == "fixture:winner"
    assert round_list[0]["score_status"] == "available"
    assert round_list[0]["score_source"] == "fixture:score"
    assert round_list[0]["end_reason_status"] == "available"
    assert round_list[0]["end_reason_source"] == "fixture:reason"
    assert cli.main(["rounds", "show", match_id, "1", "--db", str(database)]) == 0
    round_output = json.loads(capsys.readouterr().out)
    assert len(round_output["events"]["grenades"]) == 1
    assert round_output["round"]["winner_side"] == "T"
    assert round_output["round"]["outcome_status"] == "source_event"

    monkeypatch.setattr("builtins.input", lambda: "n")
    assert cli.main(["matches", "delete", match_id, "--db", str(database)]) == 0
    cancelled = capsys.readouterr()
    assert json.loads(cancelled.out)["status"] == "cancelled"
    assert "[y/N]" in cancelled.err

    assert cli.main(["matches", "delete", match_id, "--yes", "--db", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] is True
