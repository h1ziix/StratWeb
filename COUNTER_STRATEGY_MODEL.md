# Stage 8.7 — Deterministic Counter-Strategy Rules V1

Stage 8.7 converts only readiness-approved Stage 8.6 findings into reproducible
pre-match hypotheses. It is not an LLM layer and does not read a live match.

## Hard gate

The engine consumes one immutable Analysis run and one Stage 8.6.1 audit over that
exact run. A finding is eligible only when its readiness status is `ready`. A
`limited` or `blocked` finding is written to `skipped_findings` and can never produce
a recommendation.

Default readiness policy:

- 20 included opponent matches;
- at least two evidence matches for an individual finding;
- no upstream small-sample warning;
- source pattern is not partial;
- buy type is known.

Unknown values stay unknown. No rule substitutes a player, position, buy type, tick,
intent, or causal explanation.

## V1 rule families

- frequent proven plant outcome;
- recurring early/contact/CT starting-zone control;
- recurring opening killer;
- recurring opening victim;
- low conversion after an opening kill;
- recovery after an opening death;
- lost man advantage;
- untraded death.

Every rule has an explicit, fingerprinted threshold in `CounterStrategyConfig`.
Unsupported patterns and supported patterns below their threshold are recorded as
different skip reasons.

## Recommendation contract

`CounterStrategyRecommendation` keeps these fields separate:

- `observation`: copied unchanged from the source finding;
- `tactical_interpretation`: deterministic cautious interpretation;
- `recommendation`: an action to test before/during preparation, not a certainty;
- `avoid`: a separate warning against overreaction;
- original numerator, denominator, frequency, sample and Wilson confidence;
- the complete source evidence denominator;
- limitations, including explicit non-causality and future-behaviour warnings.

Statistics, confidence and evidence are copied, never recalculated by text rules.

## Reproducibility and persistence

One immutable `CounterStrategyRun` pins:

- source Analysis run ID/fingerprint/schema/rule;
- readiness audit ID/fingerprint/schema/rule and full readiness config;
- full strategy config and its SHA-256;
- strategy schema/rule versions;
- every recommendation and every skipped finding.

IDs are UUIDv5 over canonical content. Migration 022 stores runs, recommendations,
skips and exact recommendation-to-evidence links atomically. Repeated computation is
idempotent. Latest-compatible selection never mixes different Analysis runs.

## CLI and API

```powershell
stratweb strategies compute PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb strategies status PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb strategies show PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb strategies skipped PROFILE_ID --db .\data\stratweb.duckdb --pretty
```

JSON endpoints live under:

```text
/api/opponents/{profile_id}/analysis/strategies
```

Compute endpoints remain localhost-only. Stage 8.7 does not add a report UI; that is
Stage 8.8.

## Current acceptance limitation

The current real profile contains one match, so the correct V1 result is zero
published recommendations and explicit `finding_not_ready` records. Positive rule
paths are covered by deterministic synthetic tests. Real recommendation acceptance
requires a verified corpus of approximately 20 matches for one opponent.
