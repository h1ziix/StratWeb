from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from stratweb.maps.models import MapSelectionStatus
from stratweb.spatial.models import SpatialAvailabilityStatus
from stratweb.spatial.query_models import MapOverview
from stratweb.web.view_models.match_readiness import (
    MATCH_READINESS_VIEW_VERSION,
    MatchReadinessState,
    build_match_readiness,
)
from stratweb.web.view_models.product import (
    HealthItemView,
    MatchLibraryItemView,
    MatchOverviewView,
)


def test_readiness_explains_user_impact_without_guessing_missing_zones() -> None:
    overview = _overview(
        canonical="available",
        analytics="available",
        temporal="available",
        spatial="partial",
    )
    map_overview = MapOverview(
        map_name="de_dust2",
        status=SpatialAvailabilityStatus.AVAILABLE,
        canonical_name="de_dust2",
        display_name="Dust II",
        selected_revision="fixture-revision",
        revision_selection_status=MapSelectionStatus.UNPROVEN,
        image_url="/assets/map-overviews/de_dust2.png",
        source="test",
    )

    result = build_match_readiness(overview, map_overview, None)

    assert result.view_version == MATCH_READINESS_VIEW_VERSION
    assert result.state is MatchReadinessState.LIMITED
    assert result.available_capability_count == 3
    assert tuple(item.status for item in result.capabilities) == (
        "partial",
        "available",
        "available",
    )
    assert {item.title for item in result.issues} == {
        "Не все позиции попали в 2D-повтор",
        "Версия карты не подтверждена демкой",
        "Названия зон пока не рассчитаны",
    }


def test_readiness_blocks_when_no_user_facing_result_is_available() -> None:
    result = build_match_readiness(
        _overview(
            canonical="unavailable",
            analytics="unavailable",
            temporal="unavailable",
            spatial="unavailable",
        ),
        None,
        None,
    )

    assert result.state is MatchReadinessState.BLOCKED
    assert result.available_capability_count == 0
    assert result.primary_action_label == "Открыть карточку матча"
    assert "Демка прочитана не полностью" in {item.title for item in result.issues}


def _overview(*, canonical: str, analytics: str, temporal: str, spatial: str) -> MatchOverviewView:
    match_id = uuid4()
    return MatchOverviewView(
        match=MatchLibraryItemView(
            match_id=match_id,
            short_id=str(match_id).split("-")[0],
            map_name="de_dust2",
            source_name="fixture.dem",
            imported_at=datetime.now(UTC),
            round_count=24,
            teams=(),
            score_available=False,
            canonical_status=canonical,
            analytics_status=analytics,
            temporal_status=temporal,
            spatial_status=spatial,
            warning_count=0,
        ),
        rounds=(),
        players=(),
        health=(
            HealthItemView(label="Canonical", status=canonical, detail="fixture"),
            HealthItemView(label="Analytics", status=analytics, detail="fixture"),
            HealthItemView(label="Temporal", status=temporal, detail="fixture"),
            HealthItemView(label="Spatial", status=spatial, detail="fixture"),
        ),
        opening_duels=0,
        trades=0,
        plants=0,
        defuses=0,
        developer_details={},
    )
