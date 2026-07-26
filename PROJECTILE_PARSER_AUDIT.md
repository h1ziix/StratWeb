# demoparser2 Projectile Audit

## Audited build and methods

The project remains pinned to `demoparser2==0.41.4`. The installed signatures and upstream tag
source at commit `db3ba5f7a1b02b8cb27d0063d52649883a98469c` were inspected before implementation:

```text
parse_grenades(*, extra=None, grenades=True)
parse_events(event_name, *, player=None, other=None)
parse_event(event_name, *, player=None, other=None)
list_game_events()
list_updated_fields()
```

The adapter requests only `Grenade.m_nBounces` and `Grenade.m_vInitialVelocity`, and calls
`parse_grenades(..., grenades=False)`. On the Overpass demo this reduced 2,640,167 default rows
to 378,063 projectile rows; 2,262,104 inventory/non-projectile entity rows were excluded.

## Capability matrix

| Data | 0.41.4 source | Authority/status | Limitation |
|---|---|---|---|
| Projectile tick and x/y/z | `parse_grenades` | authoritative parser entity | sampled every 4 ticks |
| Owner SteamID/name | `parse_grenades` | authoritative parser entity | canonical participant mapping can be partial |
| Grenade type | `grenade_type` | authoritative parser entity | molotov/incendiary refined from associated weapon action |
| Initial velocity | `Grenade.m_vInitialVelocity` | authoritative/partial | not per-tick velocity |
| Bounce | `Grenade.m_nBounces` | derived observation | first cumulative-count change; no bounce game event |
| Throw action | `weapon_fire` | event tick + derived track association | first coordinate is later and stays separate |
| Flash/HE detonation | game events | authoritative event; association may be derived | event entity id can differ |
| Smoke start/end | detonate/expired events | authoritative lifecycle, partial | some starts have no matching end |
| Fire start/end | inferno start/expire | authoritative lifecycle, association derived | no individual fire-cell geometry |
| Decoy lifecycle | decoy events | demo-dependent | Ancient exposes no decoy events |
| Effect radius | none found | unavailable | never invented |

`parse_event` and projectile entity ticks do not have interchangeable semantics. Game events prove
actions/lifecycle; entity rows prove sampled positions. The adapter keeps these authorities
separate.

## Real FACEIT results

| Demo | Map | Parser tracks | Terminal events | Persisted tracks | Persisted points | Effects | Notable warning |
|---|---|---:|---:|---:|---:|---:|---|
| `1-9720fa9b-...dem` | Overpass | 603 | 596 | 603 | final recompute recorded in DuckDB | 596 | 155 bounded terminal associations; 7 tracks without terminal event |
| `1-c380734e-...dem` | Ancient | 235 | 234 | 233 | 9,093 | 233 | 2 warmup/out-of-round tracks excluded; decoy events absent |

Overpass type population is 177 smoke, 131 flash, 125 HE, 161 molotov/incendiary, and 9 decoy
tracks. Ancient lifecycle coverage is 234/235, fire lifecycle 60/60, and smoke end coverage
66/73. These are capability observations, not utility quality scores.

Entity ids were observed to be reused later in the same demo. For example, one Overpass entity
track begins near tick 5529 and the same id reappears near tick 195673. Segmentation is therefore
mandatory.

## Requested events

The exact requested event list is `weapon_fire`, `flashbang_detonate`,
`hegrenade_detonate`, `smokegrenade_detonate`, `smokegrenade_expired`,
`inferno_startburn`, `inferno_expire`, `decoy_started`, and `decoy_detonate`.
Missing event names degrade only the corresponding capability; player Spatial extraction still
completes.

