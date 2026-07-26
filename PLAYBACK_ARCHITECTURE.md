# Stage 7.2–7.6 — Product UI and Spatial Playback

## Scope and evidence boundary

Stage 7.2 is a presentation and query productization layer. It does not add tactical
analytics, zones, map control, rotations, clustering, recommendations or AI.

`SpatialSnapshot` stored for an authoritative tick remains the only evidence position.
`GET /api/spatial/{match}/rounds/{round}/playback` schema `1.2.0` returns bounded
collections of these stored samples and explicitly reports:

- `evidence_semantics=authoritative_spatial_samples`;
- `visual_interpolation_included=false`;
- the pinned Spatial and Temporal run IDs;
- authoritative sample indexes and ticks;
- an explicit presentation-clock policy;
- original availability and warnings.

Visual interpolation exists only in `static/js/map-renderer.js`. It is never persisted,
never added to the tick list and never returned by an evidence API. Exact mode disables it.
Previous/Next, scrubber release, event jumps and Temporal links resolve to a stored sample.

## Problems found in the Stage 7.1 UI

The previous viewer used a 300 ms `setInterval`, fetched one tick at a time and rebuilt the
complete SVG plus player and event cards after every response. It had no prefetch, no
animation-frame render loop, no visual interpolation and replaced all URL query parameters
with only `tick`. At most 3.33 sample transitions per second were possible before network
latency. The measured warm exact-tick endpoint averaged about 186 ms on the validation
machine. Player labels used one fixed offset and collided near dense spawns.

The other pages used separate embedded CSS blocks, exposed UUIDs as primary headings and
required a UUID on the home page. Technical run details competed with match information.

## Frontend structure

```text
src/stratweb/web/
├── routers/product.py
├── view_models/product.py
├── templates/
│   ├── base.html
│   ├── errors/page.html
│   ├── matches/{library,overview,diagnostics,job}.html
│   └── spatial/{explorer,path}.html
└── static/
    ├── css/{tokens,layout,components,spatial-viewer}.css
    └── js/{api-client,buffer-ranges,label-layout,url-state,map-renderer,spatial-player,...}.js
```

Jinja autoescape is enabled centrally. Embedded JSON escapes `<`, `>` and `&`. Demo-derived
names are assigned with `textContent` in dynamic UI. No Node build pipeline or SPA framework
is required.

## Playback state machine

```text
loading chunk ──success──> paused/exact ──Play──> playing
      │                         ▲                  │
      └──failure──> error       │                  ├── rAF visual frames
                                │                  ├── exact sample boundary
 event/scrub/prev/next ─────────┘                  ├── prefetch near buffer end
                                                   ├── end/error ──> paused/exact
                                                   └── underrun ──> buffering/frozen
                                                                      │
                                                        data available└──> playing
```

The initial 64-sample chunk is embedded in the page. Later chunks are fetched before the
buffer edge. Scrubber jumps request a bounded chunk around the selected index. A generation
token and `AbortController` discard stale or differently filtered requests. Filter-changing
Back/Forward restores the target controls, clears the previous generation's evidence and
performs one fetch/commit for the new state. Exact/far navigation cancels stale prefetch
before loading its target. Buffered ranges are merged, and time-aware prefetch starts once
at the contiguous range edge instead of launching overlapping requests. The trigger uses
the remaining tick duration, current speed and a wall-time reserve, so 4× playback asks
earlier than 1×. Every chunk is rejected if its Spatial or Temporal run differs from the
page-pinned IDs. Round, tick, filters, mode and pinned run survive URL navigation and
browser BFCache.

## Absolute presentation clock

Stage 7.6 supersedes the former `260 ms per sample transition` policy. That policy made
event-heavy fights slower because shots, damage and utility introduced more authoritative
samples. It also advanced at most one sample per animation frame and reset the transition
origin, losing elapsed overshoot.

The current clock owns one absolute monotonic playhead:

```text
playhead_tick =
  anchor_tick + (monotonic_now_ms - anchor_time_ms) * speed / 15.625
```

The configured policy is 64 presentation ticks/s (`15.625 ms/tick`). API clock metadata
states:

- `basis=relative_demo_ticks`;
- `presentation_ticks_per_second=64.0`;
- `rate_source=presentation_policy:not_canonical_tickrate`;
- `canonical_tickrate_used=false`;
- `event_density_independent=true`.

This is deliberately **not** a detected tickrate and must not be presented as physical
match time. It provides a stable relative timeline until trustworthy source-rate evidence
is available. The `0.25×`, `0.5×`, `1×`, `2×` and `4×` controls scale this presentation
timeline.

