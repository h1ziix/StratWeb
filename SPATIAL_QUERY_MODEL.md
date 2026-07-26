# Spatial Query & Visualization Layer 1.0

## Scope and authority

Stage 7.1 is a read-only exploration layer over one persisted compatible Spatial run.
It answers where a player, team, or source-supported C4 carrier was at an authoritative
tick. It does not name zones, interpolate routes, measure spacing, recognize rotations,
or produce tactical conclusions. The stored Spatial schema remains `1.0.0`; Spatial rule
`1.1.0` additionally samples every exact Temporal event tick so timeline links never
silently resolve to a nearby sample.

The dependency direction is:

```text
DuckDB canonical labels + one Temporal 1.1 run + one Spatial 1.1 run
  -> indexed SpatialRepository queries
  -> SpatialExplorerService typed read models
  -> official local overview projection
  -> JSON API / server-rendered map and path pages
```

Temporal remains authoritative for rounds, ticks, alive state, side, physical team, and
event identity. Spatial supplies source-decoded coordinates/view angles and derived C4
carrier state. The query/UI layer performs projection and presentation only.

## Query contracts

`SpatialExplorerService` exposes deterministic operations for:

- exact tick lookup with player/team/alive/C4 filters;
- all authoritative sampled ticks in a round;
- reliable alive-player path in one round;
- raw round path with optional team/player/alive filters;
- one physical-team snapshot at an exact tick;
- nearest players by Euclidean 3D Source 2 world-unit distance;
- carried-C4 position at an exact tick;
- Temporal death/bomb markers and already-persisted Stage 5 opening/direct-trade markers.

An absent tick returns `navigation.status=unavailable`, empty players, adjacent available
ticks, and a warning. It is never rounded or interpolated. Player paths exclude dead-pawn
and `unreliable` positions. Lines connect consecutive stored samples in tick order and do
not claim the exact route between them.

## Overview projection

Overview assets are read only from `STRATWEB_MAP_OVERVIEW_DIR`. A map is available only
when an exact `de_*.png` and `de_*.txt` pair is present and valid. The registry publishes
both SHA-256 hashes and the metadata values. For current unrotated official overviews:

```text
pixel_x = (world_x - pos_x) / scale
pixel_y = (pos_y - world_y) / scale
```

Source 2 yaw `0` points along `+X`; yaw `90` points along `+Y`, which maps upward in image
coordinates. The server computes a typed direction segment; browser code does not invent
angle semantics. Nonzero overview rotation is typed unavailable until a separately tested
transform is implemented.

The repository does not redistribute CS2 assets. They are extracted from the user's own
local CS2 VPK with the audited Source2Viewer CLI build. The reproducible installer is:

```powershell
python .\scripts\install_map_overview.py de_ancient `
  --cs2-root "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive" `
  --vrf-cli "C:\path\to\Source2Viewer-CLI.exe" `
  --output .\data\map_overviews
