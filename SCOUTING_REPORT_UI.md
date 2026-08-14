# Stage 8.8 — Evidence-First Scouting Report UI

Stage 8.8 is a read-only presentation layer over one pinned immutable Stage 8.7
Counter-Strategy run. It does not recompute statistics, change readiness, create a
recommendation, or use an LLM.

## Entry points

Open an opponent workspace and select **Open scouting report**, or navigate directly:

```text
/ui/opponents/{profile_id}/report
```

The read-only JSON representation is:

```text
/api/opponents/{profile_id}/report
```

The report JSON has `report_schema_version=1.0.0` and
`report_view_rule_version=scouting_report_view_v1`.

## Pinned source bundle

The application resolves exactly one Strategy run, then loads only its pinned Analysis
run, reproduces its stored readiness audit, loads every finding/recommendation/explicit
skip, and executes the Stage 8.7.1 acceptance audit. No rows from another run may be
shown on the page.

Every form, pagination link, JSON link, and finding detail link carries the resolved
`strategy_run_id`. The page exposes strategy/analysis/validation IDs and fingerprints
under **Reproducibility and versions**.

Default selection uses the latest compatible Strategy run. An explicit historical run
can be inspected with `?run_id=UUID`; it remains pinned while navigating.

## Sections

- acceptance status and confirmed-corpus coverage;
- deterministic data-quality checks and warnings;
- T-side and CT-side team tendencies;
- Steam-ID-backed individual tendencies;
- outcome/risk observations that may indicate recurring mistakes without claiming
  cause or intent;
- published recommended response and `avoid` text, kept separate from observation and
  tactical interpretation;
- explicit empty/blocked state when no recommendation passed readiness;
- exact immutable corpus manifest;
- evidence detail with numerator/denominator math, sample size, Wilson interval,
  limitations, and every denominator round linked to map and timeline.

Unknown values remain `unknown`/`unavailable`; the UI never fills them with a guessed
player, zone, tick, buy type, or tactical meaning.

## Filters

Filters support map, side, buy type, pattern type, minimum sample size, and minimum
Wilson conservative score. They select already materialized findings only. They never
recalculate a denominator or confidence value.

Selecting a subset of matches is intentionally absent in V1. Such a filter would change
the evidence population and requires a new Analysis run; hiding rows while retaining the
old statistics would be misleading.

The view is paginated at 30 findings by default (10–100 allowed). Published
recommendations are restricted to the source findings visible on the current page.

## Acceptance semantics

- `passed`: all deterministic integrity and product gates passed;
- `blocked`: internally consistent, but corpus/coverage/recommendation requirements are
  not met;
- `failed`: the report must not be trusted because an integrity invariant failed.

When status is `failed`, recommendation cards are suppressed even if corrupted stored
rows exist. Findings and failed checks remain visible for diagnosis.

The UI does not turn `blocked` into a green report. Current real data correctly shows
one confirmed match out of the required 20, 155 source findings, zero ready findings,
zero recommendations, 155 explicit skips, and 498 source-finding evidence references.

## Deliberate exclusions

Stage 8.8 does not add LLM wording, match-subset recomputation, live analysis, heatmaps,
or new tactics. Stable printable, JSON and PDF artifacts are implemented separately by
Stage 8.9 and preserve the pinned Stage 8.8 source bundle.
