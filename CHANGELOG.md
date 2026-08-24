# Changelog

All notable StratWeb changes are recorded here. The project uses semantic versions for
release baselines; analytics, persistence and report contracts keep their own independent
schema and rule versions.

## [0.11.0] - 2026-08-24

### Added

- Stage 9.6.5 introduces a plain-language coach view for Tactical V2.
- Deterministic frequency bands explain results as rarely, sometimes, often or almost always.
- Every finding states sample reliability in ordinary language and links directly to its rounds.
- A primary match-plan action connects observations to the existing recommendation report.

### Changed

- The default list now shows one representative per finding family and only three key signals;
  selecting a family still reveals the complete persisted set.
- Attack/defence labels replace raw T/CT symbols in the reading layer.
- Exact percentages, ratios, counts, limitations, ticks and UUIDs moved behind explicit
  explanation or service-data disclosures.
- Evidence cards have one obvious primary action; alternate timeline and event tools are folded.
- Locale schema `3.0.0` rewrites the Tactical V2 Russian/English vocabulary for players and
  coaches.

### Safety

- Frequency bands are a pure deterministic projection over the persisted ratio.
- Exact numerator, denominator, percentage, sample size, limitations and source lineage remain
  available and unchanged.
- No analytical rule, Tactical schema, DuckDB table or recommendation was modified.

## [0.10.4] - 2026-08-24

### Added

- Stage 9.6.4 adds one local analyst note per exact Tactical V2 run and observation.
- DuckDB migration 027 stores notes separately from immutable evidence and statistics.
- Tactical calculation and note forms expose explicit submitting states.
- Missing or empty evidence receives dedicated Russian/English UI states.

### Changed

- Evidence actions, headings and note controls stack cleanly on phone-sized screens.
- Locale schema `2.2.0` covers analyst-note, loading, empty and error messages.

### Safety

- Notes never participate in analytical fingerprints, ratios, evidence or recommendations.
- Note mutation remains localhost- and same-origin-protected; deleting a Tactical run removes
  only notes pinned to that run.
- Missing evidence is presented as unavailable data and is never converted into a zero.

## [0.10.3] - 2026-08-24

### Added

- Stage 9.6.3 adds a Russian/English HTML evidence drill-down for every Tactical V2
  observation.
- Evidence cards navigate to the exact source match, round, tick, event detail, post-tick
  snapshot, exact-mode 2D map and round facts when the corresponding reference exists.
- Temporal tick groups and event rows now expose stable HTML anchors.

### Changed

- Tactical V2 persistence exposes one bounded insight lookup instead of loading the complete
  observation set for a detail page.
- Locale schema `2.1.0` includes all evidence navigation labels in both supported catalogs.

### Safety

- Every deep link pins the Temporal, Spatial or Feature run stored in the selected Tactical
  source lineage; latest-run data is never silently mixed into the page.
- Missing lineage or unavailable reference types remove the precise action instead of creating
  an inferred link.
- Evidence navigation is read-only and does not recalculate observations or mutate DuckDB.

## [0.10.2] - 2026-08-24

### Added

- Stage 9.6.2 introduces a versioned `2.0.0` locale contract for the shared shell and
  Tactical V2 product surface.
- Russian and English catalogs have identical stable keys and formatting placeholders.
- A page-level language selector persists a valid explicit choice in a same-site cookie.

### Changed

- Tactical card titles and descriptions are now locale-neutral presenter keys plus proven
  values instead of preformatted Russian strings.
- Status, neutral team labels and limitation messages render through the selected locale
  without changing canonical values or persisted analytical output.

### Safety

- Locale selection is presentation-only and cannot alter observations, ratios, evidence,
  fingerprints or JSON API responses.
- Unsupported locale values never poison the cookie and fall back deterministically.
- The release script resolves the installed package version instead of expecting obsolete
  `0.7.0` artifacts.
- Spanish and Chinese are not advertised until each catalog and surface passes the same
  no-mixed-language acceptance gate.

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
