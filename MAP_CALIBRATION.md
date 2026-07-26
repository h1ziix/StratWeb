# Map calibration and validation

Calibration converts raw Source 2 world coordinates to an overview. It is presentation
metadata, not a zone model or tactical assertion. Accepted constants originate from the
pinned Valve overview metadata in [MAP_ASSETS.md](MAP_ASSETS.md); they are never estimated
from a screenshot.

## Current metadata

| Map | Origin X | Origin Y | Scale | Rotation metadata | Level policy |
|---|---:|---:|---:|---:|---|
| de_mirage | -3230 | 1713 | 5.0 | 0 | single |
| de_nuke | -3453 | 2887 | 7.0 | 0 | upper/lower, split Z -495 |
| de_ancient | -2953 | 2164 | 5.0 | 0 | single |
| de_anubis | -2796 | 3328 | 5.22 | 0 | single |
| de_dust2 | -2476 | 3239 | 4.4 | 90, baked into asset | single |
| de_inferno | -2087 | 3870 | 4.9 | 0 | single |
| de_cache | -2000 | 3250 | 5.5 | 0 | single |
| de_overpass | -4831 | 1781 | 5.2 | 0 | single |

## Acceptance levels

- `configured`: typed data exists, but projection has not passed the required checks.
- `synthetic_validated`: official metadata plus deterministic round-trip, bounds, origin,
  axis direction, and no-mirror tests pass.
- `demo_validated`: synthetic checks plus inspected real-demo player/C4 evidence pass.
- `unsupported`: no accepted transform/asset exists for this revision.

A map must not be promoted to `demo_validated` merely because its PNG renders. The current
evidence matrix is in [MAP_FIXTURE_MATRIX.md](MAP_FIXTURE_MATRIX.md).

## Developer workbench

Enable only on a local development server:

```powershell
$env:STRATWEB_MAP_DEVELOPER_MODE = "true"
python -m uvicorn stratweb.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/ui/maps/calibration`. The page can select a map/revision,
enter raw x/y/z, evaluate a candidate origin/scale/split through the backend pure
transform, collect several comparison points, and export candidate JSON. Nuke exposes
automatic upper/lower selection plus explicit upper, lower, and two-layer diagnostic
views.

The candidate endpoint is disabled outside developer mode. Candidate values live only in
the browser request and are never written to the registry or DuckDB. Exported JSON says
`accepted=false` and `persisted=false`; accepting it requires source review, several known
points, synthetic tests, and a real demo.

## Validation protocol

For a candidate revision:

1. pin asset and metadata checksums;
2. verify upper-left origin, inverse round-trip, X-right/Y-down orientation, and no mirror;
3. test center, corners, and intentional out-of-bounds points without clamp;
4. on a matching real demo, inspect both team spawn bands, several independent player
   paths, A/B-side event jumps, C4-carrier positions, labels, zoom/pan, and playback;
5. on Nuke, inspect upper, lower, transitions, missing Z, and the ambiguous split boundary;
6. record demo SHA-256 and observed sample counts in the definition and fixture matrix;
7. only then promote validation status and recompute the Spatial run.

Stage 7.3 intentionally does not attach named locations to known points. A radar pixel is
not an analytical zone.

## Real-demo evidence available now

Ancient was manually exercised in Stage 7.1 with demo SHA-256
`3957844f5eb46645b342718422775674c69c73957014068792caf43e9f0d56d0`.

Overpass uses demo SHA-256
`1d62bcbc0f4bc5d8ae1c4f4a28c71d1742cddbdde6074cfe929e06c8d43bb050`:
110,886 reliable alive positions over 30 rounds projected inside the overview, first-live
spawn bands aligned with the radar spawn annotations, and all 7,730 carried-C4 samples
remained inside. The demo header patch `14164` does not prove the installed `14171`
revision, so the run still reports revision-selection warnings despite the successful
coordinate audit.

