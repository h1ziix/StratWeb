# Projectile Evidence Model 1.0

The projectile layer is read-only, parser-independent, run-aware, and separate from player
`SpatialSnapshot` rows. It does not simulate missing trajectory points or infer tactics.

## Typed entities

`ProjectileType` supports smoke, flashbang, HE, molotov, incendiary, decoy, and unknown.
`ProjectileLifecycle` supports thrown, in-flight, bounced, landed, detonated, effect-active,
expired, and unavailable.

The source adapter produces:

- `ProjectileSourceTrack`: segmented parser entity evidence, owner, type, first/terminal ticks,
  initial velocity when present, and sampled points;
- `ProjectileSourcePoint`: x/y/z, cumulative bounce count, lifecycle, authority source, warnings;
- `UtilityEffectSource`: start/end game events and an event-provided center.

The deterministic Spatial engine maps these to `SpatialProjectile`, `ProjectileSnapshot`, and
`UtilityEffect` using the selected Temporal 1.1 run. Player/team/side ownership is copied only
when SteamID resolves to a canonical participant in that round.

## Authority boundaries

- Projectile x/y/z ticks come from `parse_grenades(grenades=False)` entity rows.
- `weapon_fire` supplies an authoritative action tick, but association to a track is derived by
  same owner/type and a bounded 64-tick offset. The offset remains in warnings.
- Direct terminal entity-id matching has priority. If Source 2 uses a different event entity id,
  a terminal event may be associated by owner/type/tick and a 512-unit position bound. Capability
  authority then becomes `derived_association`.
- Bounce is the first observed tick where cumulative `Grenade.m_nBounces` increases. It is not
  represented as a game event.
- `Grenade.m_vInitialVelocity` is initial velocity only. Per-tick velocity is unavailable.
- Effect radius is `null`; the parser audit found no authoritative radius field.

## Sampling and identity

Projectile entity ids are reused across rounds. A stable track therefore combines entity id,
type, owner, monotonic contiguous ticks, and bounce-reset boundaries. Raw entity id alone is not
a projectile identity.

Trajectory rows are sampled every 4 ticks plus first, terminal, and bounce-change ticks. This
limits persistence and browser memory while keeping parser evidence. A terminal game-event point
after the last entity row is stored as a separate point with
`trajectory_to_terminal_event_not_interpolated`; no missing path is filled.

## Persistence and run compatibility

Migration 14 adds:

- `spatial_projectiles`;
- `spatial_projectile_snapshots`;
- `spatial_utility_effects`;
- `spatial_runs.projectile_metadata`;
- `spatial_runs.projectile_capabilities`.

The run metadata pins parser version, extraction rule, requested properties/events, sampling
policy, and capability fingerprint. Legacy runs remain readable with projectile capability
`unavailable` and warning `legacy_spatial_run_without_projectile_layer`; no backfill is claimed.

Playback schema 1.1 returns distinct `player_samples`, `projectile_samples`, `utility_effects`,
and `event_markers` collections. It never serializes a browser-interpolated coordinate.

