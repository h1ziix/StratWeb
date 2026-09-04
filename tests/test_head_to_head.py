from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import duckdb
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import (
    DuckDBHeadToHeadRepository,
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
)
from stratweb.application.canonical_models import Sha256
from stratweb.application.normalization_utils import canonical_json
from stratweb.application.opponent_models import OpponentProfile
from stratweb.domain.enums import Side
from stratweb.head_to_head.engine import HeadToHeadEngine
from stratweb.head_to_head.models import (
    HEAD_TO_HEAD_RULE_VERSION,
    HEAD_TO_HEAD_SCHEMA_VERSION,
    HeadToHeadInput,
    HeadToHeadReliability,
    HeadToHeadRiskLevel,
    HeadToHeadRule,
    HeadToHeadSaveStatus,
)
from stratweb.main import create_app
from stratweb.tactical_v2.models import (
    TACTICAL_V2_RULE_VERSION,
    TACTICAL_V2_SCHEMA_VERSION,
    TacticalAvailability,
    TacticalEvidenceReference,
    TacticalInsight,
    TacticalInsightType,
    TacticalV2Config,
    TacticalV2RunSummary,
    TacticalV2Summary,
)


def _id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"head-to-head-test:{value}")


def _fingerprint(value: str) -> Sha256:
    return (value * 64)[:64]


def _evidence(scope: str) -> tuple[TacticalEvidenceReference, ...]:
    return tuple(
        TacticalEvidenceReference(
            match_id=_id(f"{scope}-match-{index}"),
            round_number=index,
            tick_start=100 * index,
            tick_end=100 * index + 8,
            event_ids=(_id(f"{scope}-event-{index}"),),
        )
        for index in range(1, 4)
    )


def _insight(
    profile_id: UUID,
    run_id: UUID,
    insight_type: TacticalInsightType,
    key: str,
    side: Side,
    numerator: int,
    denominator: int,
) -> TacticalInsight:
    evidence = _evidence(f"{profile_id}-{insight_type.value}-{key}-{side.value}")
    return TacticalInsight(
        insight_id=_id(f"{profile_id}-{insight_type.value}-{key}-{side.value}"),
        tactical_run_id=run_id,
        profile_id=profile_id,
        insight_type=insight_type,
        map_name="de_inferno",
        side=side,
        key=key,
        label=key,
        availability=TacticalAvailability.AVAILABLE,
        numerator=numerator,
        denominator=denominator,
        frequency=numerator / denominator,
        sample_size=denominator,
        match_count=3,
        small_sample_warning=True,
        evidence_references=evidence,
        limitations=("test_source_limitation",),
    )


def _summary(profile_id: UUID, run_id: UUID, fingerprint: Sha256) -> TacticalV2RunSummary:
    return TacticalV2RunSummary(
        tactical_schema_version=TACTICAL_V2_SCHEMA_VERSION,
        tactical_rule_version=TACTICAL_V2_RULE_VERSION,
        tactical_run_id=run_id,
        tactical_fingerprint=fingerprint,
        configuration_hash=_fingerprint("c"),
        profile_id=profile_id,
        config=TacticalV2Config(),
        source_pins=(),
        capabilities={},
        summary=TacticalV2Summary(
            selected_matches=3,
            included_matches=3,
            excluded_matches=0,
            eligible_rounds=30,
            insights=3,
            evidence_references=9,
            insight_type_counts={},
            small_sample_insights=3,
        ),
        row_counts={},
    )


def _input() -> HeadToHeadInput:
    opponent_profile = _id("opponent")
    our_profile = _id("ours")
    opponent_run = _id("opponent-run")
    our_run = _id("our-run")
    return HeadToHeadInput(
        opponent_profile_id=opponent_profile,
        our_profile_id=our_profile,
        opponent_summary=_summary(opponent_profile, opponent_run, _fingerprint("a")),
        our_summary=_summary(our_profile, our_run, _fingerprint("b")),
        opponent_insights=(
            _insight(
                opponent_profile,
                opponent_run,
                TacticalInsightType.ENTRY_STRUCTURE,
                "opening_duel_success",
                Side.CT,
                7,
                10,
            ),
        ),
        our_insights=(
            _insight(
                our_profile,
                our_run,
                TacticalInsightType.TRADE_STRUCTURE,
                "opening_death_traded",
                Side.T,
                2,
                10,
            ),
            _insight(
                our_profile,
                our_run,
                TacticalInsightType.SPACING_PROFILE,
                "checkpoint:640",
                Side.T,
                6,
                10,
            ),
        ),
    )