Each animation frame binary-searches the authoritative tick array for the playhead's
left/right bracket. If a delayed frame crosses several samples, their boundaries are
counted and the current bracket-left exact sample is committed; wall time is not stretched
to replay a fabricated per-sample minimum. Events crossed between callbacks are retained
for 120 ms of wall time in a bounded transient buffer and rendered through 32 preallocated
map slots. The TTL does not extend the demo-tick timeline. Stable same-tick sorting is only
a presentation order and never claims physical ordering. On a genuine buffer underrun the
clock freezes at the required tick and resumes from exactly that anchor when the chunk
arrives.

The controller renders on every browser-delivered `requestAnimationFrame` callback. A
removed 15-ms guard aliased 75-Hz delivery to roughly 37.5 updates/s and 144-Hz delivery
to roughly 48 updates/s. The application no longer imposes a nominal 60-FPS gate; actual
cadence follows the browser/display scheduler.

Schema `1.2.0` removes transport duplication: player views occur only under
`samples[].players`, and event markers only under `samples[].events`. Projectile samples
and utility effects remain separate lifecycle collections. Large FastAPI responses use
gzip. Neither compaction nor compression changes evidence semantics.

## Interpolation eligibility

Two player positions may be blended only when both samples:

- belong to the same participant and round;
- move forward in authoritative tick order;
- report the player alive;
- have available, non-unreliable positions;
- contain map projections.

The renderer holds or snaps at the boundary when a participant disappears, appears, dies,
has unavailable/unreliable position or changes round. View direction is blended only when
both view-angle samples are available. Bomb and event markers are exact-sample UI only.

## Rendering and instrumentation

Each participant owns one fixed compositor slot. Animation frames update guarded
`transform`, direction, opacity and visibility properties; player/projectile/effect/event
pools do not allocate nodes during playback. Label layout, bomb marker and event ribbon
update only when authoritative evidence changes. Projectile trail gap segmentation is
cached when its evidence series changes instead of being recomputed from full history on
every frame.

The map event pool contains 32 slots for current and transient crossed markers. It is
intentionally finite. Overflow is presentation loss only; exact navigation, Temporal UI
and evidence APIs retain the underlying event.

Nickname placement uses a full persisted roster supplied independently of active
team/player filters. A deterministic anchor is assigned once per participant and remains
stable across movement, alive/dead/C4/selection changes, zoom and filtered subsets. This
prevents left/right flipping; it does not claim globally collision-free labels in every
dense cluster.

The Diagnostics drawer records DOM node count, HTTP fetch count, average renderer duration
and browser frames delayed by more than 34 ms. Stage 7.6 also reports total crossed
authoritative samples, maximum samples crossed in one frame, label-plan builds and
unexpected anchor changes. These are manual profiling signals, not CI claims about a
particular workstation. Once a chunk is buffered, advancing exact samples requires no
network request and local DOM selection is below the 100 ms product target.

## Product shell and local operations

`/ui` is a searchable/sortable match library. Match overview presents map, teams, proven
score where available, round strip, player totals, basic observed event counts and readable
data health. Raw IDs, versions, fingerprints, validation links and deletion are isolated in
Diagnostics.

Completed `.dem` upload is localhost-only. It validates extension, size and CS2 signature,
streams to a UUID internal filename, preserves the original filename as metadata and runs
the existing canonical → analytics → Temporal → Spatial services on one bounded local worker.
Jobs are intentionally process-local and do not survive restart; persisted completed runs do.

Manual measurements and the full FACEIT acceptance matrix are recorded in
[STAGE_7_2_ACCEPTANCE.md](STAGE_7_2_ACCEPTANCE.md). The superseding playback-clock and
label-stability measurements are in
[STAGE_7_6_ACCEPTANCE.md](STAGE_7_6_ACCEPTANCE.md).

## Remaining product debt before Stage 8

- Temporal details still use a compatibility bridge that renders existing evidence-safe HTML
  fragments inside the common Jinja shell; a future cleanup can convert every fragment into
  dedicated component templates without changing contracts.
- Import jobs are in-memory and single-process; interrupted jobs must be started again.
- Only carried C4 position is available from current Spatial evidence.
- Rotated official overview transforms remain unavailable.
- Stable nickname anchors intentionally prefer temporal consistency over solving every
  dense-cluster collision.
- The 120-ms event buffer and 32-slot pool are bounded presentation policy; pathological
  bursts above capacity remain available only through exact evidence surfaces.
- The 64 ticks/s clock is a presentation policy, not canonical demo tickrate evidence.
- Browser performance values must be re-profiled on each target machine.
- Final Stage 7.6 product acceptance requires the user's manual viewer check.

Stage 8 has not started.
