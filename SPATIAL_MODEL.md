# Spatial Engine 1.2

## Scope

Spatial Engine is a deterministic, offline foundation for answering only: where was a
player or a source-supported object at a proven match tick? It does not assign named map
zones, infer movement paths, recognize tactics, judge play, or generate recommendations.
Current Spatial schema is `1.2.0`; rule `1.3.0` adds the audited projectile/effect layer
and playback-fidelity provenance. Legacy runs remain visible but are not selected by default.

The data flow is one-way:

```text
completed .dem + persisted canonical match + compatible Temporal 1.1 run
  -> Demoparser2SpatialExtractor (explicit Temporal ticks only)
  -> typed SpatialExtraction
  -> pure SpatialEngine + independent validation
  -> immutable SpatialMatchState and deterministic fingerprint
  -> SpatialRepository / DuckDB migrations 007-014
  -> CLI JSON, query service, read-only table UI
```

No seconds are present in this model. A tick selected from an existing Temporal round is
the only time coordinate. Spatial state never creates a round or tick boundary.

## demoparser2 0.41.4 audit

The production adapter is pinned to `demoparser2==0.41.4`. The audit checked the installed
wheel, the upstream source at tag `v0.41.4`, `DemoParser.list_updated_fields()` on the
FACEIT fixture, and direct calls against that fixture. The actual relevant signature is:

```python
parse_ticks(wanted_props, *, players=None, ticks=None, prop_states=None)
```

The adapter requests exactly `X`, `Y`, `Z`, `pitch`, `yaw`, `is_alive`, `team_num`, and
`inventory_as_ids`, restricted by `ticks=`. The returned dataframe also supplies player
identity columns (`steamid`, `name`) and `tick`.

Observed source classification:

| Value | Classification | Reason |
|---|---|---|
| `X`, `Y`, `Z` | demo entity-derived | demoparser2 decodes pawn/entity state; it is not a canonical event field |
| `pitch`, `yaw` | demo entity-derived | decoded player view state at the sampled tick |
| alive | Temporal-authoritative | parser `is_alive` is retained only as a validation cross-check |
| physical team and T/CT side | Temporal-authoritative | taken from the Temporal participant state for that round |
| `has_bomb` | derived | true only when `inventory_as_ids` contains CS2 item definition index `49` |
| carried bomb position | derived | the confirmed carrier's player origin at that tick |
| dropped/planted bomb position | unavailable | no supported C4 entity-position contract was found in this parser version |
| map name | demo/canonical source | inherited from the matching canonical dataset |
| map bounds, spawns, bomb-site coordinates | unavailable | not supplied by the audited parser contract |

`is_bomb_dropped` and `is_bomb_planted` are global boolean state values repeated on tick
rows, not object coordinates. Event actor coordinates are not relabelled as bomb
coordinates. The adapter fails if its installed parser version or source demo SHA-256 does
not match the persisted provenance.

## Snapshot contract

Each immutable `SpatialSnapshot` contains:

- stable snapshot, match, Temporal run, round and participant IDs;
- authoritative `round_number` and `tick`;
- nullable raw Source 2 `x`, `y`, `z`, `pitch`, and `yaw`;
- alive state replayed from Temporal, plus parser-independent physical team and side;
- nullable derived `has_bomb`;
- map, source, authority labels, and per-field availability with warnings.

All three position coordinates are present together or all are null. Dead-pawn position
and view values remain visible evidence but are marked `unreliable`; they are excluded
from reliable capability coverage. No interpolation is performed between sampled ticks.

Sampling begins at `live_start_tick` (or the Temporal start fallback), ends at the proven
effective round end before the next round, uses a configurable tick interval (default 16),
and includes both boundaries plus every stored Temporal event tick. This avoids inventing
respawn/reset semantics while allowing exact timeline-to-map links. The interval and
event-tick policy are part of the config hash and run fingerprint.

## Map and coordinate model

Coordinates are raw `source2_world_units` with untransformed Source 2 `+X`, `+Y`, and
vertical `+Z` axes. The Stage 7 foundation performs no radar transform. Stage 7.1 projects
read models with a separately hashed official local overview pair; stored snapshots remain
raw. `SpatialMapModel` supports typed bounds, spawn points, and bomb-site points, but they remain null/empty with typed
`unavailable` status until an authoritative versioned source is added. Names such as
Window, Connector, Banana, or Ramp are intentionally absent.

## Capability and availability semantics

Each capability records `status`, `authority`, population, covered rows, source fields,
sampling interval, and warnings. Status is one of `available`, `partial`, `unavailable`,
or `unreliable`.

- positions: reliable alive-player coordinate coverage;
- view angles: reliable angle coverage (dead-pawn view is unreliable);
- bomb positions: sampled ticks with a live confirmed C4 carrier; planted/dropped remain
  unavailable;
- map metadata: map name plus optional authoritative geometry metadata;
- sampling frequency: coverage of requested Temporal ticks.

Missing capability never becomes a zero coordinate or a false claim.

## Validation

The engine checks per-player monotonic source ticks, duplicate participant/tick rows,
unknown Steam IDs, participant-round mismatch, rows outside the requested Temporal tick
set, parser/Temporal alive or side disagreement, incomplete coordinate tuples, non-finite
angles, and a configurable absolute coordinate safety bound. Pydantic rejects NaN and
Infinity at the typed boundary. Structural contradictions are fatal before persistence;
recoverable source gaps are stored as typed issues and availability.

## Persistence and run selection

Migration `007 spatial_engine_foundation` adds independent `spatial_runs`,
`spatial_snapshots`, `bomb_position_snapshots`, and `spatial_validation_issues` tables.
Every child row carries a Spatial run ID, match ID, Temporal run ID, round/tick keys, and a
versioned typed payload. Save/replace/delete is transactional and does not alter canonical,
analytics, or Temporal data. Repeating the same dataset, Temporal fingerprint, parser,
source SHA, config, and rules produces the same IDs/fingerprint and `already_exists`.

Multiple runs may coexist when their version/config/provenance differs. Default queries
select only the newest exact compatible Spatial schema `1.2.0` / rule `1.3.0` run. Run history exposes actual
schema/rule versions and compatibility; snapshots from different runs are never combined.

## Known limitations

- The validated corpus currently contains FACEIT SourceTV demos; Valve, HLTV, and POV
  coverage still needs additional fixtures.
- Parser entity state may disagree with event-derived Temporal alive state near unusual
  lifecycle/reset conditions. Temporal remains authoritative and every disagreement is a
  validation issue.
- The parser exposes pawn origins, not semantic foot position or visibility.
- Visual-only player interpolation and sampled projectile trails exist, but neither is persisted
  as evidence. There is no speculative velocity/trajectory simulation, line-of-sight, collision,
  nav mesh, map zone, heatmap, or tactical inference.
- Inventory-based C4 ownership is derived and cannot locate a dropped or planted C4.
- DuckDB remains a single-local-writer workflow.

Stage 7.1 query, map projection, API, asset provenance, and performance semantics are
specified in [SPATIAL_QUERY_MODEL.md](SPATIAL_QUERY_MODEL.md).

Stage 7.4 projectile authority, persistence, and rendering are specified in
[PROJECTILE_MODEL.md](PROJECTILE_MODEL.md),
[PROJECTILE_PARSER_AUDIT.md](PROJECTILE_PARSER_AUDIT.md), and
[UTILITY_RENDERING.md](UTILITY_RENDERING.md). Playback interpolation and buffering are normative
in [PLAYBACK_MODEL.md](PLAYBACK_MODEL.md).
