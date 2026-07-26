# Stage 7.6 — Density-independent Playback and Stable Labels

Status: implementation candidate complete; final product acceptance remains a manual
user decision.

Date: 2026-07-26

Validation fixture:

- real persisted FACEIT match
  `dba336bb-dc00-5974-bebe-3525d39a6ef4`;
- round 10;
- primary fight interval: ticks `67391–68093`;
- smoke/plant interval: ticks `69536–70158`;
- Chrome against the local FastAPI server and persisted DuckDB data.

Stage 7.6 is a corrective viewer/playback stage. It does not start Stage 8 and adds no
zones, tactical inference, coaching, recommendations or AI.

## User-visible failure

The Stage 7.5 compositor rewrite removed expensive SVG paint and DOM churn, but it did
not solve the user's main temporal complaint:

- movement slowed during firefights;
- shots, damage and utility made the slowdown more obvious;
- player nicknames repeatedly changed sides around their markers.

The first symptom was not primarily a remaining CSS/GPU problem. It was a playback-clock
model error. The second was a stateless label-layout policy.

## Root-cause evidence

### Sample-density-dependent time

The previous transition formula was:

```text
260 ms × clamp(tick_gap / 16, 0.45, 2.5) / speed
```

This gave a one-tick gap a 117-ms minimum at 1×. Under the new explicitly declared
presentation policy, one relative demo tick is 15.625 ms. A dense event region therefore
received extra wall time for each shot/damage/utility sample.

Round 10 contains 618 authoritative samples between ticks `66449–73169`. Of these,
197 are event-only samples and 230 adjacent gaps are seven ticks or less. The primary
fight interval contains 142 samples, including 133 event samples, 103 shots, 17 damage
events and four deaths. The old viewer took `21.114 s` to traverse ticks
`67391–68093`, while that tick span's Stage 7.6 presentation target is:

```text
(68093 - 67391) / 64 = 10.96875 s
```

The frame loop also advanced at most one authoritative sample and reset its local
transition origin after each advance. It discarded overshoot from a delayed frame,
which compounded the slowdown.

### Stateless nickname placement

The previous collision layout recomputed candidate anchors from current positions and
state on every sample. A round-10 audit recorded:

- 376 layout recomputations;
- 132 anchor changes;
- 74 left/right flips;
- up to 25 anchor changes and 18 flips for one participant.

The layout calculation itself was inexpensive. The defect was visual instability:
movement and nearby players changed the chosen candidate, so the nickname appeared to
orbit or swap sides.

### Refresh-rate aliasing and crossed-event visibility

The initial clock correction still skipped any rAF callback arriving less than 15 ms
after the previous rendered callback. That happened to approximate 60 updates/s on one
profile, but aliased common display cadences: about 75 Hz became 37.5 rendered updates/s,
and 144 Hz became 48. The resulting uneven motion was independent of renderer cost.

Removing per-sample delay also meant an exact event sample could be crossed between two
visual callbacks. Giving that sample extra demo time would reintroduce the original
slowdown. The required correction was therefore a bounded presentation lifetime separate
from playback time.

### Navigation-generation races

Two asynchronous races remained:

- filter-changing Back/Forward could restore controls for state B while retaining samples
  fetched under state A;
- a slow prefetch for A could complete after a far seek and repopulate the new target's
  buffer.

Both failures mixed individually valid evidence from different UI intents. Run IDs alone
could not detect them because A and B belonged to the same Spatial run.

## Implemented correction

### Absolute relative-demo-tick clock

`DemoTickClock` owns one monotonic playhead:

```text
playhead_tick =
  anchor_tick + (monotonic_now_ms - anchor_time_ms) * speed / 15.625
```

Every animation frame binary-searches the authoritative tick array for the current
left/right bracket. A delayed frame may cross multiple sample boundaries; they are counted
and the current bracket-left exact sample is committed. Elapsed overshoot is preserved.
Sample count and event density cannot change total duration for the same start tick, end
tick and speed.

The API publishes:

```json
{
  "basis": "relative_demo_ticks",
  "tick_duration_ms": 15.625,
  "presentation_ticks_per_second": 64.0,
  "rate_source": "presentation_policy:not_canonical_tickrate",
  "canonical_tickrate_used": false,
  "event_density_independent": true
}
```

This is a presentation policy, not a detected/canonical CS2 tickrate and not physical
match-time evidence.

### Native rAF cadence and transient event presentation

The manual 15-ms frame limiter was removed. The renderer now runs once for every callback
delivered by `requestAnimationFrame`; the application does not claim or enforce a fixed
monitor FPS.

When the absolute clock crosses one or more authoritative samples, their event markers
enter a deduplicated transient buffer for 120 ms of wall time. Thirty-two preallocated map
slots render current and transient markers without DOM allocation. The buffer:

- does not pause or slow the demo-tick clock;
- does not persist new evidence;
- does not assign duration to an individual event;
- uses deterministic ordering only for display and does not invent same-tick physical
  order.

