"""Ground-truth world->image anchors for shipped map transforms.

Every prior transform test was a self-consistent round-trip through the same
code, which cannot detect an orientation error (a wrongly rotated or mirrored
projection round-trips perfectly). These tests pin the projection against two
independent evidence sources:

1. Real freeze-end player positions from imported FACEIT demos. Spawn points
   are fixed by the game, so the per-side centroid of the first playback
   sample of round 1 is a known map location.
2. The spawn icon anchors (``CTSpawn_x/_y``, ``TSpawn_x/_y``) recorded in the
   Valve overview ``.txt`` shipped in the same VPK revision
   ``cs2-1.41.7.1-d263aa1118fb`` the definitions are calibrated against.
   Those anchors are normalized image coordinates authored by Valve for the
   shipped radar texture, independent of this repository's transform code.

A correct projection lands each centroid within spawn-area distance of the
Valve anchor. An orientation error (ignored ``rotate`` flag, swapped axes,
mirrored Y) displaces the projection by 0.3-1.0 normalized units, far beyond
the tolerance, so these tests fail loudly instead of silently accepting a
rotated map. This matters most for ``de_dust2``: it is the only shipped map
with ``rotation=90``, where the flag is asserted to be baked into the PNG.
"""

from __future__ import annotations

import pytest

from stratweb.maps.registry import DEFAULT_MAP_REGISTRY
from stratweb.maps.transforms import world_to_map

REVISION_ID = "cs2-1.41.7.1-d263aa1118fb"

# Spawn-area tolerance in normalized image units. Observed deviations between
# demo spawn centroids and Valve icon anchors are <= 0.08 (players spread out
# inside the spawn zone and the icon anchor is not the zone centroid), while
# any rotation/mirror defect displaces points by >= 0.3.
TOLERANCE = 0.15

# Freeze-end per-side player centroids: first playback sample of round 1 of a
# locally imported FACEIT match (world x/y averaged over the five alive
# players of the side), paired with the Valve overview icon anchor for that
# side's spawn. Matches are identified by canonical match id prefix.
# world = (x, y); expected = (CTSpawn_x/TSpawn_x, CTSpawn_y/TSpawn_y).
GROUND_TRUTH_ANCHORS = (
    # de_dust2, match 28492216 (17 rounds), round 1, tick 5811.
    # The only rotation=90 map: this pair proves the rotate flag is baked
    # into the shipped radar texture.
    ("de_dust2", "CT spawn", (257.0, 2415.0), (0.62, 0.21)),
    ("de_dust2", "T spawn", (-704.0, -796.0), (0.39, 0.91)),
    # de_mirage, match e0f188cf (21 rounds), round 1, tick 6456.
    ("de_mirage", "CT spawn", (-1716.8, -1889.6), (0.28, 0.70)),
    ("de_mirage", "T spawn", (1184.0, -171.4), (0.87, 0.36)),
    # de_overpass, match dba336bb (30 rounds), round 1, tick 4964.
    ("de_overpass", "CT spawn", (-2256.0, 793.2), (0.49, 0.20)),
    ("de_overpass", "T spawn", (-1430.8, -3137.1), (0.66, 0.93)),
    # de_ancient, match 24708cef (17 rounds), round 1, tick 10705.
    ("de_ancient", "CT spawn", (-345.6, 1702.4), (0.51, 0.17)),
    ("de_ancient", "T spawn", (-456.0, -2262.4), (0.485, 0.87)),
)


@pytest.mark.parametrize(
    ("canonical_name", "label", "world", "expected"),
    GROUND_TRUTH_ANCHORS,
    ids=[f"{name}-{label.split()[0]}" for name, label, _, _ in GROUND_TRUTH_ANCHORS],
)
def test_world_to_map_matches_valve_spawn_anchors(
    canonical_name: str,
    label: str,
    world: tuple[float, float],
    expected: tuple[float, float],
) -> None:
    definition = DEFAULT_MAP_REGISTRY.get_revision(canonical_name, REVISION_ID)
    assert definition is not None, f"{canonical_name} revision {REVISION_ID} missing"

    result = world_to_map(definition, world[0], world[1], None)
    assert result.normalized_x is not None and result.normalized_y is not None, (
        f"{canonical_name} {label}: projection unavailable ({result.warnings})"
    )
    delta_x = abs(result.normalized_x - expected[0])
    delta_y = abs(result.normalized_y - expected[1])
    assert delta_x <= TOLERANCE and delta_y <= TOLERANCE, (
        f"{canonical_name} {label}: projected ({result.normalized_x:.3f}, "
        f"{result.normalized_y:.3f}) expected ~({expected[0]:.3f}, {expected[1]:.3f}) "
        f"delta ({delta_x:.3f}, {delta_y:.3f}) exceeds {TOLERANCE}"
    )


def test_dust2_rotation_would_be_detected() -> None:
    """Prove the anchors have discriminating power for the rotation case.

    Projecting the dust2 CT-spawn centroid through an *unrotated* interpretation
    (swapped axes, the failure the round-trip tests cannot see) must land far
    outside the tolerance, demonstrating the ground-truth pairs would catch a
    wrongly oriented asset or transform. The CT anchor is the discriminating
    one: the T spawn sits near the x == y diagonal, where an axis swap barely
    moves the projection, so it has no power against rotation on its own.
    """

    definition = DEFAULT_MAP_REGISTRY.get_revision("de_dust2", REVISION_ID)
    assert definition is not None
    assert definition.world_origin_x is not None
    assert definition.world_origin_y is not None
    assert definition.scale is not None
    assert definition.image_width is not None and definition.image_height is not None

    world_x, world_y = 257.0, 2415.0
    expected_x, expected_y = 0.62, 0.21
    # 90-degree-rotated (axis-swapped) projection of the same world point.
    rotated_x = (world_y - definition.world_origin_x) / definition.scale
    rotated_y = (definition.world_origin_y - world_x) / definition.scale
    rotated_norm_x = rotated_x / definition.image_width
    rotated_norm_y = rotated_y / definition.image_height

    assert (
        abs(rotated_norm_x - expected_x) > TOLERANCE
        or abs(rotated_norm_y - expected_y) > TOLERANCE
    ), "rotated projection unexpectedly matches the anchor; test has no power"
