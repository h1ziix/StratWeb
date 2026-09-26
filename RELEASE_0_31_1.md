# StratWeb 0.31.1 — DuckDB initialization lock ordering

## Cause

`initialize()` acquired `_INITIALIZATION_LOCK` before entering a DuckDB connection, which
acquired `DuckDBWriteCoordinator`. The import pipeline already held the writer coordinator
when calling `initialize()`. Concurrent execution could therefore leave the initializer
waiting for the writer and the importer waiting for the initializer indefinitely.

## Fix

- Every initialization path, including cache hits, now takes the reentrant writer coordinator
  before `_INITIALIZATION_LOCK`. The writer remains held across the complete migration sequence,
  including checkpoints and fresh connections required between backfills and ART indexes.
- Import repository calls ensure the schema under that same coordinator. Nested initialization
  safely reenters the writer lock; entering a write section alone does not run migrations.
- Canonical reads wait for the coordinator before checking or opening the file. They do not
  initialize the schema or create a missing database.
- Schema cache entries use file identity (`st_dev`, `st_ino`, and Windows birth time when
  available) and the migration manifest. Ordinary writes/checkpoints changing `mtime` no longer
  invalidate schema readiness. One current manifest is cached per path, so an older repository
  cannot reuse a stale cache after a newer schema was installed.
- `initialize(force=True)` explicitly checks on-disk migration names, checksums and unknown
  versions. Use it after external schema/metadata edits; a process restart also revalidates.
  File replacement and manifest changes invalidate the cache automatically. Failed verification
  removes the cache entry. Automatic detection of arbitrary in-place external schema edits is
  not provided by the fast path.

## Reproduction and checks

`tests/persistence_concurrency_probe.py` holds the writer in an import thread, starts an
initializer and a reader, and waits for both to attempt the writer lock before continuing
the import. Events make the ordering reproducible without scheduling sleeps. Daemon threads
have one 15-second completion deadline; pytest launches the probe in a killable subprocess
with a 30-second timeout.

Both a new database and an existing migration-014 database are covered. The probe checks a
successful/idempotent import, the read result, preservation of existing match/event counts,
and all 34 migration records with their exact names and checksums. Separate regressions cover
file replacement, data-only mtime changes, changed manifests, checksum corruption, unknown
versions, transaction rollback and retry after migration failure.

The same probe executed with the original `initialize()` from Git HEAD reproduced
`Lock deadlock` at its 15-second deadline. The fixed implementation passed both scenarios.

Focused validation: **83 passed** across persistence, import jobs, batches and release integrity.

The full gate exposed an existing Windows checkout issue: Git converted the checksum-pinned
legacy JSON fixture from LF to CRLF. Restoring its original LF bytes recovered the existing
SHA-256 (`7df660ee829e27ba3ccc35a97648182a45a1fa78e7eefb0661ec21640beff9aa`). A scoped
`.gitattributes` rule now preserves those bytes. All 11 outcome-availability tests then passed.
The spatial migration repair test deliberately removes tables and migration records through a
direct DuckDB connection; it now requests `force=True` for this external schema edit. Its
migration-007–014 reconstruction check passes and preserves canonical and temporal rows.

Final local release gate: `./scripts/release_check.ps1 -AllowDirty` — **passed** on Windows,
Python 3.13.14. The non-integration suite finished with **466 passed, 6 deselected** in 543.35s.
Lockfile validation, frozen environment sync, dependency consistency, formatting (315 files),
Ruff lint, strict mypy (245 source files), JavaScript syntax (20 files), application import,
HTTP smoke (`/health: 200`, `/ui: 200`), Golden Corpus contract and Compose validation passed.
The six deselected tests require integration inputs; no real demo acceptance is claimed.

Wheel: `.runtime/release-check/dist/stratweb-0.31.1-py3-none-any.whl`.

SHA-256: `7ceb991c9ae37e99f276c96f62dc80b2f44b03a4eb2c9fc676f731c427162c69`.

## Scope

No new database migration is required. This release changes in-process coordination and schema
cache behavior; it does not add cross-process write serialization. Golden Corpus product
acceptance remains blocked by the existing lack of confirmed matches and analyst labels.
