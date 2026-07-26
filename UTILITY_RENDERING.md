# Utility Rendering Contract

The map viewer renders utility evidence in independent persistent SVG layers:

1. stored projectile trails;
2. utility effect centers;
3. player markers;
4. projectile markers;
5. C4;
6. bounded-lifetime event markers.

## What is drawn

- A projectile marker uses the latest stored projectile point at or before the visual playback
  tick. It is a held authoritative point, not a simulated coordinate.
- Trails connect only consecutive stored points. They split at gaps over 16 ticks and before a
  terminal event point explicitly marked as discontinuous.
- Bounce and detonation lifecycle are shown by marker style/pulse when proven.
- A throw pulse is placed at the owner's SpatialSnapshot. The action tick comes from
  `weapon_fire`; a non-zero owner-sample offset is included in warnings and is never called exact.
- Smoke/fire are neutral center markers active only between proven start/end ticks.
- Flash and HE use instantaneous detonation markers. Affected players and blast models are not
  computed.
- Decoy is rendered only when the demo exposes its lifecycle.

Effect radius is unavailable in the audited parser contract. The UI labels smoke/fire markers
`radius unavailable` and uses a small fixed icon, not a gameplay-radius claim. Molotov/inferno
does not draw an ideal circle or inferred fire cells.

## Filters and rejected entities

The viewer supports a global utility toggle plus smoke, flash, HE, molotov, incendiary, fire, and
decoy filters. Team/player filters apply through the proven projectile owner mapping.

Every player, bomb, projectile, utility effect, and event has its own typed category. Projection
outside the pinned overview produces `render_status=rejected` and a diagnostic reason while raw
world coordinates remain in JSON. Unknown entities never fall back to a white point at `(0, 0)`
and coordinates are never clamped to image edges.

## Event lifetime and run alignment

Shot, damage, grenade, death, bomb, opening, and trade markers exist only in their current
evidence interval. They link to the exact Temporal event when one exists; canonical shot/damage
markers link to the selected Temporal snapshot tick. Same-tick Temporal ordering is not changed.

Projectile/effect rows always carry the selected `temporal_run_id` and are queried with one pinned
`spatial_run_id`. A page never combines legacy and current runs.