### Buffering and prefetch

- Prefetch uses remaining buffered tick duration, selected speed and a 2.5-second
  wall-time reserve.
- Ordinary prefetch remains asynchronous and does not stop the playhead.
- A real underrun freezes the absolute clock at the required tick.
- Successful loading resumes from that same tick rather than creating a new transition
  delay.
- One browser frame can advance across and account for all authoritative sample
  boundaries crossed since the previous frame without serializing them into extra time.

### Navigation isolation

- Every asynchronous chunk is tagged with the active filter/navigation generation.
- Filter-changing Back/Forward cancels both request channels, clears old buffers and
  performs one fetch/commit for the restored state.
- Exact/far seek increments the generation, cancels stale prefetch and aborts an obsolete
  foreground request.
- A delayed A→B browser test retained B in the URL and controls, rendered B's five labels,
  and produced no console, page or request error.
- The active async navigation generation also owns loading UI: a new
  exact/filter/popstate intent cancels both clients and releases a stale loading overlay.
  A delayed far-fetch → cached-navigation test ended at index 87 with the loader hidden
  and no browser error.

### Payload and transport

Playback API schema is `1.2.0`.

- Players occur once under `samples[].players`.
- Event markers occur once under `samples[].events`.
- The duplicate top-level `player_samples` and `event_markers` collections were removed.
- Projectile and utility collections remain separate because their lifecycles are
  independent of player snapshots.
- FastAPI gzip is enabled for large responses.

The prior dense chunk was `2,084,855` bytes uncompressed and included duplicate player
and event data. Observed Stage 7.6 gzip responses for adjacent dense chunks were
approximately `88–109 KB`. This is an observed transport comparison, not a claim that
gzip alone produced the entire reduction: schema deduplication and compression both
contribute.

### Cached projectile trails

Projectile evidence series are converted to gap-aware segment plans when loaded or
evicted. Visual frames select only the required segment prefix instead of rescanning the
full projectile history. Stored parser samples remain the only trail evidence; no physics
or missing trajectory is invented.

### Stable roster-based nickname anchors

The page supplies the full persisted match roster independently of active team/player
filters. The renderer assigns a deterministic anchor once per participant and retains it
through:

- movement and nearby-player changes;
- alive/dead and C4/selection changes;
- team/player filtering;
- zoom and pan.

A genuinely unseen participant extends the plan without reassigning existing players.
The nickname still follows its player's position, but its direction relative to the
marker remains stable. This deliberately prioritizes temporal stability; it does not
promise a mathematically collision-free solution for every dense cluster.

## Before/after measurements

### Primary round-10 fight

Ticks `67391–68093`, delta 702 ticks:

| Measurement | Stage 7.5 | Stage 7.6 |
| --- | ---: | ---: |
| 1× presentation target | — | `10.969 s` |
| 1× observed wall time | `21.114 s` | approximately `11.005 s` |
| 1× error from Stage 7.6 target | +92.5% | approximately +0.3% |
| 4× presentation target | — | `2.742 s` |
| 4× observed wall time | approximately `5.363 s` | approximately `2.813 s` |
| Buffering transitions | — | 0 |
| Label anchor changes | 132 in round audit | 0 in validated fight |
| Label left/right flips | 74 in round audit | 0 in validated fight |

Polling resolution explains the small 4× overshoot: the observer saw tick `68106` after
the target tick. The clock did not pause or buffer.

### Smoke and plant interval

Ticks `69536–70158` were replayed at 4×:

- observed wall time: approximately `2.597 s`, with polling seeing tick `70193`;
- peak visible effects: 2;
- peak visible projectiles: 1;
- buffering transitions: 0;
- nickname anchor changes: 0;
- label-plan builds: 1;
- maximum renderer duration observed in this interval: approximately `1.30 ms`;
- console, page and request errors: 0.

### Complete round-10 control run

The complete round was replayed from tick `66449` through `73169` at 4× after the
integrated fix:

- deterministic presentation target: `26.250 s`;
- observed wall time: `26.266 s`;
- all 617 sample boundaries crossed and final index `617 / 617` reached;
- 275 renderable marker occurrences represented 214 unique evidence URLs;
- all 214 unique event URLs were observed during continuous playback;
- peak simultaneous transient map markers: 25 of 32 available slots;
- buffering transitions: 0;
- nickname anchor flips: 0;
- maximum rAF interval: `24.9 ms`; intervals above 34 ms: 0;
- maximum renderer duration: `1.20 ms`;
- browser long tasks: 0;
- console, page and request errors: 0.

### Frame and DOM observation

An additional full 1× main-fight observation recorded:

- wall time: approximately `11.005 s`;
- rAF interval p50/p95/p99: `4.2 / 4.3 / 4.3 ms` in uncapped headless Chrome;
- maximum rAF interval: `9.4 ms`;
- intervals above 34 ms: 0;
- browser long tasks: 0;
- label-anchor attribute mutations: 0;
- label child nodes added/removed during playback: 0/0;
- console, page and request errors: 0.

