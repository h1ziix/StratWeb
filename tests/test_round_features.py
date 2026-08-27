from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
from fastapi.testclient import TestClient

from stratweb import cli
from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBMatchRepository,
    DuckDBRoundFeatureRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.application.analytics import ComputeMatchAnalyticsService
from stratweb.application.round_features import ComputeRoundFeaturesService
from stratweb.application.spatial import ComputeSpatialStateService
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.application.zone_assignments import ComputeZoneAssignmentsService
from stratweb.features.models import (
    ROUND_FEATURE_RULE_VERSION,
    EarlyZonePresencePayload,
    FeatureAvailability,
    FeatureComputeStatus,
    RoundFeatureConfig,
    RoundFeatureType,
)
from stratweb.main import create_app
from stratweb.spatial.models import SpatialExtraction, SpatialSourceSample


class FeatureFixtureExtractor:
    def __init__(self, players: tuple[Any, ...]) -> None:
        self._players = players

    def extract(
        self, demo_path: Path, ticks: tuple[int, ...], *, expected_sha256: str
    ) -> SpatialExtraction:
        del demo_path
        samples: list[SpatialSourceSample] = []
        for tick in ticks:
            for index, player in enumerate(self._players):
                if index == 0:
                    x, y = (1184.0, -171.4) if tick < 130 else (-465.2, -2178.2)
                else:
                    x, y = (-1716.8, -1889.6) if tick <= 140 else (-465.2, -2178.2)
                samples.append(
                    SpatialSourceSample(
                        tick=tick,
                        steam_id=player.steam_id,
                        player_name=player.current_name,
                        x=x,
                        y=y,
                        z=0.0,
                        inventory_item_ids=(49,) if index == 0 else (),
                    )
                )
        return SpatialExtraction(
            parser_name="fixture",
            parser_version="1.0.0",
            source_demo_sha256=expected_sha256,
            requested_ticks=ticks,
            source_columns=("tick", "steamid", "X", "Y", "Z", "inventory_as_ids"),
            samples=tuple(samples),
        )


def _feature_fixture(
    tmp_path: Path, canonical_dataset_factory: Any
) -> tuple[Path, Any, ComputeRoundFeaturesService]:
    dataset = canonical_dataset_factory("round-features")
    database = tmp_path / "round-features.duckdb"
    matches = DuckDBMatchRepository(database)
    analytics = DuckDBAnalyticsRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    zones = DuckDBZoneAssignmentRepository(database)
    features = DuckDBRoundFeatureRepository(database)
    matches.save_match(dataset)
    ComputeMatchAnalyticsService(matches, analytics).compute(dataset.match.match_id)
    ComputeTemporalStateService(
        matches,
        temporal,
        analytics_repository=analytics,
    ).compute(dataset.match.match_id)
    ComputeSpatialStateService(
        matches,
        temporal,
        spatial,
        FeatureFixtureExtractor(dataset.players),
    ).compute(dataset.match.match_id, tmp_path / "ignored.dem")
    ComputeZoneAssignmentsService(spatial, zones).compute(dataset.match.match_id)
    service = ComputeRoundFeaturesService(
        matches,
        analytics,
        temporal,
        spatial,
        zones,
        features,
    )
    return database, dataset, service


