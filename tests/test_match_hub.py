from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from stratweb.spatial.models import SpatialAvailabilityStatus
from stratweb.spatial.query_models import MapOverview
from stratweb.web.view_models.match_hub import MATCH_HUB_VIEW_VERSION, build_match_hub
from stratweb.web.view_models.match_readiness import (
    MatchReadinessState,
    MatchReadinessView,
)
from stratweb.web.view_models.product import (
    HealthItemView,
    MatchLibraryItemView,
    MatchOverviewView,
    RoundStripItemView,
)


def test_match_hub_uses_one_best_round_destination() -> None:
    match_id = uuid4()
    overview = _overview(
        match_id,
        rounds=(
            RoundStripItemView(
                round_number=1,
                winner="Команда 1 · T",
                score="1:0",
                complete=True,
                map_href=f"/ui/spatial/{match_id}/rounds/1",
                timeline_href=f"/ui/temporal/{match_id}/rounds/1",
            ),
        ),
    )
    map_overview = MapOverview(
        map_name="de_dust2",
        status=SpatialAvailabilityStatus.AVAILABLE,
        image_url="/assets/map-overviews/de_dust2.png",
        source="fixture",
    )

    result = build_match_hub(
        overview,
        _readiness(match_id),
        map_overview,
        economy_available=True,
        features_available=True,
    )

    assert result.view_version == MATCH_HUB_VIEW_VERSION
    assert result.primary_action_label == "Смотреть матч"
    assert result.primary_action_href == f"/ui/spatial/{match_id}/rounds/1"
    assert result.rounds[0].href == result.primary_action_href
    assert tuple(item.status for item in result.sections) == (
        "available",
        "available",
        "available",
    )
    assert result.map_image_url == "/assets/map-overviews/de_dust2.png"


def test_match_hub_marks_missing_optional_sections_without_inventing_content() -> None:
    match_id = uuid4()

    result = build_match_hub(
        _overview(match_id),
        _readiness(match_id),
        None,
        economy_available=False,
        features_available=False,
    )

    assert result.primary_action_label == "Посмотреть составы"
    assert result.primary_action_href == f"/ui/matches/{match_id}#players"
    assert result.sections[0].status == "unavailable"
    assert result.sections[1].href is None
    assert result.sections[2].href is None


def test_match_hub_falls_back_to_timeline_when_positions_are_unavailable() -> None:
    match_id = uuid4()
    map_href = f"/ui/spatial/{match_id}/rounds/1"
    timeline_href = f"/ui/temporal/{match_id}/rounds/1"
    overview = _overview(
        match_id,
        rounds=(
            RoundStripItemView(
                round_number=1,
                winner="Команда 1 · T",
                score="1:0",
                complete=True,
                map_href=map_href,
                timeline_href=timeline_href,
            ),
        ),
        spatial_status="unavailable",
    )

    result = build_match_hub(
        overview,
        _readiness(match_id),
        None,
        economy_available=False,
        features_available=False,
    )

    assert result.primary_action_href == timeline_href
    assert result.rounds[0].href == timeline_href
    assert result.primary_action_href != map_href


def _overview(
    match_id: UUID,
    *,
    rounds: tuple[RoundStripItemView, ...] = (),
    spatial_status: str = "available",
    temporal_status: str = "available",
) -> MatchOverviewView:
    return MatchOverviewView(
        match=MatchLibraryItemView(
            match_id=match_id,
            short_id=str(match_id).split("-")[0],
            map_name="de_dust2",
            source_name="fixture.dem",
            imported_at=datetime.now(UTC),
            round_count=len(rounds),
            teams=(),
            score_available=False,
            canonical_status="available",
            analytics_status="available",
            temporal_status="available",
            spatial_status="available",
            warning_count=0,
        ),
        rounds=rounds,
        players=(),
        health=(
            HealthItemView(label="Spatial", status=spatial_status, detail="fixture"),
            HealthItemView(label="Temporal", status=temporal_status, detail="fixture"),
        ),
        opening_duels=0,
        trades=0,
        plants=0,
        defuses=0,
        developer_details={},
    )


def _readiness(match_id: UUID) -> MatchReadinessView:
    return MatchReadinessView(
        state=MatchReadinessState.READY,
        status_label="Всё готово",
        title="Разбор готов",
        lead="fixture",
        primary_action_label="Открыть разбор",
        primary_action_href=f"/ui/matches/{match_id}",
        capabilities=(),
        issues=(),
        available_capability_count=3,
    )