def test_head_to_head_is_deterministic_and_pairs_opposite_sides() -> None:
    data = _input()
    first = HeadToHeadEngine().compute(data)
    second = HeadToHeadEngine().compute(data)

    assert first == second
    assert first.head_to_head_schema_version == HEAD_TO_HEAD_SCHEMA_VERSION
    assert first.head_to_head_rule_version == HEAD_TO_HEAD_RULE_VERSION
    assert first.summary.comparison_count == 2
    trade = next(item for item in first.comparisons if item.rule is HeadToHeadRule.OPENING_VS_TRADE)
    assert trade.opponent_side is Side.CT
    assert trade.our_side is Side.T
    assert abs(trade.risk_score - 0.56) < 1e-12
    assert trade.risk_level is HeadToHeadRiskLevel.HIGH
    assert trade.reliability is HeadToHeadReliability.TACTICAL_TREND
    assert "7 из 10" in trade.observation
    assert "2 из 10" in trade.observation
    assert trade.opponent_insight.evidence_references
    assert trade.our_insight.evidence_references
    spacing = next(
        item for item in first.comparisons if item.rule is HeadToHeadRule.OPENING_VS_SPACING
    )
    assert abs(spacing.risk_score - 0.42) < 1e-12
    assert spacing.risk_level is HeadToHeadRiskLevel.MEDIUM
    assert "head_to_head_is_historical_alignment_not_proven_causality" in first.warnings

    unknown_opponent = data.opponent_insights[0].model_copy(update={"side": Side.UNKNOWN})
    unknown_data = data.model_copy(update={"opponent_insights": (unknown_opponent,)})
    assert HeadToHeadEngine().compute(unknown_data).comparisons == ()


def test_head_to_head_persistence_and_product_page(tmp_path: Path) -> None:
    database = tmp_path / "head-to-head.duckdb"
    DuckDBMatchRepository(database).initialize()
    data = _input()
    state = HeadToHeadEngine().compute(data)
    profiles = DuckDBOpponentRepository(database)
    now = datetime.now(UTC)
    profiles.create_profile(
        OpponentProfile(
            profile_id=data.opponent_profile_id,
            display_name="Соперник",
            created_at=now,
            updated_at=now,
        )
    )
    profiles.create_profile(
        OpponentProfile(
            profile_id=data.our_profile_id,
            display_name="Наша команда",
            created_at=now,
            updated_at=now,
        )
    )
    with duckdb.connect(str(database)) as connection:
        _insert_tactical(connection, data.opponent_summary, data.opponent_insights)
        _insert_tactical(connection, data.our_summary, data.our_insights)

    repository = DuckDBHeadToHeadRepository(database)
    saved = repository.save(state)
    assert saved.status is HeadToHeadSaveStatus.COMPUTED
    assert repository.save(state).status is HeadToHeadSaveStatus.ALREADY_EXISTS
    loaded = repository.get_for_sources(
        data.opponent_profile_id,
        data.our_profile_id,
        data.opponent_summary.tactical_run_id,
        data.our_summary.tactical_run_id,
    )
    assert loaded == state
    assert repository.list_runs(data.opponent_profile_id, data.our_profile_id)[0].compatible

    with TestClient(create_app(database)) as client:
        page = client.get(
            f"/ui/opponents/{data.opponent_profile_id}/head-to-head",
            params={"our_profile_id": str(data.our_profile_id)},
        )
        assert page.status_code == 200
        assert "Мы против них" in page.text
        assert "Первые контакты соперника против наших разменов" in page.text
        assert "Что сыграть" in page.text
        assert "Раунды соперника" in page.text
        response = client.get(
            f"/api/opponents/{data.opponent_profile_id}/head-to-head/summary",
            params={"our_profile_id": str(data.our_profile_id)},
        )
        assert response.status_code == 200
        assert response.json()["summary"]["comparison_count"] == 2
        recompute = client.post(
            f"/api/opponents/{data.opponent_profile_id}/head-to-head/compute",
            data={"our_profile_id": str(data.our_profile_id)},
            headers={"accept": "text/html"},
            follow_redirects=False,
        )
        assert recompute.status_code == 303
        missing = client.get(
            f"/api/opponents/{data.opponent_profile_id}/head-to-head/summary",
            params={
                "our_profile_id": str(data.our_profile_id),
                "run_id": str(_id("missing-run")),
            },
        )
        assert missing.status_code == 404


def _insert_tactical(
    connection: duckdb.DuckDBPyConnection,
    summary: TacticalV2RunSummary,
    insights: tuple[TacticalInsight, ...],
) -> None:
    connection.execute(
        """
        INSERT INTO tactical_v2_runs (
            tactical_run_id, tactical_fingerprint, tactical_schema_version,
            tactical_rule_version, configuration_hash, profile_id, config,
            capabilities, summary, row_counts, warnings
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            summary.tactical_run_id,
            summary.tactical_fingerprint,
            summary.tactical_schema_version,
            summary.tactical_rule_version,
            summary.configuration_hash,
            summary.profile_id,
            canonical_json(summary.config.model_dump(mode="json")),
            canonical_json({}),
            canonical_json(summary.summary.model_dump(mode="json")),
            canonical_json({}),
            canonical_json([]),
        ],
    )
    for insight in insights:
        connection.execute(
            """
            INSERT INTO tactical_v2_insights (
                tactical_run_id, insight_id, profile_id, insight_type, map_name, side,
                insight_key, availability, numerator, denominator, frequency,
                match_count, small_sample_warning, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                insight.tactical_run_id,
                insight.insight_id,
                insight.profile_id,
                insight.insight_type.value,
                insight.map_name,
                insight.side.value,
                insight.key,
                insight.availability.value,
                insight.numerator,
                insight.denominator,
                insight.frequency,
                insight.match_count,
                insight.small_sample_warning,
                canonical_json(insight.model_dump(mode="json")),
            ],
        )