def test_round_features_are_deterministic_evidenced_and_queryable(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, service = _feature_fixture(tmp_path, canonical_dataset_factory)
    config = RoundFeatureConfig(
        checkpoint_offsets_ticks=(16, 32, 48),
        early_window_ticks=64,
    )

    computed = service.compute(dataset.match.match_id, config=config)
    repeated = service.compute(dataset.match.match_id, config=config)
    repository = DuckDBRoundFeatureRepository(database)
    records = repository.list_features(dataset.match.match_id, limit=5000)

    assert computed.status is FeatureComputeStatus.COMPUTED
    assert repeated.status is FeatureComputeStatus.ALREADY_EXISTS
    assert repeated.feature_fingerprint == computed.feature_fingerprint
    assert computed.summary.features == len(records)
    assert computed.summary.features == (
        computed.summary.available
        + computed.summary.partial
        + computed.summary.unavailable
        + computed.summary.not_applicable
    )
    assert records
    assert all(item.feature_rule_version == ROUND_FEATURE_RULE_VERSION for item in records)
    assert all(item.match_id == dataset.match.match_id for item in records)
    assert all(item.limitations is not None for item in records)
    assert any(
        item.feature_type is RoundFeatureType.FIRST_CONTACT and item.evidence_event_ids
        for item in records
    )
    assert any(
        item.feature_type is RoundFeatureType.STARTING_ZONE_DISTRIBUTION
        and item.evidence_snapshot_ids
        for item in records
    )
    assert any(
        item.feature_type is RoundFeatureType.FIRST_UTILITY
        and item.availability is FeatureAvailability.PARTIAL
        and "source_observes_effect_not_throw_tick" in item.limitations
        for item in records
    )
    assert any(item.feature_type is RoundFeatureType.BOMBSITE for item in records)
    for item in records:
        if isinstance(item.payload, EarlyZonePresencePayload):
            assert len(item.evidence_snapshot_ids) == len(item.payload.player_ids)
    assert not any(
        item.feature_type is RoundFeatureType.RETAKE_ATTEMPT
        and item.availability is FeatureAvailability.AVAILABLE
        for item in records
    )


def test_round_feature_api_cli_and_dependency_cascade(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    capsys: Any,
) -> None:
    database, dataset, service = _feature_fixture(tmp_path, canonical_dataset_factory)
    service.compute(dataset.match.match_id)
    match_id = dataset.match.match_id

    assert cli.main(["features", "status", str(match_id), "--db", str(database)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["feature_rule_version"] == ROUND_FEATURE_RULE_VERSION

    with TestClient(create_app(database)) as client:
        summary = client.get(f"/api/features/{match_id}/summary")
        contacts = client.get(
            f"/api/features/{match_id}/records",
            params={"round": 1, "type": "first_contact"},
        )
    assert summary.status_code == 200
    assert contacts.status_code == 200
    assert contacts.json()["count"] > 0
    assert all(item["feature_type"] == "first_contact" for item in contacts.json()["features"])

    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE round_feature_runs SET feature_rule_version = 'legacy_v0' WHERE match_id = ?",
            [match_id],
        )
    repository = DuckDBRoundFeatureRepository(database)
    assert repository.get_summary(match_id) is None
    assert repository.list_runs(match_id)[0].compatible is False
    assert repository.list_runs(match_id)[0].selected_by_default is False

    assert DuckDBZoneAssignmentRepository(database).delete_zone_assignments(match_id) == 1
    assert repository.list_runs(match_id) == ()
    assert DuckDBSpatialRepository(database).get_summary(match_id) is not None


def test_round_feature_ui_renders_cards_filters_evidence_and_links(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, service = _feature_fixture(tmp_path, canonical_dataset_factory)
    service.compute(
        dataset.match.match_id,
        config=RoundFeatureConfig(
            checkpoint_offsets_ticks=(16, 32, 48),
            early_window_ticks=64,
        ),
    )

    with TestClient(create_app(database)) as client:
        page = client.get(f"/ui/matches/{dataset.match.match_id}/features")
        filtered = client.get(
            f"/ui/matches/{dataset.match.match_id}/features",
            params={"round": 1, "side": "T", "type": "first_contact"},
        )
        overview = client.get(f"/ui/matches/{dataset.match.match_id}")

    assert page.status_code == 200
    assert "Что происходило в каждом раунде" in page.text
    assert "Где был перелом" in page.text
    assert "Какая проблема найдена" in page.text
    assert "Режим аналитика" in page.text
    assert "Таблица доказательств" in page.text
    assert "Что произошло" in page.text
    assert "Технические данные" in page.text
    assert "Показать момент" in page.text
    assert "Посмотреть раунд" in page.text
    ordinary_view = page.text.split('<details class="analyst-mode">', 1)[0]
    assert "smokegrenade_detonate" not in ordinary_view
    assert '<details class="analyst-mode">' in page.text
    assert "mode=smooth" in page.text
    assert "mode=exact" not in page.text
    assert "Alpha" in page.text
    assert filtered.status_code == 200
    assert 'option value="first_contact" selected' in filtered.text
    assert 'option value="T" selected' in filtered.text
    assert "Инициатор: Alpha" in filtered.text
    assert overview.status_code == 200
    assert "Факты по игре" in overview.text


def test_round_feature_ui_explains_missing_compatible_run(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("round-feature-ui-missing")
    database = tmp_path / "missing-features.duckdb"
    DuckDBMatchRepository(database).save_match(dataset)

    with TestClient(create_app(database)) as client:
        response = client.get(f"/ui/matches/{dataset.match.match_id}/features")

    assert response.status_code == 200
    assert "Разбор раундов пока недоступен" in response.text
