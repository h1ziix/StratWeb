# Stage 9.6.7 — Match Readiness Experience

## Goal

Turn the match diagnostics entry point into a player-facing quality page. A coach should be able
to understand in a few seconds whether the match can be reviewed and what, if anything, will be
missing from the visible experience.

## User experience

- The page is named **Demo quality / Качество демки** in match navigation.
- The shared locale contract is version `3.2.0`.
- The hero gives one answer: ready, ready with limitations, or waiting for processing.
- One primary button returns to the match review.
- Three cards describe 2D playback, round chronology and the match review in ordinary language.
- Only limitations that affect viewing appear at the first level.
- All counters, percentages, raw warnings, run IDs, versions and JSON links remain under one
  closed **Technical details** disclosure.
- Desktop and phone layouts share the same information hierarchy. Motion respects
  `prefers-reduced-motion`.

## Deterministic contract

`MatchReadinessView` is built from the existing `MatchOverviewView`, `MapOverview` and compatible
`ZoneAssignmentRunSummary`. It does not query new data, recalculate a match or infer missing
values. Status mapping and limitation wording are fixed in code and versioned as
`MATCH_READINESS_VIEW_VERSION = 1.0.0`.

## Non-goals

- No parser or normalization change.
- No analytics, confidence or recommendation change.
- No DuckDB migration.
- No API response change.
- No LLM or generated explanation.
