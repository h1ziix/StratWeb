# Stage 7.3 acceptance record

Run date: 2026-07-18. Scope: multi-map assets, revision selection, calibration,
projection, persistence pinning, offline delivery, and UI integration only. Stage 8 was
not started.

## Implemented map/revision matrix

| Map | Current revision | Additional revision record | Validation |
|---|---|---|---|
| Mirage | `cs2-1.41.7.1-d263aa1118fb` | — | synthetic |
| Nuke | `cs2-1.41.7.1-d263aa1118fb` | upper/lower within revision | synthetic |
| Ancient | `cs2-1.41.7.1-d263aa1118fb` | — | real demo |
| Anubis | `cs2-1.41.7.1-d263aa1118fb` | — | synthetic |
| Dust II | `cs2-1.41.7.1-d263aa1118fb` | — | synthetic |
| Inferno | `cs2-1.41.7.1-d263aa1118fb` | — | synthetic |
| Cache | `cs2-1.41.7.1-d263aa1118fb` | `cs2-historical-cache-layout-unresolved` | current synthetic; historical unsupported |
| Overpass | `cs2-1.41.7.1-d263aa1118fb` | `cs2-historical-overpass-layout-unresolved` | current real demo; historical unsupported |

The two historical records intentionally carry no transform or image. They prevent a
historical demo from silently receiving the installed current radar, but they are not a
claim of historical rendering support. Matching historical assets and authoritative
revision evidence are still required.

Asset origin, build, license, dimensions, and all checksums are in
[MAP_ASSETS.md](MAP_ASSETS.md). Transform constants and their sources are in
[MAP_CALIBRATION.md](MAP_CALIBRATION.md). Detailed per-map limitations are in
[MAP_FIXTURE_MATRIX.md](MAP_FIXTURE_MATRIX.md).

## Real FACEIT Overpass result

- source demo SHA-256:
  `1d62bcbc0f4bc5d8ae1c4f4a28c71d1742cddbdde6074cfe929e06c8d43bb050`
- header map/patch: `de_overpass` / `14164`
- recomputed Spatial run: `0aff170c-e26d-542f-9f4c-644852e8f6c8`
- fingerprint: `bf60529d11fc071896bfd778f00a3d69afb8c5ea3f4dc767166bd44cd2205e78`
- Spatial schema/rule: `1.1.0` / `1.2.0`
- definition fingerprint:
  `5d5388370753000a0b0ef0e939ca2282bdd36ddfaa8222d40d7953569f29a223`
- status: `replaced`
- 30 rounds; 15,441 requested ticks; 154,410 player snapshots; 110,886 reliable
  alive positions; 7,730 carried-C4 snapshots; zero validation issues
- selected revision: `cs2-1.41.7.1-d263aa1118fb`
- selection: `unproven`, evidence `unmatched_patch_version:14164`
- calibration: `demo_validated`
- warnings retained: `map_revision_unproven`, `map_layout_may_be_incompatible`

All reliable alive and carried-C4 points audited during calibration remained inside the
overview. This demonstrates compatible coordinates for this fixture, but the demo build
does not prove identity with installed asset build 14171; the UI therefore displays the
warning prominently.

No old Cache demo was available. No result is fabricated. Cache current metadata passes
synthetic transform tests; the historical revision remains explicitly unavailable.

Ancient's pre-7.3 runs remain schema/rule 1.0/1.1 with `legacy_map_semantics=true`, null
revision/pin fields, and their original local legacy overview route. They were not
backfilled.

## HTTP and product checks

- `/api/maps` returned exactly eight canonical maps.
- `/api/spatial/{match_id}/map` returned the exact run pin, versioned local URL,
  `unproven` selection evidence, and warnings even after `/api/maps` warmed the asset
  cache.
- overview response: HTTP 200, exact 290,940 bytes, full SHA-256 ETag, and
  `Cache-Control: public, max-age=31536000, immutable`.
- unknown map and unknown revision asset return HTTP 404 with no fallback.
- Nuke transform at `z=-600` returned `level=lower`; the developer UI loaded both assets
  and exposed automatic/upper/lower/overlay selection.
- calibration UI is HTTP 404 unless developer mode is explicitly enabled.
- real Overpass round 1 rendered players, view directions, C4, authoritative playback,
  pinned revision/calibration, and the revision warning.

## Screenshots

All files are local test artifacts under `.stage7-manual/screenshots/stage7-3/`:

- `de_mirage.png`
- `de_nuke.png` and `de_nuke_lower.png`
- `de_ancient.png`
- `de_anubis.png`
- `de_dust2.png`
- `de_inferno.png`
- `de_cache.png`
- `de_overpass.png` and `de_overpass_round1.png`

Each screenshot was inspected. The eight official assets render with the expected
orientation; Nuke lower is visibly separate; the real Overpass page shows the warning and
authoritative player evidence.

## Final quality gates

| Gate | Result |
|---|---|
| `ruff format --check src tests scripts` | pass, 131 files formatted |
| `ruff check src tests scripts` | pass |
| `mypy --strict src` | pass, 97 source files |
| `pytest -m "not integration"` | 200 passed, 0 failed/error/skipped, 71.599 s |
| focused map/spatial tests | pass, 18 tests |
| real FACEIT CLI recompute | pass, 30 rounds, zero validation issues, 264.172 s |
| `pip check` | pass, no broken requirements |
| import smoke | pass, StratWeb `0.3.0` |
| JavaScript `node --check` | pass for all static modules |
| `docker compose config --quiet` | pass |
| isolated wheel build/install/static smoke | pass; package `0.3.0` includes map definitions, templates, CSS, and JS |

Final wheel is a local artifact with SHA-256
`fb52184910897bc23bb85948f7d7ae9ad32cbbcfe3b197f7d7432c9a4d2bc238`.

## Critical review and corrections

Three serious issues were found during self-review and fixed before acceptance:

1. A fingerprint-only overview cache allowed a public map request to erase run-specific
   selection status/evidence/warnings. Cache keys now include the complete immutable pin,
   with a regression test reproducing the request order.
2. Multiple authoritative selectors could disagree while the first match won. Registry
   selection now rejects conflicting patch/CRC/asset evidence as
   `map_revision_evidence_conflict`; ambiguous shared selectors are also rejected.
3. Clearing Z in the calibration UI serialized `z=null` and caused HTTP validation failure.
   Optional candidate fields are now omitted, so Nuke can return typed unknown level.

Remaining limitations are evidence gaps rather than hidden implementation behavior:

- matching real demos are absent for six maps;
- authoritative historical assets/CRCs/build mappings are absent for Cache and Overpass;
- source demo headers do not provide proven map bounds, spawn coordinates, or bomb-site
  coordinates;
- only carried C4 is available; dropped/planted C4 entity position remains unavailable;
- dead-pawn coordinates are retained but excluded from reliable path coverage.

No zones, named locations, map control, heatmaps, route clustering, execute/rotation
detection, tactical conclusions, coaching, recommendations, or AI analysis exist in this
stage.
