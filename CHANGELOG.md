# Changelog

All notable StratWeb changes are recorded here. The project uses semantic versions for
release baselines; analytics, persistence and report contracts keep their own independent
schema and rule versions.

## [0.10.1] - 2026-08-23

### Changed

- Stage 9.6.1 replaces the Tactical V2 diagnostic table with a Russian product view.
- Adds representative overview cards, type/map/side filters and bounded pagination.
- Internal insight keys and run identifiers are removed from the primary reading flow.
- Capability coverage and per-observation limitations are presented in plain language.

### Safety

- Filtering and ordering are presentation-only; persisted ratios and evidence are never changed.
- The overview chooses the largest existing denominator per family and is explicitly not a ranking
  or recommendation.

## [0.10.0] - 2026-08-23

### Added

- Stage 9.5 Tactical Intelligence V2 with ten deterministic observation families.
- Source-pinned path, execute, utility, spacing, entry/trade, rotation, clutch/save and heatmap
  calculations.
- Immutable DuckDB migration 026 with normalized evidence lookup and dependency-aware cleanup.
- JSON API and Russian opponent inspection page.

### Safety

- Tactical intent, recommendation and causality are never inferred.
- Same-tick clutch state is evaluated only after the complete group.
- Flash/smoke effectiveness and unavailable save facts remain typed unavailable.
- Every observation retains numerator, denominator, frequency, sample size and source evidence.

## [0.9.0] - 2026-08-23

### Added

- Stage 9.4 immutable Statistical Trust runs and DuckDB migration 025.
- Deterministic match-cluster bootstrap intervals and leave-one-match-out stability.
- Exact one-sided match-cluster sign tests with global Benjamini–Hochberg FDR correction.
- Pre-registered practical-effect, cluster-count, interval, multiplicity and stability gates.
- Evidence-reliability ranking separate from observations and tactical recommendations.
- JSON API and Russian statistical-trust workspace for each opponent profile.

### Safety

- Multi-category patterns without a justified null hypothesis are `not_testable`.
- Patch and roster-period stability remain typed unavailable because match patch/time metadata is
  not proven by the current canonical schema.
- Existing findings and recommendations are not silently rewritten or re-ranked.
- Statistical support is explicitly not presented as causality or tactical value.

## [0.8.0] - 2026-08-23

### Added

- Stage 9.3 parser isolation: every native `demoparser2` call runs in a disposable child
  process and returns an atomically written, Pydantic-validated JSON artifact.
- Streaming upload SHA-256, early duplicate refusal, bounded admission and typed backpressure.
- Durable cancellation, retry checkpoints, worker PID/peak-memory diagnostics and reuse of
  hash/tick-matched canonical, economy and spatial artifacts.
- Parser timeout, working-set memory and free-disk guards with controlled error codes.

### Changed

- DuckDB writes remain in the single application process; parser children never open the
  database, preventing cross-process DuckDB writer conflicts.
- Graceful server shutdown stops parser children before final durable job-state writes.
- Import-job migration 024 stores source identity, worker/checkpoint and cancellation metadata.

### Safety

- Original upload names remain presentation metadata; files keep random internal names.
- Cancellation never invents partial evidence and retained demos can be retried explicitly.
- Stage 9.4 statistical work is not included.

## [0.7.0] - 2026-08-22

### Added

- Stage 9.2b verified DuckDB backup using `COPY FROM DATABASE` before any V2 mutation.
- Version-aware `canonical_key_indexes_v2` reads with three canonical lookup indexes.
- Deterministic key/payload parity, warm-cache latency gates and persisted migration status.
- `storage status`, `storage migrate-v2` and reversible `storage rollback-v1` commands.
- Migration and rollback tests covering backup refusal, payload parity and repository reads.

### Changed

- Active V2 writes store Spatial and bomb payload only in their canonical tables.
- A rehearsed slim-table join was rejected after exceeding the latency budget; direct canonical
  indexes matched legacy lookup performance and became the final design.
- Parquet remains an archive candidate only, not an interactive storage dependency.

### Safety

- Existing legacy mirror rows remain intact during the acceptance window.
- No mirror deletion, run retention or disk reclamation is performed in Stage 9.2b.
- Original uploaded demos are never classified as automatically deletable.

## [0.6.0] - 2026-08-14

### Added

- Stage 9.2a read-only DuckDB storage audit with exact rows, block attribution and JSON bytes.
- Mirror/derived relationship audits for Spatial, bomb-position and zone data.
- Bounded warm-cache benchmarks for five representative application query shapes.
- Explicit run-history inventory and limited 20/100/500-match growth projections.
- `stratweb storage audit` CLI with safe JSON output protection.

### Findings

- The five-match local database is about 1.45 GiB with 2,199,091 exact rows.
- Spatial and bomb lookup mirrors duplicate about 695.6 MB of identical JSON payload.
- Stage 9.2b should test slim key-only lookup tables before any destructive migration.

### Safety

- Stage 9.2a never mutates, checkpoints, compacts or deletes from the audited database.
- Additional immutable runs are inventoried but are not classified as deletion-safe.

## [0.5.0] - 2026-08-14

### Added

- Stage 9.1 versioned Golden Corpus manifest and external SHA-256 demo storage contract.
- Deterministic corpus readiness audit for opponent, map, source, edge-case and parser coverage.
- Analyst-labelled finding contracts with evidence and explicit indeterminate values.
- Deterministic TP/FP/TN/FN, precision, recall, false-positive-rate and F1 evaluation.
- `stratweb corpus validate` and `stratweb corpus evaluate` CLI commands.

### Known limitations

- The local manifest contains five FACEIT candidates, not 20 confirmed matches of one opponent.
- Valve, GOTV/HLTV, POV, damaged and incomplete fixtures still need real analyst-reviewed demos.
- Corpus readiness is intentionally `blocked` until those external data requirements are met.

## [0.4.0] - 2026-08-14

### Added

- deterministic economy, round-feature, cross-match pattern, finding, readiness and
  counter-strategy layers;
- evidence-first opponent report with stable JSON, printable HTML and PDF exports;
- Russian product presentation layer and versioned design system;
- `uv.lock`, Windows/Linux CI and a local release quality gate;
- a documented release and recovery procedure.

### Changed

- established commit `8351d5a` as the recoverable Stage 8.9 source baseline;
- bound Docker Compose to host loopback by default;
- made local Make targets use the frozen uv environment;
- ignored generated `output/`, `tmp/` and `.runtime/` artifacts.

### Known limitations

- the application is still a single-user, local-first product without authentication;
- the accepted opponent corpus is below the default 20-match gate;
- Valve/HLTV/GOTV corpus validation, storage compaction and worker isolation remain
  future hardening work;
- Valve radar assets are local-use inputs and are not included in the source release.

## [0.3.0] - 2026-07-27

- initial repository baseline through the opponent workspace and early Zone Engine work.
