from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi.testclient import TestClient

from stratweb import cli
from stratweb.adapters.persistence import (
    DuckDBAnalysisRepository,
    DuckDBAnalyticsRepository,
    DuckDBCounterStrategyRepository,
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
    DuckDBPatternRepository,
    DuckDBRoundFeatureRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.application.analytics import ComputeMatchAnalyticsService
from stratweb.application.counter_strategy import (
    ComputeCounterStrategiesService,
    CounterStrategyQueryService,
    ValidateCounterStrategiesService,
)
from stratweb.application.findings import (
    AnalysisFindingQueryService,
    ComputeAnalysisFindingsService,
)
from stratweb.application.opponents import OpponentWorkspaceService
from stratweb.application.patterns import ComputeCrossMatchPatternsService
from stratweb.application.readiness import FindingReadinessService
from stratweb.application.round_features import ComputeRoundFeaturesService
from stratweb.application.scouting_reports import ScoutingReportSource
from stratweb.application.spatial import ComputeSpatialStateService
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.application.zone_assignments import ComputeZoneAssignmentsService
from stratweb.counter_strategy.engine import CounterStrategyEngine
from stratweb.counter_strategy.models import (
    CounterStrategyConfig,
    CounterStrategyInput,
    CounterStrategyRunSummary,
)
from stratweb.counter_strategy.validation import CounterStrategyValidationEngine
from stratweb.counter_strategy.validation_models import (
    CounterStrategyValidationInput,
    StrategyAcceptanceStatus,
    StrategyValidationConfig,
    ValidationCheckCode,
)
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.features.models import (
    BombsitePayload,
    FeatureAvailability,
    OpeningDuelPayload,
    RoundFeature,
    RoundFeatureType,
)
from stratweb.findings.models import FindingTextAvailability
from stratweb.main import create_app
from stratweb.patterns.engine import CrossMatchPatternEngine, wilson_confidence
from stratweb.patterns.models import (
    CrossMatchPatternInput,
    PatternAvailability,
    PatternConfig,
    PatternInputStatus,
    PatternMatchInput,
    PatternPlayerIdentity,
    PatternRoundInput,
    PatternType,
)
from stratweb.readiness.engine import FindingReadinessEngine
from stratweb.readiness.models import (
    FindingReadinessConfig,
    FindingReadinessInput,
    ReadinessReason,
)
from stratweb.spatial.models import SpatialExtraction, SpatialSourceSample
from stratweb.web.rendering import render_template
from stratweb.web.view_models.scouting_report import (
    ScoutingReportFilters,
    build_coach_report_page,
    build_scouting_report_page,
)


def _id(seed: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"pattern-test:{seed}")


def _feature(
    match_id: UUID,
    team_id: UUID,
    round_number: int,
    feature_type: RoundFeatureType,
    payload: BombsitePayload | OpeningDuelPayload,
    *,
    side: Side = Side.T,
) -> RoundFeature:
    round_id = uuid5(match_id, f"round:{round_number}")
    event_id = payload.plant_event_id if isinstance(payload, BombsitePayload) else payload.event_id
    return RoundFeature(
        feature_id=uuid5(match_id, f"feature:{round_number}:{feature_type.value}"),
        feature_run_id=uuid5(match_id, "feature-run"),
        feature_rule_version="per_round_facts_v1",
        match_id=match_id,
        round_id=round_id,
        round_number=round_number,
        team_id=team_id,
        side=side,
        feature_type=feature_type,
        availability=FeatureAvailability.AVAILABLE,
        tick_start=100 + round_number,
        tick_end=100 + round_number,
        buy_type=BuyType.FULL,
        payload=payload,
        evidence_event_ids=(event_id,),
    )


def _match_input(seed: str, sites: tuple[str, ...]) -> PatternMatchInput:
    profile_id = _id("profile")
    match_id = _id(f"match:{seed}")
    team_id = uuid5(match_id, "team")
    player_id = uuid5(match_id, "player:alpha")
    opponent_wins = (True, False) if seed == "one" else (True, True)
    rounds: list[PatternRoundInput] = []
    for index, site in enumerate(sites, start=1):
        plant_event = uuid5(match_id, f"plant:{index}")
        opening_event = uuid5(match_id, f"opening:{index}")
        opening_role = "loser" if seed == "two" and index == 2 else "winner"
        site_feature = _feature(
            match_id,
            team_id,
            index,
            RoundFeatureType.BOMBSITE,
            BombsitePayload(
                site=site,  # type: ignore[arg-type]
                plant_event_id=plant_event,
                planter_player_id=player_id,
                resolution_source="fixture",
            ),
        ).model_copy(
            update={
                "zone_id": f"bombsite_{site.lower()}",
                "zone_name": f"Bombsite {site}",
            }
        )
        features = (
            site_feature,
            _feature(
                match_id,
                team_id,
                index,
                RoundFeatureType.OPENING_DUEL,
                OpeningDuelPayload(
                    role=opening_role,  # type: ignore[arg-type]
                    killer_player_id=player_id,
                    victim_player_id=uuid5(match_id, f"victim:{index}"),
                    event_id=opening_event,
                    ordering_status="proven",
                ),
            ),
        )
        rounds.append(
            PatternRoundInput(
                match_id=match_id,
                round_id=uuid5(match_id, f"round:{index}"),
                round_number=index,
                team_id=team_id,
                side=Side.T,
                buy_type=BuyType.FULL,
                is_complete=True,
                opponent_won=opponent_wins[index - 1],
                features=features,
            )
        )
    return PatternMatchInput(
        profile_id=profile_id,
        match_id=match_id,
        team_id=team_id,
        map_name="de_mirage",
        status=PatternInputStatus.INCLUDED,
        dataset_fingerprint="1" * 64 if seed == "one" else "2" * 64,
        feature_run_id=uuid5(match_id, "feature-run"),
        feature_fingerprint="3" * 64 if seed == "one" else "4" * 64,
        feature_schema_version="1.0.0",
        feature_rule_version="per_round_facts_v1",
        players=(
            PatternPlayerIdentity(
                player_id=player_id,
                identity_key="steam:76561198000000001",
                current_name="Alpha",
                steam_id="76561198000000001",
                cross_match_resolved=True,
            ),
        ),
        rounds=tuple(rounds),
    )


def test_cross_match_patterns_are_deterministic_scoped_and_evidenced() -> None:
    first = _match_input("one", ("A", "A"))
    second = _match_input("two", ("A", "B"))
    second = second.model_copy(
        update={
            "players": (second.players[0].model_copy(update={"current_name": "Alpha renamed"}),)
        }
    )
    config = PatternConfig(minimum_corpus_matches=20, minimum_sample_size=5)
    engine = CrossMatchPatternEngine()

    state = engine.compute(
        CrossMatchPatternInput(profile_id=_id("profile"), inputs=(first, second)),
        config,
    )
    repeated = engine.compute(
        CrossMatchPatternInput(profile_id=_id("profile"), inputs=(second, first)),
        config,
    )

    assert repeated.pattern_fingerprint == state.pattern_fingerprint
    assert repeated.pattern_run_id == state.pattern_run_id
    assert state.summary.selected_matches == 2
    assert state.summary.included_matches == 2
    assert state.summary.eligible_rounds == 4
    assert state.summary.corpus_below_minimum is True
    assert "opponent_corpus_below_minimum:2/20" in state.warnings

    site_a = next(
        item
        for item in state.patterns
        if item.pattern_type is PatternType.SITE_PREFERENCE
        and item.value.kind == "categorical"
        and item.value.key == "site:A"
    )
    assert site_a.numerator == 3
    assert site_a.denominator == 4
    assert site_a.frequency == 0.75
    assert site_a.sample_size == 4
    assert site_a.small_sample_warning is True
    assert len(site_a.evidence_references) == 3
    assert len(site_a.included_rounds) == 4
    assert {item.match_id for item in site_a.evidence_references} == {
        first.match_id,
        second.match_id,
    }
    assert all(item.event_ids for item in site_a.evidence_references)
    assert (
        len([item for item in state.patterns if item.pattern_type is PatternType.SITE_PREFERENCE])
        == 2
    )

    alpha = next(
        item
        for item in state.patterns
        if item.pattern_type is PatternType.RECURRING_OPENING_PLAYER
        and item.value.kind == "player"
        and item.value.identity_key == "steam:76561198000000001"
    )
    assert alpha.numerator == 3
    assert alpha.denominator == 3
    assert alpha.numerator_match_count == 2
    assert alpha.value.cross_match_resolved is True
    assert (
        len(
            [
                item
                for item in state.patterns
                if item.pattern_type is PatternType.RECURRING_OPENING_PLAYER
                and item.value.kind == "player"
                and item.value.identity_key == "steam:76561198000000001"
            ]
        )
        == 1
    )

    conversion = next(
        item for item in state.patterns if item.pattern_type is PatternType.OPENING_KILL_CONVERSION
    )
    assert conversion.numerator == 2
    assert conversion.denominator == 3
    assert "association_is_not_a_causal_claim" in conversion.limitations

    assert state.capabilities[PatternType.EARLY_ROTATION].availability is (
        PatternAvailability.UNAVAILABLE
    )
    assert (
        "stage_8_4_first_ct_rotation_is_not_proven"
        in state.capabilities[PatternType.EARLY_ROTATION].limitations
    )
    assert state.capabilities[PatternType.RETAKE_FREQUENCY].availability is (
        PatternAvailability.UNAVAILABLE
    )
    assert state.capabilities[PatternType.SAVE_FREQUENCY].availability is (
        PatternAvailability.UNAVAILABLE
    )


def test_wilson_confidence_is_bounded_and_deterministic() -> None:
    interval = wilson_confidence(7, 10)
    assert interval.method == "wilson_score_95_v1"
    assert 0 < interval.lower_bound < 0.7 < interval.upper_bound < 1
    assert interval.score == interval.lower_bound
    assert wilson_confidence(7, 10) == interval


class _PatternSpatialExtractor:
    def __init__(self, players: tuple[Any, ...]) -> None:
        self._players = players

    def extract(
        self, demo_path: Path, ticks: tuple[int, ...], *, expected_sha256: str
    ) -> SpatialExtraction:
        del demo_path
        samples = tuple(
            SpatialSourceSample(
                tick=tick,
                steam_id=player.steam_id,
                player_name=player.current_name,
                x=1184.0 if index == 0 else -1716.8,
                y=-171.4 if index == 0 else -1889.6,
                z=0.0,
                inventory_item_ids=(49,) if index == 0 else (),
            )
            for tick in ticks
            for index, player in enumerate(self._players)
        )
        return SpatialExtraction(
            parser_name="fixture",
            parser_version="1.0.0",
            source_demo_sha256=expected_sha256,
            requested_ticks=ticks,
            source_columns=("tick", "steamid", "X", "Y", "Z"),
            samples=samples,
        )


def _persist_feature_match(database: Path, dataset: Any, tmp_path: Path) -> None:
    matches = DuckDBMatchRepository(database)
    analytics = DuckDBAnalyticsRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    zones = DuckDBZoneAssignmentRepository(database)
    features = DuckDBRoundFeatureRepository(database)
    matches.save_match(dataset)
    ComputeMatchAnalyticsService(matches, analytics).compute(dataset.match.match_id)
    ComputeTemporalStateService(matches, temporal, analytics_repository=analytics).compute(
        dataset.match.match_id
    )
    ComputeSpatialStateService(
        matches,
        temporal,
        spatial,
        _PatternSpatialExtractor(dataset.players),
    ).compute(dataset.match.match_id, tmp_path / "ignored.dem")
    ComputeZoneAssignmentsService(spatial, zones).compute(dataset.match.match_id)
    ComputeRoundFeaturesService(
        matches,
        analytics,
        temporal,
        spatial,
        zones,
        features,
    ).compute(dataset.match.match_id)


def test_pattern_service_persistence_and_feature_cascade(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    capsys: Any,
) -> None:
    database = tmp_path / "patterns.duckdb"
    first = canonical_dataset_factory("patterns-persistence-one")
    second = canonical_dataset_factory("patterns-persistence-two")
    third = canonical_dataset_factory("patterns-persistence-three")
    _persist_feature_match(database, first, tmp_path)
    _persist_feature_match(database, second, tmp_path)
    DuckDBMatchRepository(database).save_match(third)

    opponent_service = OpponentWorkspaceService(
        DuckDBOpponentRepository(database),
        DuckDBMatchRepository(database),
    )
    profile = opponent_service.create_profile("Pattern Opponent")
    for dataset in (first, second, third):
        opponent_service.assign_match(
            profile.profile_id,
            dataset.match.match_id,
            dataset.teams[0].team_id,
        )

    repository = DuckDBPatternRepository(database)
    service = ComputeCrossMatchPatternsService(
        DuckDBOpponentRepository(database),
        DuckDBMatchRepository(database),
        DuckDBRoundFeatureRepository(database),
        repository,
    )
    computed = service.compute(profile.profile_id)
    repeated = service.compute(profile.profile_id)

    assert computed.status.value == "computed"
    assert repeated.status.value == "already_exists"
    assert repeated.pattern_fingerprint == computed.pattern_fingerprint
    summary = repository.get_summary(profile.profile_id)
    assert summary is not None
    assert summary.summary.included_matches == 2
    assert summary.summary.selected_matches == 3
    assert summary.summary.excluded_matches == 1
    records = repository.list_patterns(profile.profile_id, limit=5000)
    assert records
    assert all(item.profile_id == profile.profile_id for item in records)
    assert repository.list_runs(profile.profile_id)[0].selected_by_default is True

    _persist_feature_match(database, third, tmp_path)
    assert repository.get_summary(profile.profile_id) is None
    stale_runs = repository.list_runs(profile.profile_id)
    assert len(stale_runs) == 1
    assert stale_runs[0].compatible is False
    assert stale_runs[0].selected_by_default is False

    refreshed = service.compute(profile.profile_id)
    assert refreshed.status.value == "computed"
    assert refreshed.summary.selected_matches == 3
    assert refreshed.summary.included_matches == 3
    assert refreshed.summary.excluded_matches == 0

    analysis_repository = DuckDBAnalysisRepository(database)
    analysis_compute = ComputeAnalysisFindingsService(
        repository,
        DuckDBMatchRepository(database),
        analysis_repository,
    )
    analysis_result = analysis_compute.compute(profile.profile_id)
    analysis_repeated = analysis_compute.compute(profile.profile_id)
    assert analysis_result.status.value == "computed"
    assert analysis_repeated.status.value == "already_exists"
    assert analysis_result.analysis_fingerprint == analysis_repeated.analysis_fingerprint
    assert analysis_result.summary.findings > 0
    assert analysis_result.summary.evidence_references > 0
    analysis_query = AnalysisFindingQueryService(repository, analysis_repository)
    analysis_summary = analysis_query.get_summary(profile.profile_id)
    assert analysis_summary.source_pattern_run_id == refreshed.pattern_run_id
    findings = analysis_query.list_findings(profile.profile_id, limit=5000)
    assert findings
    finding = findings[0]
    assert finding.observation.availability is FindingTextAvailability.AVAILABLE
    assert finding.tactical_implication.availability is (FindingTextAvailability.UNAVAILABLE)
    assert finding.recommended_response.availability is (FindingTextAvailability.UNAVAILABLE)
    assert finding.avoid.availability is FindingTextAvailability.UNAVAILABLE
    assert len(finding.evidence_references) == finding.denominator
    assert (
        sum(item.contributed_to_numerator for item in finding.evidence_references)
        == finding.numerator
    )
    assert all(item.map_href and item.timeline_href for item in finding.evidence_references)

    readiness = FindingReadinessService(analysis_query).audit(profile.profile_id)
    readiness_repeated = FindingReadinessService(analysis_query).audit(profile.profile_id)
    assert readiness.audit_fingerprint == readiness_repeated.audit_fingerprint
    assert readiness.summary.included_matches == 3
    assert readiness.summary.required_corpus_matches == 20
    assert readiness.summary.ready_findings == 0
    assert readiness.summary.blocked_findings == len(findings)
    assert readiness.summary.stage_8_7_ready is False
    assert readiness.summary.reason_counts[ReadinessReason.CORPUS_BELOW_MINIMUM] == len(findings)
    permissive = FindingReadinessService(analysis_query).audit(
        profile.profile_id,
        config=FindingReadinessConfig(
            minimum_corpus_matches=1,
            minimum_finding_matches=1,
            block_partial_source=False,
            require_known_buy_type=False,
        ),
    )
    assert permissive.audit_fingerprint != readiness.audit_fingerprint
    assert ReadinessReason.CORPUS_BELOW_MINIMUM not in permissive.summary.reason_counts
    assert permissive.summary.reason_counts[ReadinessReason.FINDING_SAMPLE_BELOW_MINIMUM] == len(
        findings
    )

    supported = next(
        item
        for item in findings
        if item.pattern_type
        in {
            PatternType.SITE_PREFERENCE,
            PatternType.EARLY_ZONE_OCCUPATION,
            PatternType.RECURRING_OPENING_PLAYER,
            PatternType.RECURRING_OPENING_DEATH,
            PatternType.FIRST_CONTACT_ZONE,
            PatternType.CT_STARTING_POSITION,
            PatternType.OPENING_KILL_CONVERSION,
            PatternType.RECOVERY_AFTER_OPENING_DEATH,
            PatternType.LOST_MAN_ADVANTAGE,
            PatternType.UNTRADED_DEATH,
        }
        and all(ref.tick is not None for ref in item.evidence_references)
    )
    ready_finding = supported.model_validate(
        {
            **supported.model_dump(mode="python"),
            "source_availability": "available",
            "scope": {**supported.scope.model_dump(mode="python"), "buy_type": "full"},
            "minimum_sample_size": supported.denominator,
            "small_sample_warning": False,
        }
    )
    ready_audit = FindingReadinessEngine().audit(
        FindingReadinessInput(analysis=analysis_summary, findings=(ready_finding,)),
        FindingReadinessConfig(
            minimum_corpus_matches=1,
            minimum_finding_matches=1,
        ),
    )
    strategy_state = CounterStrategyEngine().compute(
        CounterStrategyInput(
            analysis_fingerprint=analysis_summary.analysis_fingerprint,
            analysis_schema_version=analysis_summary.analysis_schema_version,
            analysis_rule_version=analysis_summary.analysis_rule_version,
            profile_id=profile.profile_id,
            readiness=ready_audit,
            findings=(ready_finding,),
        ),
        CounterStrategyConfig(
            frequent_site_threshold=0,
            frequent_control_threshold=0,
            recurring_opening_player_threshold=0,
            recurring_opening_death_threshold=0,
            low_opening_conversion_threshold=1,
            opening_death_recovery_threshold=0,
            lost_advantage_threshold=0,
            untraded_death_threshold=0,
        ),
    )
    assert len(strategy_state.recommendations) == 1
    strategy = strategy_state.recommendations[0]
    assert strategy.observation == ready_finding.observation
    assert strategy.denominator == len(strategy.evidence_references)
    assert "causality" in " ".join(strategy.limitations)

    strategy_repository = DuckDBCounterStrategyRepository(database)
    strategy_compute = ComputeCounterStrategiesService(analysis_query, strategy_repository)
    strategy_result = strategy_compute.compute(profile.profile_id)
    strategy_repeated = strategy_compute.compute(profile.profile_id)
    assert strategy_result.status.value == "computed"
    assert strategy_repeated.status.value == "already_exists"
    assert strategy_result.summary.recommendations == 0
    assert strategy_result.summary.skipped_not_ready == len(findings)
    strategy_query = CounterStrategyQueryService(analysis_query, strategy_repository)
    assert strategy_query.list_recommendations(profile.profile_id) == ()
    assert len(strategy_query.list_skipped(profile.profile_id)) == len(findings)
    validation_service = ValidateCounterStrategiesService(analysis_query, strategy_query)
    validation = validation_service.validate(profile.profile_id)
    validation_repeated = validation_service.validate(profile.profile_id)
    assert validation.status is StrategyAcceptanceStatus.BLOCKED
    assert validation.validation_fingerprint == validation_repeated.validation_fingerprint
    assert validation.failures == ()
    assert ValidationCheckCode.CORPUS_SIZE in validation.blockers
    assert ValidationCheckCode.PUBLISHED_RECOMMENDATIONS in validation.blockers

    additional_inputs = tuple(
        analysis_summary.input_matches[0].model_validate(
            {
                **analysis_summary.input_matches[0].model_dump(mode="python"),
                "match_id": _id(f"acceptance-match-{index}"),
                "team_id": _id(f"acceptance-team-{index}"),
                "demo_file_id": _id(f"acceptance-demo-{index}"),
                "source_demo_sha256": f"{index + 100:064x}",
                "feature_run_id": _id(f"acceptance-feature-run-{index}"),
            }
        )
        for index in range(17)
    )
    analysis_twenty = analysis_summary.model_validate(
        {
            **analysis_summary.model_dump(mode="python"),
            "input_matches": analysis_summary.input_matches + additional_inputs,
            "summary": {
                **analysis_summary.summary.model_dump(mode="python"),
                "selected_matches": 20,
                "included_matches": 20,
                "excluded_matches": 0,
            },
        }
    )
    readiness_twenty = FindingReadinessEngine().audit(
        FindingReadinessInput(analysis=analysis_twenty, findings=(ready_finding,)),
        FindingReadinessConfig(
            minimum_corpus_matches=20,
            minimum_finding_matches=1,
        ),
    )
    strategy_twenty = CounterStrategyEngine().compute(
        CounterStrategyInput(
            analysis_fingerprint=analysis_twenty.analysis_fingerprint,
            analysis_schema_version=analysis_twenty.analysis_schema_version,
            analysis_rule_version=analysis_twenty.analysis_rule_version,
            profile_id=profile.profile_id,
            readiness=readiness_twenty,
            findings=(ready_finding,),
        ),
        CounterStrategyConfig(
            frequent_site_threshold=0,
            frequent_control_threshold=0,
            recurring_opening_player_threshold=0,
            recurring_opening_death_threshold=0,
            low_opening_conversion_threshold=1,
            opening_death_recovery_threshold=0,
            lost_advantage_threshold=0,
            untraded_death_threshold=0,
        ),
    )
    strategy_twenty_payload = strategy_twenty.model_dump(mode="python")
    strategy_twenty_payload.pop("recommendations")
    strategy_twenty_payload.pop("skipped_findings")
    strategy_twenty_payload["row_counts"] = {
        "counter_strategy_runs": 1,
        "counter_strategy_recommendations": len(strategy_twenty.recommendations),
        "counter_strategy_skipped_findings": len(strategy_twenty.skipped_findings),
    }
    strategy_twenty_summary = CounterStrategyRunSummary.model_validate(strategy_twenty_payload)
    accepted = CounterStrategyValidationEngine().validate(
        CounterStrategyValidationInput(
            strategy=strategy_twenty_summary,
            analysis=analysis_twenty,
            readiness=readiness_twenty,
            findings=(ready_finding,),
            recommendations=strategy_twenty.recommendations,
            skipped_findings=strategy_twenty.skipped_findings,
        ),
        StrategyValidationConfig(require_both_sides=False),
    )
    assert accepted.status is StrategyAcceptanceStatus.PASSED
    assert accepted.coverage.included_matches == 20
    assert accepted.coverage.recommendations == 1
    assert accepted.blockers == ()
    assert accepted.failures == ()
    accepted_source = ScoutingReportSource(
        strategy=strategy_twenty_summary,
        analysis=analysis_twenty,
        readiness=readiness_twenty,
        validation=accepted,
        findings=(ready_finding,),
        recommendations=strategy_twenty.recommendations,
        skipped_findings=strategy_twenty.skipped_findings,
    )
    accepted_report = build_scouting_report_page(
        accepted_source,
        opponent_service.get_workspace(profile.profile_id),
        ScoutingReportFilters(),
    )
    coach_report = build_coach_report_page(
        accepted_source, opponent_service.get_workspace(profile.profile_id)
    )
    assert accepted_report.acceptance_status == "passed"
    assert len(accepted_report.recommendations) == 1
    assert coach_report.rule_version == "coach_report_projection_v2"
    assert len(coach_report.recommendations) == 1
    assert (
        len(
            (
                *coach_report.attack,
                *coach_report.defence,
                *coach_report.risks,
                *coach_report.individual,
            )
        )
        == 1
    )
    assert coach_report.evidence[0].finding.finding_id == ready_finding.finding_id
    assert coach_report.evidence[0].plain_title
    assert coach_report.evidence[0].plain_explanation
    assert "Наблюдение подтверждено" in accepted_report.recommendations[0].observation
    accepted_html = render_template(
        "opponents/report.html",
        workspace=opponent_service.get_workspace(profile.profile_id),
        report=accepted_report,
        unavailable_reason=None,
        match_context=None,
    )
    assert "Тактическая интерпретация" in accepted_html
    assert "Рекомендуемый ответ" in accepted_html
    assert "Чего избегать" in accepted_html
    escaped_html = render_template(
        "opponents/report.html",
        workspace=opponent_service.get_workspace(profile.profile_id),
        report=accepted_report.model_copy(
            update={"display_name": "<script>alert('report')</script>"}
        ),
        unavailable_reason=None,
        match_context=None,
    )
    assert "<script>alert('report')</script>" not in escaped_html
    assert "&lt;script&gt;alert" in escaped_html
    source_recommendation = strategy_twenty.recommendations[0]
    corrupted_reference = source_recommendation.evidence_references[0].model_copy(
        update={"match_id": _id("outside-accepted-corpus")}
    )
    corrupted_recommendation = source_recommendation.model_copy(
        update={
            "numerator_match_count": source_recommendation.numerator_match_count + 1,
            "evidence_references": (
                corrupted_reference,
                *source_recommendation.evidence_references[1:],
            ),
        }
    )
    rejected = CounterStrategyValidationEngine().validate(
        CounterStrategyValidationInput(
            strategy=strategy_twenty_summary,
            analysis=analysis_twenty,
            readiness=readiness_twenty,
            findings=(ready_finding,),
            recommendations=(corrupted_recommendation,),
            skipped_findings=strategy_twenty.skipped_findings,
        ),
        StrategyValidationConfig(require_both_sides=False),
    )
    assert rejected.status is StrategyAcceptanceStatus.FAILED
    assert ValidationCheckCode.STATISTICS_PRESERVED in rejected.failures
    assert ValidationCheckCode.EVIDENCE_PRESERVED in rejected.failures
    assert ValidationCheckCode.EVIDENCE_WITHIN_CORPUS in rejected.failures
    rejected_report = build_scouting_report_page(
        ScoutingReportSource(
            strategy=strategy_twenty_summary,
            analysis=analysis_twenty,
            readiness=readiness_twenty,
            validation=rejected,
            findings=(ready_finding,),
            recommendations=(corrupted_recommendation,),
            skipped_findings=strategy_twenty.skipped_findings,
        ),
        opponent_service.get_workspace(profile.profile_id),
        ScoutingReportFilters(),
    )
    assert rejected_report.recommendations_suppressed is True
    assert rejected_report.recommendations == ()
    rejected_html = render_template(
        "opponents/report.html",
        workspace=opponent_service.get_workspace(profile.profile_id),
        report=rejected_report,
        unavailable_reason=None,
        match_context=None,
    )
    assert "Рекомендации скрыты" in rejected_html
    assert corrupted_recommendation.recommendation.text not in rejected_html

    profile_id = str(profile.profile_id)
    assert cli.main(["patterns", "status", profile_id, "--db", str(database)]) == 0
    cli_summary = json.loads(capsys.readouterr().out)
    assert cli_summary["pattern_rule_version"] == "cross_match_patterns_v1"
    assert cli_summary["summary"]["included_matches"] == 3
    assert cli.main(["findings", "status", profile_id, "--db", str(database)]) == 0
    cli_analysis = json.loads(capsys.readouterr().out)
    assert cli_analysis["analysis_rule_version"] == "analysis_findings_v1"
    assert cli_analysis["summary"]["findings"] == len(findings)
    assert cli.main(["readiness", "audit", profile_id, "--db", str(database)]) == 0
    cli_readiness = json.loads(capsys.readouterr().out)
    assert cli_readiness["readiness_rule_version"] == "finding_readiness_v1"
    assert cli_readiness["summary"]["stage_8_7_ready"] is False
    assert cli.main(["strategies", "status", profile_id, "--db", str(database)]) == 0
    cli_strategy = json.loads(capsys.readouterr().out)
    assert cli_strategy["strategy_rule_version"] == "counter_strategy_rules_v1"
    assert cli_strategy["summary"]["recommendations"] == 0
    assert cli.main(["strategies", "validate", profile_id, "--db", str(database)]) == 0
    cli_validation = json.loads(capsys.readouterr().out)
    assert cli_validation["status"] == "blocked"
    assert cli_validation["validation_fingerprint"] == validation.validation_fingerprint
    assert (
        cli.main(
            [
                "findings",
                "evidence",
                profile_id,
                str(finding.finding_id),
                "--db",
                str(database),
            ]
        )
        == 0
    )
    cli_finding = json.loads(capsys.readouterr().out)
    assert cli_finding["finding_id"] == str(finding.finding_id)
    assert (
        cli.main(
            [
                "patterns",
                "show",
                profile_id,
                "--type",
                "opening_kill_conversion",
                "--db",
                str(database),
            ]
        )
        == 0
    )
    cli_patterns = json.loads(capsys.readouterr().out)
    assert cli_patterns
    assert all(item["pattern_type"] == "opening_kill_conversion" for item in cli_patterns)

    with TestClient(create_app(database_path=database)) as client:
        api_summary = client.get(f"/api/opponents/{profile_id}/patterns/summary")
        assert api_summary.status_code == 200
        assert api_summary.json()["pattern_rule_version"] == "cross_match_patterns_v1"
        api_patterns = client.get(
            f"/api/opponents/{profile_id}/patterns",
            params={"type": "opening_kill_conversion"},
        )
        assert api_patterns.status_code == 200
        assert api_patterns.json()["count"] == len(cli_patterns)
        api_runs = client.get(f"/api/opponents/{profile_id}/patterns/runs")
        assert api_runs.status_code == 200
        assert api_runs.json()["count"] == 2
        api_compute = client.post(f"/api/opponents/{profile_id}/patterns/compute")
        assert api_compute.status_code == 200
        assert api_compute.json()["status"] == "already_exists"
        api_analysis = client.get(f"/api/opponents/{profile_id}/analysis/summary")
        assert api_analysis.status_code == 200
        assert api_analysis.json()["analysis_rule_version"] == "analysis_findings_v1"
        api_readiness = client.get(f"/api/opponents/{profile_id}/analysis/readiness")
        assert api_readiness.status_code == 200
        assert api_readiness.json()["audit_fingerprint"] == readiness.audit_fingerprint
        assert api_readiness.json()["summary"]["stage_8_7_ready"] is False
        api_strategy = client.get(f"/api/opponents/{profile_id}/analysis/strategies/summary")
        assert api_strategy.status_code == 200
        assert api_strategy.json()["strategy_rule_version"] == "counter_strategy_rules_v1"
        api_validation = client.get(f"/api/opponents/{profile_id}/analysis/strategies/validation")
        assert api_validation.status_code == 200
        assert api_validation.json()["status"] == "blocked"
        assert api_validation.json()["validation_fingerprint"] == validation.validation_fingerprint
        report_page = client.get(f"/ui/opponents/{profile_id}/report")
        assert report_page.status_code == 200
        assert "Показать план на матч" in report_page.text
        assert "Сначала — насколько этому доверять" in report_page.text
        assert "Что они повторяют за атаку" in report_page.text
        assert "Что они повторяют за защиту" in report_page.text
        assert "Пока рано давать готовую тактику" in report_page.text
        assert "data-coach-step" in report_page.text
        assert "data-coach-next" in report_page.text
        assert "data-coach-deck" in report_page.text and "hidden" in report_page.text
        assert "Минимальная оценка Уилсона" not in report_page.text
        analyst_page = client.get(f"/ui/opponents/{profile_id}/report", params={"mode": "analyst"})
        assert analyst_page.status_code == 200
        assert "Доказательный отчёт о сопернике" in analyst_page.text
        assert 'name="mode" value="analyst"' in analyst_page.text
        assert "Простой режим" in analyst_page.text
        assert "Фильтры только показывают или скрывают готовые наблюдения" in analyst_page.text
        assert "Показать все проверки" in analyst_page.text
        assert "Скачать отчёт JSON" in analyst_page.text
        report_json = client.get(f"/api/opponents/{profile_id}/report")
        assert report_json.status_code == 200
        report_payload = report_json.json()
        assert report_payload["acceptance_status"] == "blocked"
        assert report_payload["report_schema_version"] == "1.0.0"
        assert report_payload["report_view_rule_version"] == "scouting_report_view_v1"
        assert report_payload["strategy_run_id"] == str(strategy_result.strategy_run_id)
        assert report_payload["source_findings"] == len(findings)
        assert report_payload["filtered_findings"] == len(findings)
        assert report_payload["recommendations_count"] == 0
        assert report_payload["evidence_references"] == sum(
            len(item.evidence_references) for item in findings
        )
        assert f"run_id={strategy_result.strategy_run_id}" in report_payload["report_json_href"]
        assert report_payload["corpus_matches"][0]["input_status"] == "included"
        export_url = f"/api/opponents/{profile_id}/report/export.json"
        export_json = client.get(
            export_url,
            params={"run_id": str(strategy_result.strategy_run_id)},
        )
        assert export_json.status_code == 200
        assert export_json.headers["content-disposition"].endswith('.json"')
        assert export_json.headers["x-stratweb-export-schema"] == "1.0.0"
        exported = export_json.json()
        assert exported["export_rule_version"] == "evidence_report_export_v1"
        assert exported["strategy_run_id"] == str(strategy_result.strategy_run_id)
        assert exported["scope"]["source_findings"] == len(findings)
        assert len(exported["findings"]) == len(findings)
        assert exported["findings"][0]["denominator"] == len(
            exported["findings"][0]["evidence_references"]
        )
        assert all(item["demo_sha256"] for item in exported["corpus"])
        assert all(item["original_file_name"] for item in exported["corpus"])
        assert export_json.headers["etag"] == f'"{exported["export_fingerprint"]}"'
        repeated_export = client.get(
            export_url,
            params={
                "run_id": str(strategy_result.strategy_run_id),
                "minimum_sample_size": 10000,
            },
        )
        assert repeated_export.content == export_json.content
        printable = client.get(
            f"/ui/opponents/{profile_id}/report/print",
            params={"run_id": str(strategy_result.strategy_run_id)},
        )
        assert printable.status_code == 200
        assert "Приложение доказательств" in printable.text
        assert "status.blocked" not in printable.text
        assert "Наблюдение «" in printable.text
        assert exported["export_fingerprint"] in printable.text
        pdf_export = client.get(
            f"/api/opponents/{profile_id}/report/export.pdf",
            params={"run_id": str(strategy_result.strategy_run_id)},
        )
        assert pdf_export.status_code == 200
        assert pdf_export.content.startswith(b"%PDF-")
        assert len(pdf_export.content) > 5000
        assert pdf_export.headers["content-disposition"].endswith('.pdf"')
        assert pdf_export.headers["etag"] == export_json.headers["etag"]
        repeated_pdf = client.get(
            f"/api/opponents/{profile_id}/report/export.pdf",
            params={"run_id": str(strategy_result.strategy_run_id)},
        )
        assert repeated_pdf.content == pdf_export.content
        t_report = client.get(
            f"/api/opponents/{profile_id}/report",
            params={"side": "T", "page_size": 100},
        )
        assert t_report.status_code == 200
        t_cards = [
            card for group in t_report.json()["finding_groups"] for card in group["findings"]
        ]
        assert t_cards
        assert all(card["side"] == "T" for card in t_cards)
        empty_report = client.get(
            f"/api/opponents/{profile_id}/report",
            params={"minimum_sample_size": 10000},
        )
        assert empty_report.status_code == 200
        assert empty_report.json()["filtered_findings"] == 0
        detail_page = client.get(
            f"/ui/opponents/{profile_id}/report/findings/{finding.finding_id}",
            params={"run_id": str(strategy_result.strategy_run_id)},
        )
        assert detail_page.status_code == 200
        assert "Полный знаменатель" in detail_page.text
        assert "Тактическая рекомендация не опубликована" in detail_page.text
        assert str(finding.evidence_references[0].evidence_id) in detail_page.text
        unknown_detail = client.get(
            f"/ui/opponents/{profile_id}/report/findings/{_id('unknown-report-finding')}"
        )
        assert unknown_detail.status_code == 404
        api_skipped = client.get(f"/api/opponents/{profile_id}/analysis/strategies/skipped")
        assert api_skipped.status_code == 200
        assert api_skipped.json()["count"] == len(findings)
        api_strategy_compute = client.post(
            f"/api/opponents/{profile_id}/analysis/strategies/compute"
        )
        assert api_strategy_compute.status_code == 200
        assert api_strategy_compute.json()["status"] == "already_exists"
        api_findings = client.get(
            f"/api/opponents/{profile_id}/analysis/findings",
            params={"type": finding.pattern_type.value},
        )
        assert api_findings.status_code == 200
        assert api_findings.json()["count"] > 0
        api_evidence = client.get(
            f"/api/opponents/{profile_id}/analysis/findings/{finding.finding_id}/evidence"
        )
        assert api_evidence.status_code == 200
        assert api_evidence.json()["count"] == finding.denominator
        api_analysis_compute = client.post(f"/api/opponents/{profile_id}/analysis/compute")
        assert api_analysis_compute.status_code == 200
        assert api_analysis_compute.json()["status"] == "already_exists"

    assert DuckDBRoundFeatureRepository(database).delete_features(first.match.match_id) == 1
    assert repository.get_summary(profile.profile_id) is None
    assert repository.list_runs(profile.profile_id) == ()
    assert analysis_repository.list_runs(profile.profile_id, current_pattern_run_id=None) == ()
    assert strategy_repository.list_runs(profile.profile_id, current_analysis_run_id=None) == ()
