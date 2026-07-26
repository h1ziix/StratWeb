# Stage 7.3 fixture and validation matrix

Large `.dem` files and Valve images are local, ignored fixtures. CI uses deterministic
model/coordinate fixtures for every map. `demo_validated` is reserved for maps where a
real demo was actually inspected.

| Map | Revisions represented | Versioned asset | Calibration source | Synthetic validation | Real-demo validation | Known limitation |
|---|---|---|---|---|---|---|
| de_mirage | current `cs2-1.41.7.1-d263aa1118fb` | upper, exact checksum | pinned Valve metadata | pass | not available | needs matching real demo before promotion |
| de_nuke | current `cs2-1.41.7.1-d263aa1118fb` | upper + lower, exact checksums | pinned Valve metadata, split Z -495 | pass, including upper/lower/unknown/boundary | not available | level policy needs real-demo transition audit |
| de_ancient | current `cs2-1.41.7.1-d263aa1118fb` | upper, exact checksum | pinned Valve metadata | pass | pass; SHA `3957844f…d56d0` | exact source demo is not committed |
| de_anubis | current `cs2-1.41.7.1-d263aa1118fb` | upper, exact checksum | pinned Valve metadata | pass | not available | needs matching real demo before promotion |
| de_dust2 | current `cs2-1.41.7.1-d263aa1118fb` | upper, exact checksum | pinned Valve metadata; rotate flag retained/baked | pass, orientation/no-mirror | not available | needs matching real demo before promotion |
| de_inferno | current `cs2-1.41.7.1-d263aa1118fb` | upper, exact checksum | pinned Valve metadata | pass | not available | historical revision asset not supplied |
| de_cache | current plus `cs2-historical-cache-layout-unresolved` | current upper; historical unavailable | current pinned Valve metadata | current pass; historical explicit unsupported | not available | no old Cache demo/asset; current fallback forbidden |
| de_overpass | current plus `cs2-historical-overpass-layout-unresolved` | current upper; historical unavailable | current pinned Valve metadata | current pass; historical explicit unsupported | pass on 30-round FACEIT demo; SHA `1d62bcbc…bb050` | demo patch 14164 does not prove installed 14171 revision; warning retained |

## Deterministic fixture coverage

`tests/test_maps.py` covers all explicit aliases, unknown/fuzzy rejection, deterministic
revision selection/manual override, all eight transforms, round-trip, bounds without
clamp, axis direction/no mirror, definition fingerprints, Nuke levels, immutable asset
routes/cache headers, API payloads without local paths, developer-mode gating, pin
persistence, registry changes, and legacy runs without backfill.

`tests/test_spatial_queries.py` verifies match-to-map query projection, exact pinned
definition use, player/C4/event rendering inputs, and preserved Spatial/Temporal run
scope. Existing playback tests continue to prove that browser interpolation never becomes
evidence and Temporal links remain exact.

## Optional local real-demo corpus

Real files remain outside Git. A developer may point the existing integration suite at a
finished demo with `STRATWEB_TEST_DEMO`; record its SHA-256 and authoritative header
metadata before changing any validation status. A fixture is unsuitable if the map/build
cannot be proved. No filesystem date may be used to select a revision.

## Honest acceptance status

All eight current assets and transforms are configured and synthetically validated.
Ancient and Overpass have real-demo evidence. Six maps still lack a matching local demo;
historical Cache and Overpass have typed revision records but no accepted historical
asset/calibration. Those gaps remain visible rather than being filled with current-radar
fallbacks or unverified constants.

