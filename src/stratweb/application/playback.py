"""Evidence-safe policy for client-side-only spatial interpolation."""

from __future__ import annotations

from enum import StrEnum
from math import hypot

from pydantic import BaseModel, ConfigDict

from stratweb.spatial.models import (
    SpatialAuthority,
    SpatialAvailabilityStatus,
    SpatialSnapshot,
)


class InterpolationBlockReason(StrEnum):
    DIFFERENT_PARTICIPANT = "different_participant"
    DIFFERENT_ROUND = "different_round"
    NON_FORWARD_TICK = "non_forward_tick"
    POSITION_UNAVAILABLE = "position_unavailable"
    POSITION_UNRELIABLE = "position_unreliable"
    PARTICIPANT_DISAPPEARED = "participant_disappeared"
    LIFE_STATE_CHANGED = "life_state_changed"


class GapClassification(StrEnum):
    NORMAL = "normal"
    LARGE = "large"
    DISCONTINUITY = "discontinuity"
    UNAVAILABLE = "unavailable"


class PlayerSampleSemantics(StrEnum):
    EXACT = "exact"
    INTERPOLATED = "interpolated"
    HELD = "held"
    UNAVAILABLE = "unavailable"
    DEAD = "dead"
    ABSENT = "absent"


class PlaybackMotionPolicy(BaseModel):
    """Presentation safety thresholds; never a claim about CS2 physics or tickrate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    normal_gap_max_ticks: int = 16
    large_gap_max_ticks: int = 64
    max_interpolation_planar_distance: float = 1024.0
    max_interpolation_vertical_distance: float = 512.0


class MotionTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    classification: GapClassification
    interpolation: InterpolationDecision
    tick_gap: int | None = None
    delta_x: float | None = None
    delta_y: float | None = None
    delta_z: float | None = None
    planar_distance: float | None = None
    derived_speed_world_units_per_tick: float | None = None
    repeated_identical_sample: bool = False
    map_bound_transition: bool = False
    level_transition: bool = False
    warnings: tuple[str, ...] = ()


class InterpolationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    eligible: bool
    reason: InterpolationBlockReason | None = None


def interpolation_eligibility(
    previous: SpatialSnapshot | None,
    following: SpatialSnapshot | None,
) -> InterpolationDecision:
    """Decide whether two stored samples may be blended for presentation only."""

    if previous is None or following is None:
        return _blocked(InterpolationBlockReason.PARTICIPANT_DISAPPEARED)
    if previous.participant_id != following.participant_id:
        return _blocked(InterpolationBlockReason.DIFFERENT_PARTICIPANT)
    if previous.round_id != following.round_id or previous.round_number != following.round_number:
        return _blocked(InterpolationBlockReason.DIFFERENT_ROUND)
    if following.tick <= previous.tick:
        return _blocked(InterpolationBlockReason.NON_FORWARD_TICK)
    if previous.alive is not True or following.alive is not True:
        return _blocked(InterpolationBlockReason.LIFE_STATE_CHANGED)
    if (
        previous.availability.position is not SpatialAvailabilityStatus.AVAILABLE
        or following.availability.position is not SpatialAvailabilityStatus.AVAILABLE
        or any(value is None for value in (previous.x, previous.y, following.x, following.y))
    ):
        return _blocked(InterpolationBlockReason.POSITION_UNAVAILABLE)
    if previous.position_authority in {
        SpatialAuthority.UNRELIABLE,
        SpatialAuthority.UNAVAILABLE,
    } or following.position_authority in {
        SpatialAuthority.UNRELIABLE,
        SpatialAuthority.UNAVAILABLE,
    }:
        return _blocked(InterpolationBlockReason.POSITION_UNRELIABLE)
    return InterpolationDecision(eligible=True)


def classify_motion(
    previous: SpatialSnapshot | None,
    following: SpatialSnapshot | None,
    *,
    policy: PlaybackMotionPolicy | None = None,
    previous_inside_map: bool | None = None,
    following_inside_map: bool | None = None,
    previous_level: str | None = None,
    following_level: str | None = None,
) -> MotionTransition:
    """Classify a stored-sample pair without producing an intermediate coordinate."""

    selected = policy or PlaybackMotionPolicy()
    eligibility = interpolation_eligibility(previous, following)
    if previous is None or following is None:
        return MotionTransition(
            classification=GapClassification.UNAVAILABLE,
            interpolation=eligibility,
            warnings=("missing_participant_sample",),
        )
    tick_gap = following.tick - previous.tick
    map_transition = (
        previous_inside_map is not None
        and following_inside_map is not None
        and previous_inside_map != following_inside_map
    )
    level_transition = (
        previous_level is not None
        and following_level is not None
        and previous_level != following_level
    )
    coordinates = (previous.x, previous.y, previous.z, following.x, following.y, following.z)
    if any(value is None for value in coordinates):
        return MotionTransition(
            classification=GapClassification.UNAVAILABLE,
            interpolation=eligibility,
            tick_gap=tick_gap if tick_gap > 0 else None,
            map_bound_transition=map_transition,
            level_transition=level_transition,
            warnings=("invalid_entity_coordinate",),
        )
    assert previous.x is not None and previous.y is not None and previous.z is not None
    assert following.x is not None and following.y is not None and following.z is not None
    delta_x = following.x - previous.x
    delta_y = following.y - previous.y
    delta_z = following.z - previous.z
    planar = hypot(delta_x, delta_y)
    repeated = planar == 0.0 and delta_z == 0.0
    speed = planar / tick_gap if tick_gap > 0 else None
    warnings: list[str] = []
    if repeated:
        warnings.append("repeated_identical_sample")
    if map_transition or previous_inside_map is False or following_inside_map is False:
        warnings.append("out_of_map_coordinate")
    suspicious = (
        planar > selected.max_interpolation_planar_distance
        or abs(delta_z) > selected.max_interpolation_vertical_distance
    )
    if suspicious:
        warnings.append("suspicious_spatial_jump")
    if not eligibility.eligible and eligibility.reason in {
        InterpolationBlockReason.POSITION_UNAVAILABLE,
        InterpolationBlockReason.POSITION_UNRELIABLE,
        InterpolationBlockReason.PARTICIPANT_DISAPPEARED,
    }:
        classification = GapClassification.UNAVAILABLE
    elif (
        not eligibility.eligible
        or suspicious
        or map_transition
        or level_transition
        or tick_gap > selected.large_gap_max_ticks
    ):
        classification = GapClassification.DISCONTINUITY
    elif tick_gap <= selected.normal_gap_max_ticks:
        classification = GapClassification.NORMAL
    else:
        classification = GapClassification.LARGE
    return MotionTransition(
        classification=classification,
        interpolation=(
            eligibility
            if classification in {GapClassification.NORMAL, GapClassification.LARGE}
            else InterpolationDecision(
                eligible=False,
                reason=eligibility.reason,
            )
        ),
        tick_gap=tick_gap if tick_gap > 0 else None,
        delta_x=delta_x,
        delta_y=delta_y,
        delta_z=delta_z,
        planar_distance=planar,
        derived_speed_world_units_per_tick=speed,
        repeated_identical_sample=repeated,
        map_bound_transition=map_transition,
        level_transition=level_transition,
        warnings=tuple(warnings),
    )


def visual_sample_semantics(
    previous: SpatialSnapshot | None,
    following: SpatialSnapshot | None,
    transition: MotionTransition,
    *,
    alpha: float,
    smooth: bool,
) -> PlayerSampleSemantics:
    if previous is None:
        return PlayerSampleSemantics.ABSENT
    if previous.alive is False:
        return PlayerSampleSemantics.DEAD
    if (
        previous.availability.position is not SpatialAvailabilityStatus.AVAILABLE
        or previous.x is None
        or previous.y is None
    ):
        return PlayerSampleSemantics.UNAVAILABLE
    if not smooth or alpha <= 0.0:
        return PlayerSampleSemantics.EXACT
    if following is None:
        return PlayerSampleSemantics.ABSENT
    if following.alive is False:
        return PlayerSampleSemantics.DEAD if alpha >= 1.0 else PlayerSampleSemantics.EXACT
    if transition.classification is GapClassification.UNAVAILABLE:
        return PlayerSampleSemantics.HELD
    if not transition.interpolation.eligible:
        return PlayerSampleSemantics.EXACT
    if transition.repeated_identical_sample:
        return PlayerSampleSemantics.HELD
    return PlayerSampleSemantics.INTERPOLATED


def interpolate_yaw_shortest_path(start: float, end: float, alpha: float) -> float:
    """Visual-only angle interpolation, normalized to [0, 360)."""

    bounded = min(1.0, max(0.0, alpha))
    delta = ((end - start + 180.0) % 360.0) - 180.0
    return (start + delta * bounded) % 360.0


def _blocked(reason: InterpolationBlockReason) -> InterpolationDecision:
    return InterpolationDecision(eligible=False, reason=reason)
