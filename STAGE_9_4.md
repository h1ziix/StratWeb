# Stage 9.4 — Statistical Trust

Status: implemented. Package baseline: `0.9.0`. DuckDB migration: `025`.

## Delivered

- immutable versioned trust runs tied to one exact Stage 8.5 pattern run;
- match-cluster bootstrap intervals with deterministic hash-derived seeds;
- exact one-sided match-cluster sign test;
- global Benjamini–Hochberg false-discovery-rate correction;
- effect, cluster-count, lower-bound, multiplicity and match-stability gates;
- typed support / not-supported / insufficient / not-testable decisions;
- evidence-reliability ranking that never modifies findings or recommendations;
- JSON summary/runs/assessment endpoints and a Russian opponent workspace page;
- dependency-aware cascade when a source pattern run is deleted.

## Real-data smoke

The latest retained `hanak1ri` pattern run was read directly from the production DuckDB in
read-only mode. All 160 persisted pattern payloads validated and produced a deterministic trust
run in memory:

- source patterns: 160;
- testable under pre-registered V1 nulls: 25;
- insufficient data: 25;
- not testable without an invented baseline: 135;
- supported: 0;
- patch/roster-period stability available: 0/0.

This is the expected honest outcome for the current five-match corpus split by map, side and buy
type. The smoke did not migrate or write the production database.

## API and UI

```text
POST /api/opponents/{profile_id}/statistical-trust/compute
GET  /api/opponents/{profile_id}/statistical-trust/summary
GET  /api/opponents/{profile_id}/statistical-trust/runs
GET  /api/opponents/{profile_id}/statistical-trust/assessments
GET  /ui/opponents/{profile_id}/statistical-trust
```

The compute endpoint is localhost-only. The workspace exposes match count, pooled frequency,
cluster interval, effect, adjusted q-value, leave-one-out spread, decision, rank and versioned
provenance.

## Limitations

- The current accepted corpus remains below the owner's 20-match target.
- V1 does not test arbitrary multi-category values against a data-derived uniform baseline.
- No patch or roster-period claim is emitted without canonical metadata.
- Bootstrap intervals and sign tests quantify repeatability; they do not prove causality.
- Existing Stage 8.6/8.7 artifacts are not silently changed. A future explicitly versioned
  downstream stage may consume `supported` assessments.
- Stage 9.5 Tactical Intelligence V2 was not started.

## Verification

- `pytest`: 322 passed, 6 skipped;
- Ruff format/check: passed;
- strict mypy: 199 source files passed;
- wheel and source distribution: built successfully;
- package import: `stratweb 0.9.0`;
- Docker Compose configuration: valid.
