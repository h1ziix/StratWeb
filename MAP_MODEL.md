# Map model and revision contract

Stage 7.3 adds map presentation semantics without adding zones, named locations, map
control, tactical analysis, or inferred routes. Raw Source 2 coordinates remain the
evidence. A map definition is only a versioned projection contract for displaying that
evidence on a matching local overview.

## Typed model

`MapDefinition` is immutable and contains the canonical name, exact aliases, game,
`MapRevision`, overview references, coordinate transform, dimensions, origin, scale,
axis orientation, optional multi-level policy, provenance, calibration status, validation
status, and warnings. Definitions live in `src/stratweb/maps/definitions/`; adding another
definition does not change Spatial extraction or playback logic.

`MapRevision` separates a map name from a particular geometry. A revision may list
authoritative patch versions, map CRCs, or asset versions. Current configured definitions
use revision `cs2-1.41.7.1-d263aa1118fb`, tied to the local CS2 VPK fingerprint documented
in [MAP_ASSETS.md](MAP_ASSETS.md). Historical Cache and Overpass revisions are explicit
unsupported records until a matching asset and calibration are supplied; current radar
data is never borrowed for them.

## Name and revision selection

Normalization strips surrounding whitespace, case-folds, and performs an exact alias
lookup. It is intentionally not fuzzy. `dust_2` is an explicit alias; an unknown or
misspelled map stays unsupported.

Revision selection evaluates evidence in this order:

1. explicit developer/manual revision override;
2. unique matching demo patch/build identifier;
3. unique matching map CRC;
4. unique matching asset version;
5. the single configured current candidate, marked `unproven`.

File timestamps are not selectors. An override is reported as
`manual_revision_override` and does not rewrite canonical demo evidence. If an exact
revision cannot be proved, the response includes `map_revision_unproven`; maps with known
layout-change risk additionally include `map_layout_may_be_incompatible`.

## Pure coordinate transform

`world_to_map(definition, x, y, z)` is deterministic and side-effect free:

```text
pixel_x      = (x - world_origin_x) / scale
pixel_y      = (world_origin_y - y) / scale
normalized_x = pixel_x / image_width
normalized_y = pixel_y / image_height
```

The Valve `rotate` metadata describes preparation of the shipped radar and is already
baked into the image. It is retained as metadata but is not applied a second time. The
inverse transform is used for round-trip and axis tests. Increasing Source X moves right;
decreasing Source Y moves down. Results include normalized and pixel coordinates, level,
availability, and warnings.

There is no clamp. An out-of-bounds point retains its real values, returns `partial`, and
adds `out_of_map_bounds`. Missing calibration, non-finite input, or unknown revision
returns a typed unavailable result. Raw x/y/z is persisted independently and remains
available in diagnostics.

## Multi-level policy

Level policy belongs to the revision. Nuke's installed metadata supplies upper and lower
radars and the split `z=-495`. Values above the split are `upper`, values below it are
`lower`, and the boundary itself is deliberately `unknown` with
`map_level_boundary_ambiguous`. Missing Z also produces `unknown`; the snapshot remains
visible and the UI permits upper, lower, or diagnostic overlay display.

The same `MapLevelPolicy` contract can represent later multi-level revisions without
changing the viewer.

## Spatial run pinning

Spatial schema `1.1.0` / rule `1.2.0` pins:

- raw and canonical map names;
- selected revision and selection evidence/status;
- map-definition schema version and immutable definition fingerprint;
- upper/lower overview checksums;
- transform rule version and calibration status.

The pin participates in the Spatial input fingerprint. Query projection resolves the
exact definition fingerprint; a changed registry cannot silently reinterpret an existing
run. A run created before map pins is served as `legacy_map_semantics` and is not assigned
a revision retroactively. Recompute creates a new isolated run.

## Read-only HTTP contract

- `GET /api/maps`
- `GET /api/maps/{canonical_name}`
- `GET /api/maps/{canonical_name}/revisions`
- `GET /api/maps/{canonical_name}/transform?x=&y=&z=&revision=`
- `GET /api/spatial/{match_id}/map`

Responses expose immutable URLs and public semantics, never local filesystem paths.
Versioned PNG responses carry a checksum ETag and one-year immutable cache policy.