The approximately 240-Hz headless rAF cadence is not a monitor FPS claim. It is useful
only as evidence that this run contained no long frame gaps.

## Diagnostics contract

The Diagnostics surface separately exposes:

- clock basis, presentation rate and the explicit `not canonical tickrate` warning;
- total authoritative samples crossed by the clock;
- maximum samples crossed in one browser frame;
- buffering count and pending requests;
- label anchor-plan build count;
- unexpected label-anchor change count;
- existing render, DOM, projectile, utility and rejection metrics.

Expected stable round-10 result after a fresh page load:

- one initial label-plan build;
- zero unexpected anchor changes;
- crossed-sample count increasing through the fight;
- multi-sample catch-up allowed;
- zero buffering when the next chunk arrives within reserve.

## Evidence and compatibility guarantees

- `SpatialSnapshot` rows and exact Temporal ticks remain authoritative.
- Smooth interpolation is visual-only and is not returned by an evidence API.
- Exact mode and explicit navigation still resolve to stored samples.
- Playback schema `1.2.0` is distinct from Spatial schema/rule
  `1.2.0` / `1.3.0`.
- Removing duplicate response fields does not remove evidence; the canonical occurrence
  remains under each playback sample.
- Gzip changes wire encoding only.
- The presentation clock does not claim source tickrate or physical match time.
- The 120-ms transient buffer changes marker presentation lifetime only; it does not
  change evidence ticks or infer order inside a simultaneous tick.
- Stage 8 remains outside scope.

## Automated quality gates

Verified on 2026-07-26 after the integrated Stage 7.6 changes:

- Pytest: 211 passed, 6 skipped, no failures or warnings;
- mypy: success across 99 source files;
- Ruff: success for the complete repository via `ruff check .`;
- application import: success, title `StratWeb`;
- JavaScript syntax: success for all 11 shipped JavaScript files.

Captured `.stage7-manual` profiling/research artifacts are explicitly excluded from
version control and repository lint discovery; generated third-party evidence is not
rewritten by the project's formatter.

## Critical review and remaining limits

1. The 64 ticks/s value is a product presentation policy. A future physically timed mode
   must use separately proven source timing and must not silently reinterpret this field.
2. Stable nickname direction can permit local overlap in an unusually dense cluster.
   Preventing temporal flipping is the stronger current UX requirement; a future label
   solver must preserve the immutable anchor contract.
3. Browser timings are machine- and browser-dependent. The deterministic duration target
   is portable; absolute render-cost numbers are not.
4. The transport comparison combines schema deduplication and gzip and was taken from
   observed chunks with their real contents. It is not a synthetic compression benchmark.
5. Poll-based end detection slightly overstates short 4× timings.
6. The transient event pool is finite at 32 markers. The validated round peaked at 25
   and displayed all 214 unique renderable links, but a pathological burst above capacity
   can be bounded on the map. Exact navigation, Temporal UI and APIs retain the evidence.
7. The 120-ms TTL is wall-time presentation policy. It neither proves event duration nor
   physical order among events sharing a tick.
8. Fixed compositor pools and evidence rejection rules from Stage 7.5 remain in force.
9. Manual product acceptance has not been self-declared. The user must judge perceived
   motion and nickname readability in the actual viewer.

## Manual acceptance checklist

Use round 10 and replay at least:

1. ticks `67391–68093` at 1×;
2. the same fight at 4×;
3. ticks `69536–70158` with smoke and plant evidence;
4. the fight with all players, then team and individual filters;
5. the same player while moving, dying, carrying C4, zooming and panning;
6. Diagnostics while playback crosses a dense event group;
7. browser Back/Forward after changing a player/team filter;
8. a far seek while prefetch or another navigation request is still pending.

Accept only if:

- combat no longer plays substantially slower than quiet intervals for an equal tick
  span;
- there are no pauses unless `Buffering` is explicitly visible;
- nicknames do not swap sides or orbit around their player marker;
- short crossed combat markers remain visible without slowing playback;
- smoke/projectile layers remain responsive;
- restored filters, URL, labels and loading overlay all belong to the newest navigation;
- diagnostics show the explicit presentation-clock disclaimer;
- no browser error overlay or console/request failure appears.

## Artifacts

- [Stable round-10 labels](.stage7-manual/screenshots/stage7-6/round10-stable-labels.png)
- [Final round-10 playback frame](.stage7-manual/screenshots/stage7-6/round10-main-fight-final.png)
- [Compressed raw round-10 browser trace](.stage7-manual/profiles/stage7-6/round10-main-fight-trace.zip)
- [Final round-10 browser recording](.stage7-manual/videos/stage7-6/round10-main-fight-final.webm)

These artifacts support the implementation candidate. They do not replace the user's
manual acceptance.
