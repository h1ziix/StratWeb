# Stage 8.7.1 — Counter-Strategy Acceptance Audit

Stage 8.7.1 is a read-only, deterministic acceptance layer over one immutable
Stage 8.7 run. It does not create, rewrite, suppress, or persist recommendations.
Its purpose is to prove whether a run is safe to present in a future scouting
report and to explain why it is not ready.

## Inputs and identity

The audit pins exactly one `CounterStrategyRunSummary`, its exact source
`AnalysisRunSummary`, a readiness audit reproduced with the strategy run's stored
readiness configuration, every source finding, every recommendation, and every
explicit skip. Mixing rows from different runs is a validation failure.

`validation_schema_version=1.0.0` and
`validation_rule_version=counter_strategy_validation_v1` are part of the output.
The configuration, coverage, ordered checks, strategy fingerprint, and readiness
fingerprint produce a canonical SHA-256 fingerprint and UUIDv5 audit ID. Repeating
the audit over the same inputs produces the same result.

The audit is derived rather than stored because all inputs are already immutable.
This avoids another persistence hierarchy while retaining reproducibility.

## Status semantics

- `passed`: every integrity check passed and no configured product gate is open.
- `blocked`: data is internally valid, but the corpus/product gate is insufficient
  (for example 1/20 matches or zero publishable recommendations).
- `failed`: provenance, classification, statistics, evidence, or another invariant
  is inconsistent. A failed run must not be shown as accepted.

Failures take precedence over blockers. A warning alone does not change `passed`,
but remains visible in `checks` and `warnings`.

## Checks

The V1 audit verifies:

1. strategy, readiness, findings, and Analysis run provenance agree;
2. Analysis summary counts equal its immutable input manifest;
3. the pinned readiness audit and configuration reproduce exactly;
4. every finding is either recommended or explicitly skipped, exactly once;
5. the confirmed corpus reaches the configured minimum (20 by default);
6. T and CT findings are both represented when required;
7. unknown buy context remains visible as a warning;
8. at least one recommendation exists when required;
9. no recommendation bypassed readiness;
10. observation and all numerical statistics equal the source finding;
11. complete ordered evidence IDs equal the source finding;
12. every evidence match belongs to the included corpus;
13. no duplicate rule/scope/value recommendation signature exists;
14. generated text contains no prohibited deterministic-causality phrase.

Coverage reports confirmed matches, maps, sides, buy types, source/ready/skipped
counts, recommendations, evidence references, distinct evidence matches and rounds,
plus per-rule recommendation/evidence coverage.

## CLI and API

```powershell
stratweb strategies validate PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb strategies validate PROFILE_ID --minimum-corpus-matches 20 `
  --db .\data\stratweb.duckdb --pretty
```

Read-only JSON API:

```text
GET /api/opponents/{profile_id}/analysis/strategies/validation
```

Optional query parameters are `run_id`, `minimum_corpus_matches`,
`require_both_sides`, and `require_recommendations`.

## Current real-corpus result

The current confirmed opponent workspace contains one assigned match. The real
Stage 8.7 run has 155 source findings, zero readiness-approved findings, zero
recommendations, and 155 explicit skips. With the default acceptance configuration,
the correct result is `blocked`, not `passed`: `corpus_size` observes 1/20 and
`published_recommendations` observes 0/1. Integrity failures are absent.

The other imported matches are not silently assigned to this opponent. Team names or
nicknames are insufficient proof of identity. Full real-corpus acceptance therefore
requires explicit owner confirmation of approximately 20 matches and a later manual
tactical review of any recommendations that become publishable.

Stage 8.7.1 adds no UI, LLM, live functionality, or new recommendation rules.
