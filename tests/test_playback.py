from __future__ import annotations

from uuid import UUID, uuid4

from stratweb.application.playback import (
    GapClassification,
    InterpolationBlockReason,
    PlaybackMotionPolicy,
    PlayerSampleSemantics,
    classify_motion,
    interpolate_yaw_shortest_path,
    interpolation_eligibility,
    visual_sample_semantics,
)
from stratweb.domain.enums import Side
from stratweb.spatial.models import (
    SnapshotAvailability,
    SpatialAuthority,
    SpatialAvailabilityStatus,
    SpatialSnapshot,
)

_MATCH = uuid4()
_ROUND = uuid4()
_PLAYER = uuid4()


def _snapshot(tick: int) -> SpatialSnapshot:
    return SpatialSnapshot(
        snapshot_id=uuid4(),
        match_id=_MATCH,
        temporal_run_id=uuid4(),
        round_id=_ROUND,
        round_number=1,
        tick=tick,
        participant_id=_PLAYER,
        x=1.0,
        y=2.0,
        z=3.0,
        yaw=90.0,
        pitch=0.0,
        alive=True,
        has_bomb=False,
        physical_team_id=UUID(int=1),
        side=Side.T,
        map_name="de_mirage",
        source="test",
        position_authority=SpatialAuthority.DEMO_ENTITY_DERIVED,
        view_angle_authority=SpatialAuthority.DEMO_ENTITY_DERIVED,
        availability=SnapshotAvailability(
            position=SpatialAvailabilityStatus.AVAILABLE,
            view_angles=SpatialAvailabilityStatus.AVAILABLE,
            alive_link=SpatialAvailabilityStatus.AVAILABLE,
            has_bomb=SpatialAvailabilityStatus.AVAILABLE,
        ),
    )


def test_interpolation_allows_only_reliable_alive_same_participant_samples() -> None:
    previous = _snapshot(100)
    following = _snapshot(116)

    assert interpolation_eligibility(previous, following).eligible is True

    dead = following.model_copy(update={"alive": False})
    decision = interpolation_eligibility(previous, dead)
    assert decision.eligible is False
    assert decision.reason is InterpolationBlockReason.LIFE_STATE_CHANGED

    unavailable = following.model_copy(
        update={
            "availability": following.availability.model_copy(
                update={"position": SpatialAvailabilityStatus.UNAVAILABLE}
            )
        }
    )
    decision = interpolation_eligibility(previous, unavailable)
    assert decision.eligible is False
    assert decision.reason is InterpolationBlockReason.POSITION_UNAVAILABLE


def test_interpolation_rejects_disappearance_and_round_change() -> None:
    previous = _snapshot(100)
    assert interpolation_eligibility(previous, None).reason is (
        InterpolationBlockReason.PARTICIPANT_DISAPPEARED
    )
    following = _snapshot(116).model_copy(update={"round_number": 2})
    assert interpolation_eligibility(previous, following).reason is (
        InterpolationBlockReason.DIFFERENT_ROUND
    )


def test_gap_classification_motion_metrics_and_suspicious_jump() -> None:
    previous = _snapshot(100)
    normal = _snapshot(116).model_copy(update={"x": 5.0, "y": 5.0, "z": 4.0})
    transition = classify_motion(previous, normal)
    assert transition.classification is GapClassification.NORMAL
    assert transition.tick_gap == 16
    assert transition.delta_x == 4.0
    assert transition.delta_y == 3.0
    assert transition.planar_distance == 5.0
    assert transition.derived_speed_world_units_per_tick == 5.0 / 16.0

    large = normal.model_copy(update={"tick": 148})
    assert classify_motion(previous, large).classification is GapClassification.LARGE
    jump = normal.model_copy(update={"x": 5000.0})
    suspicious = classify_motion(
        previous,
        jump,
        policy=PlaybackMotionPolicy(max_interpolation_planar_distance=100.0),
    )
    assert suspicious.classification is GapClassification.DISCONTINUITY
    assert "suspicious_spatial_jump" in suspicious.warnings


def test_gap_classification_rejects_level_bounds_death_and_unavailable() -> None:
    previous = _snapshot(100)
    following = _snapshot(116)
    assert (
        classify_motion(
            previous, following, previous_level="upper", following_level="lower"
        ).classification
        is GapClassification.DISCONTINUITY
    )
    assert (
        classify_motion(
            previous,
            following,
            previous_inside_map=True,
            following_inside_map=False,
        ).classification
        is GapClassification.DISCONTINUITY
    )
    assert (
        classify_motion(previous, following.model_copy(update={"alive": False})).classification
        is GapClassification.DISCONTINUITY
    )
    unavailable = following.model_copy(
        update={
            "availability": following.availability.model_copy(
                update={"position": SpatialAvailabilityStatus.UNAVAILABLE}
            )
        }
    )
    assert classify_motion(previous, unavailable).classification is GapClassification.UNAVAILABLE


def test_visual_semantics_and_shortest_yaw_path() -> None:
    previous = _snapshot(100)
    following = _snapshot(116).model_copy(update={"x": 10.0})
    transition = classify_motion(previous, following)
    assert (
        visual_sample_semantics(previous, following, transition, alpha=0.5, smooth=True)
        is PlayerSampleSemantics.INTERPOLATED
    )
    held = classify_motion(previous, _snapshot(116))
    assert (
        visual_sample_semantics(previous, _snapshot(116), held, alpha=0.5, smooth=True)
        is PlayerSampleSemantics.HELD
    )
    assert interpolate_yaw_shortest_path(350.0, 10.0, 0.5) == 0.0
    assert interpolate_yaw_shortest_path(10.0, 350.0, 0.5) == 0.0
