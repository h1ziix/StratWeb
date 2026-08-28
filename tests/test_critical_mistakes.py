from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBOpponentRepository
from stratweb.application.opponent_models import OpponentProfile
from stratweb.critical_mistakes.engine import CriticalMistakeEngine
from stratweb.critical_mistakes.models import (
    CriticalCandidate,
    CriticalCapabilityStatus,
    CriticalEvidence,
    CriticalMistakesInput,
    CriticalMistakeType,
    CriticalSourcePin,
)
from stratweb.domain.enums import Side
from stratweb.main import create_app

PROFILE_ID = UUID("00000000-0000-0000-0000-000000000001")
MATCH_ID = UUID("00000000-0000-0000-0000-000000000002")
TEAM_ID = UUID("00000000-0000-0000-0000-000000000003")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000004")
RUN_ID = UUID("00000000-0000-0000-0000-000000000005")
HASH = "a" * 64


def _candidate(kind: CriticalMistakeType, round_number: int) -> CriticalCandidate:
    return CriticalCandidate(
        mistake_type=kind,
        map_name="de_inferno",
        side=Side.T,
        evidence=CriticalEvidence(
            match_id=MATCH_ID,
            round_number=round_number,
            tick=100 + round_number,
            event_ids=(EVENT_ID,),
            facts=("Подтверждённый факт.",),
        ),
        title="Ошибка",
        observation="Наблюдение.",
        tactical_interpretation="Интерпретация.",
        recommendation="Рекомендация.",
    )


def _input(candidates: tuple[CriticalCandidate, ...]) -> CriticalMistakesInput:
    return CriticalMistakesInput(
        profile_id=PROFILE_ID,
        source_pins=(
            CriticalSourcePin(
                match_id=MATCH_ID,
                team_id=TEAM_ID,
                map_name="de_inferno",
                dataset_fingerprint=HASH,
                analytics_fingerprint=HASH,
                analytics_rule_version="1.1.0",
                temporal_run_id=RUN_ID,
                temporal_fingerprint=HASH,
                temporal_rule_version="1.1.0",
                tickrate=64.0,
                tickrate_source="canonical:demo_header",
            ),
        ),
        eligible_counts={
            CriticalMistakeType.LOST_PLUS_TWO: 4,
            CriticalMistakeType.LOST_VS_FULL_ECO: 2,
            CriticalMistakeType.EARLY_UNTRADED_DEATH: 5,
        },
        candidates=candidates,
        capabilities={kind: CriticalCapabilityStatus.AVAILABLE for kind in CriticalMistakeType},
        limitations={kind: ("Ограничение.",) for kind in CriticalMistakeType},
    )


def test_engine_calculates_evidence_backed_metrics_deterministically() -> None:
    data = _input(
        (
            _candidate(CriticalMistakeType.LOST_PLUS_TWO, 2),
            _candidate(CriticalMistakeType.LOST_PLUS_TWO, 8),
            _candidate(CriticalMistakeType.EARLY_UNTRADED_DEATH, 4),
        )
    )

    first = CriticalMistakeEngine().compute(data)
    second = CriticalMistakeEngine().compute(data)

    assert first == second
    assert first.summary.total == 3
    assert first.summary.lost_plus_two == 2
    plus_two = next(item for item in first.mistakes if item.mistake_type == "lost_plus_two")
    assert (plus_two.numerator, plus_two.denominator, plus_two.frequency) == (2, 4, 0.5)
    assert plus_two.evidence.match_id == MATCH_ID
    assert plus_two.evidence.event_ids == (EVENT_ID,)


def test_empty_candidates_remain_honest_and_do_not_create_fake_findings() -> None:
    result = CriticalMistakeEngine().compute(_input(()))

    assert result.mistakes == ()
    assert result.summary.total == 0
    assert result.summary.lost_vs_full_eco == 0


def test_product_page_computes_and_persists_an_honest_empty_run(tmp_path: Path) -> None:
    database = tmp_path / "critical.duckdb"
    DuckDBMatchRepository(database).initialize()
    now = datetime.now(UTC)
    DuckDBOpponentRepository(database).create_profile(
        OpponentProfile(
            profile_id=PROFILE_ID,
            display_name="Соперник",
            created_at=now,
            updated_at=now,
        )
    )

    with TestClient(create_app(database)) as client:
        response = client.post(
            f"/api/opponents/{PROFILE_ID}/critical-mistakes/compute",
            headers={"accept": "text/html"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        page = client.get(f"/ui/opponents/{PROFILE_ID}/critical-mistakes")
        assert page.status_code == 200
        assert "Критические ошибки" in page.text
        assert "Подтверждённых ошибок не найдено" in page.text
        unavailable = client.get(
            f"/ui/opponents/{PROFILE_ID}/critical-mistakes",
            params={"mistake_type": "early_untraded_death"},
        )
        assert unavailable.status_code == 200
        assert "Эта проверка недоступна" in unavailable.text
        result = client.get(f"/api/opponents/{PROFILE_ID}/critical-mistakes")
        assert result.status_code == 200
        assert result.json()["summary"]["total"] == 0