```

The script requires Source2Viewer CLI
`19.2.6339+c72208352f5bf62f1482447ed166c548f303f8fa` and invokes its documented VPK
`--decompile`/`--vpk_filepath` interface. It extracts the exact radar texture plus
`resource/overviews/{map}.txt`, validates expected outputs, and prints both hashes.

## C4 and event overlays

C4 is shown only when the Spatial foundation confirms inventory item ID 49. Its position
is the carrier pawn origin at the same tick. A dropped or planted C4 entity position is
not inferred. Event overlays are ordinary evidence markers:

- death, plant, defuse, and explosion come from the selected Temporal run;
- opening duel and direct trade reuse persisted deterministic Stage 5 records;
- the marker uses the involved player's exact-tick position when available;
- missing event position remains visible in the event list with a typed warning.

Opening/trade records are displayed, not recomputed or interpreted by Stage 7.1.

## Read optimization and migrations

No UI query loads all snapshot payloads and filters them in Python. Tick and player-path
lookups use materialized keys scoped by Spatial run and round. Migrations `008`–`012`
provide the upgrade path:

1. `008` records the original query-index attempt for already deployed databases.
2. `009` backfills deterministic lookup keys without changing typed Spatial payloads.
3. `010` creates read-optimized query rows and single-column DuckDB ART indexes while
   they are empty.
4. `011` backfills those rows from existing Spatial snapshots.
5. `012` adds match scope used by canonical replace/delete without joining run tables.

New Spatial saves write the immutable snapshot and its query row in the same transaction;
replace/delete removes query rows first. Query rows duplicate the typed payload by design
so an indexed lookup does not join back through an ineligible compound index. A
materialized key-selection is used before alive/team/reliability filters because DuckDB
1.5.4 otherwise abandons the ART scan when extra predicates are added.

The real FACEIT database plan reports `Index Scan` for exact tick and player path queries.
The selected rows are 10 and 117 respectively, with measured DuckDB execution times of
approximately 5 ms and 9 ms on the validation machine. Round tick enumeration reads only
tick columns; it never deserializes all payloads.

Initialization is protected by a process-wide per-database barrier. Its cache key includes
the full migration checksums and database file identity/mtime, so concurrent read requests
cannot mix read-write migration checks with read-only DuckDB connections, while an
external file change or checksum mutation forces revalidation.

The HTTP explorer also keeps immutable run metadata, round ticks, labels, timelines and
analytics markers in a process-local read cache. This is intentionally a read-only server
optimization: restart the web process after computing, replacing or deleting a Spatial run
so one page never combines cached metadata from one run with snapshots from another.

## HTTP surface

Map UI:

```text
/ui/spatial/{match_id}/rounds/{round_number}?tick={tick}
/ui/spatial/{match_id}/rounds/{round_number}/players/{player_id}/path
```

JSON:

```text
/api/spatial/{match_id}/rounds/{round}/ticks
/api/spatial/{match_id}/rounds/{round}/ticks/{tick}
/api/spatial/{match_id}/map-snapshot?round={round}&tick={tick}
/api/spatial/{match_id}/rounds/{round}/teams/{team}/ticks/{tick}
/api/spatial/{match_id}/rounds/{round}/players/{player}/path
/api/spatial/{match_id}/rounds/{round}/path
/api/spatial/{match_id}/rounds/{round}/ticks/{tick}/nearest?player={player}
```

The map provides round/team/player/alive/C4 filters, authoritative-tick scrubber,
previous/next/play/pause, event jumps, player labels/view directions, C4 and event
markers. Every map tick links to the same Temporal run/tick; timeline event/group entries
link back to the same spatial tick. A page never combines two Spatial or Temporal runs.

## FACEIT validation and limitations

The available `de_ancient` FACEIT demo has 17 completed rounds. Spatial rule `1.1.0`
produced 7,315 requested ticks, 73,150 player snapshots, 4,200 carried-C4 snapshots, and
591 nonfatal validation issues. Round 1 opening tick `11850` and round 10 opening tick
`66721` each return exact state, ten projected players, ten view directions, and linked
death/opening markers. Plant, defuse, explosion, and direct-trade marker ticks also resolve
exactly. Temporal snapshot and event links return HTTP 200 in both directions.

The separate 30-round `de_mirage` Temporal database references source SHA-256
`71e5210adb6a03744119565b644b2ce54aa6ead1be5f4297fb5152782cda5ce0`, but that exact
`.dem` is not present locally. It therefore has no Spatial run, and round 30 cannot be
honestly spatially validated or displayed. Reusing the unrelated 17-round demo or
inventing coordinates is prohibited. The exact source demo must be restored before that
acceptance item can be completed.

Other limitations remain: no dropped/planted C4 entity tracking, no overview rotation,
no interpolation, nav mesh, line of sight, zones, heatmaps, tactics, coaching, or AI.
Stage 8 has not started.
