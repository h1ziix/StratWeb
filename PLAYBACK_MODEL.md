# Playback Fidelity Model 1.2

Stage 7.4 changes presentation, not evidence. `SpatialSnapshot`, Temporal events, projectile
entity samples, and utility lifecycle events remain authoritative stored rows. Browser-created
positions are visual frames only and are never returned by the evidence API or persisted.

## Dense-fight slowdown root cause

Stage 7.4 removed network waits from the render callback, but its corrected
`260 * clamp(tick_gap / 16, 0.45, 2.5) / speed` transition formula was still
sample-driven. Exact shot, damage, death and utility ticks increased the number of
sample pairs. A one-tick gap therefore consumed at least 117 ms at 1× instead of the
15.625 ms required by the current presentation policy. A delayed browser frame could
advance at most one sample and restarted the transition origin, discarding elapsed
overshoot.

The real FACEIT round-10 interval `67391–68093` contains 142 samples, including 133
event samples. The old formula rendered it in `21.114 s` at 1×; its relative tick span
under the current presentation policy is `10.969 s`. This density coupling explains why
movement looked normal in quiet sections and slowed during firefights and smokes.

Stage 7.6 replaces the formula with an absolute monotonic demo-tick playhead. The render
loop binary-searches the authoritative tick array for the current bracket and may commit
the current bracket after crossing multiple sample boundaries in a delayed frame. It counts
those boundaries but never stretches wall time to satisfy a minimum duration per sample.

| Property | Stage 7.4/7.5 | Stage 7.6 |
|---|---:|---:|
| Clock basis | adjacent sample pair | absolute relative demo tick |
| Minimum duration for a one-tick gap at 1× | 117 ms | 15.625 ms |
| Sample boundaries crossed per frame | at most 1 | all elapsed boundaries accounted |
| Elapsed overshoot | discarded | preserved |
| Prefetch trigger | remaining sample ratio | remaining tick time / speed |
| Buffer underrun | typed, transition-relative | typed, absolute clock frozen |
| Event density changes total duration | yes | no |
| Evidence coordinates created in browser | no | no |

## Clock policy and evidence boundary

The playback API schema `1.2.0` publishes:

- `basis=relative_demo_ticks`;
- `tick_duration_ms=15.625`;
- `presentation_ticks_per_second=64.0`;
- `rate_source=presentation_policy:not_canonical_tickrate`;
- `canonical_tickrate_used=false`;
- `event_density_independent=true`.

This is a deterministic UI policy, not measured or canonical source tickrate and not a
claim about physical match time. At speed `s`, a tick span `Δtick` has presentation
duration `Δtick × 15.625 / s` milliseconds. A future physical-time mode requires
trustworthy source-rate evidence and a separate explicit contract.

Play, seek and speed changes re-anchor the monotonic clock without changing the selected
evidence tick. Pause freezes the current playhead. A delayed frame commits the exact
bracket-left state current at that time rather than forcing every crossed sample to be
assigned extra playback time. Events in crossed samples enter a 120-ms wall-time
presentation buffer backed by 32 fixed map slots. This makes short evidence visible
without extending demo-tick duration; deterministic same-tick display order is not
physical ordering. If the bracket's next sample is not buffered, `Buffering` freezes the
clock at that required tick; loading resumes from the same anchor instead of restarting
elapsed time.

The frame loop runs on every delivered `requestAnimationFrame`. The removed 15-ms guard
caused refresh-rate aliasing: 75-Hz delivery could become 37.5 rendered updates/s and
144-Hz delivery could become 48. There is no application-imposed FPS target; playback
uses the browser/display cadence while the absolute tick clock remains independent of it.

## Gap and motion policy

`PlaybackMotionPolicy` is a presentation safety policy, not a CS2 physics model:

- `normal`: at most 16 ticks and otherwise eligible;
- `large`: 17–64 ticks and otherwise eligible;
- `discontinuity`: larger gap, life-state/round/level change, suspicious distance, or map-bound
  transition;
- `unavailable`: a required participant or reliable position is missing.

The interpolation distance guards are 1024 planar world units and 512 vertical world units.
Derived speed is reported only as world-units-per-tick. It is not converted to units/second
because demo tickrate is not asserted by this layer.

Normal and eligible large gaps may visually interpolate x/y. Yaw follows the shortest angular
path. A death or other discontinuity holds the exact prior position until the next evidence tick
and then snaps to the typed new state; it never draws a straight route across the map.

Player presentation semantics are `exact`, `interpolated`, `held`, `unavailable`, `dead`, and
`absent`. They are available in SVG data attributes/tooltips and diagnostics, but normal analysis
mode is not flooded with developer labels.

## Buffer and rendering policy

- The active player/projectile/effect compositor nodes are persistent.
- A bounded sliding window retains samples within six chunk widths of its current or
  explicitly requested anchor.
- Prefetch uses remaining buffered tick duration, current speed and a 2.5-second wall-time
  reserve; ordinary prefetch never pauses the clock.
- Projectile trails use only stored parser samples and split at gaps over 16 ticks or an explicit
  terminal discontinuity warning.
- Projectile gap segments are cached when their evidence series changes; visual frames select
  a bounded prefix rather than rescanning complete history.
- Crossed event markers remain for 120 ms of wall time, are deduplicated by stable marker
  identity and are bounded to 32 pooled nodes; they never accumulate unbounded DOM.
- Out-of-map projections remain in JSON with `render_status=rejected`; they are never clamped or
  rendered as a fallback point.

The Diagnostics drawer reports current/next evidence tick, progress, tick gap, buffered count,
pending requests, FPS, held/unavailable players, frame counts/times, underruns, requests/minute,
active nodes, rejected entities, total crossed samples, maximum crossed samples per frame,
label-plan builds, and unexpected label-anchor changes.

## Transport and nickname stability

Schema `1.2.0` removes the duplicate top-level `player_samples` and `event_markers`
collections. Player views are carried only by `samples[].players`; event markers are
carried only by `samples[].events`. Projectile samples and utility effects remain separate
because they have independent lifecycles. FastAPI gzip is enabled for large payloads.
Compaction and compression do not change stored evidence or run isolation.

Every asynchronous chunk belongs to a navigation/filter generation. Filter-changing
Back/Forward cancels both request channels, clears the previous buffer and performs one
fetch/commit for the restored state. Exact/far seek increments the token, cancels stale
prefetch and cancels an obsolete foreground request. A late response from state A cannot
populate state B. The generation also owns the loading indicator, so a superseding
exact/filter/popstate intent cancels both clients and releases a stale overlay.

Nickname anchors are planned from the complete persisted roster before active team/player
filters are applied. Assignment is deterministic by participant/team identity and is retained
for the round. Movement, death, C4/selection state, zoom and filters cannot trigger a new
anchor side. A previously unseen participant extends the plan without moving existing labels.
This policy guarantees temporal stability, not perfect non-overlap in every dense cluster.

## Reproducible audit

Run the offline audit for one round:

```powershell
.\.venv\Scripts\python.exe scripts\audit_playback.py <match-id> 1 `
  --db .stage7-manual\faceit-spatial.duckdb
```

Add `--base-url http://127.0.0.1:8000` to measure bounded playback-chunk responses. The output
contains one row per authoritative sample plus aggregate gap/motion/projectile metrics. Runtime
render fields are intentionally collected in the browser because an offline database audit
cannot truthfully invent FPS, buffer depth, or dropped frames.

The Stage 7.6 real-demo measurements and manual product checklist are in
[STAGE_7_6_ACCEPTANCE.md](STAGE_7_6_ACCEPTANCE.md). Stage 8 is not started.
