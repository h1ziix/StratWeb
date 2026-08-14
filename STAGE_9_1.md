# Stage 9.1 — Golden Corpus

Status: tooling implemented; real-corpus readiness blocked by missing reviewed data.

Package baseline: `0.5.0` (`v0.5.0`).

## Implemented

- strict, versioned Pydantic manifest for real demo fixtures;
- SHA-256-only external demo storage contract;
- explicit candidate/confirmed/rejected review lifecycle;
- target-opponent, source, map and edge-case coverage policy;
- parser name/version compatibility matrix;
- analyst finding labels with evidence and explicit indeterminate state;
- deterministic manifest fingerprint;
- file existence and byte-level SHA-256 verification;
- failure-isolated parser regression runner comparing every known canonical fact;
- deterministic TP/FP/TN/FN, precision, recall, false-positive-rate and F1 evaluation;
- CLI validation/evaluation and automated tests.

## Current candidate inventory

Five previously imported FACEIT matches are recorded without original filenames or raw demo
bytes: two Dust II, Mirage, Overpass and Ancient. They remain candidates because the product
owner has not confirmed that they belong to one opponent and no analyst finding labels exist.

This inventory must not be represented as a production-ready Golden Corpus. The acceptance
minimum is 20 explicitly confirmed matches of one opponent, plus Valve, GOTV/HLTV, POV and
failure/edge-case fixtures. Readiness therefore remains `blocked` by design.

## Verification

- 299 non-integration tests passed;
- 6 private-demo integration tests were explicitly deselected;
- formatting and lint passed for 231 files;
- strict typing passed for 184 source files;
- candidate manifest fingerprint:
  `322f01da818b8e921d51334a49bfed38996bec3a08311630a90d409639261790`;
- package import, wheel `0.5.0` build, isolated wheel installation/import and Compose
  validation passed.

## Non-goals

- no synthetic demo bytes masquerading as real fixtures;
- no automatic opponent identity inference;
- no private `.dem` files or credentials in Git;
- no LLM labelling or statistical computation;
- no Stage 9.2 storage redesign.
