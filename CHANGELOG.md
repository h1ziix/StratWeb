# Changelog

All notable StratWeb changes are recorded here. The project uses semantic versions for
release baselines; analytics, persistence and report contracts keep their own independent
schema and rule versions.

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
