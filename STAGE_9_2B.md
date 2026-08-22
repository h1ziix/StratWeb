# Stage 9.2b — Storage Engine V2

Status: implemented and activated on the owner's five-match database. Package baseline:
`0.7.0`.

## Outcome

Storage V2 uses `spatial_snapshots` and `bomb_position_snapshots` as the only payload source.
Three ART indexes cover tick, player-path and bomb-tick lookup keys. New Spatial runs no longer
write the same JSON payload to the legacy query mirror.

Existing mirror rows are intentionally retained for the acceptance window. Consequently this
stage prevents new duplication but does not yet reclaim the roughly 695.6 MB measured in
Stage 9.2a.

## Why the Stage 9.2a proposal changed

The first real-data rehearsal used slim key tables joined to canonical payload. All 793,118
rows passed parity, but tick and path medians regressed to roughly 14–16 ms and exceeded the
explicit latency gate. V2 remained inactive.

The accepted design indexes keys on the canonical rows and removes the join:

| Query | Legacy mirror | Canonical V2 |
|---|---:|---:|
| Spatial tick | 0.607 ms | 0.675 ms |
| Player path | 3.992 ms | 4.245 ms |

These are five-iteration warm-cache observations on the owner's machine, not service-level
guarantees.

## Verified production migration

- DuckDB `v1.5.4`;
- backup created before V2 schema/index mutation;
- backup verified across 65 tables and 2,199,091 rows;
- backup SHA-256:
  `24c8579dd4876d7307cbb414688e9b38bbce171c4a7034c51bd437023f9cbbb5`;
- Spatial canonical keys: 753,000 / 753,000, zero missing or mismatched;
- bomb canonical keys: 40,118 / 40,118, zero missing or mismatched;
- active layout: `canonical_key_indexes_v2`;
- source DuckDB file was not compacted and stayed 1,557,409,792 bytes.

The backup file is external runtime data and is not committed to Git.

## Commands

```powershell
uv run --frozen stratweb storage status --db <database.duckdb> --pretty

uv run --frozen stratweb storage migrate-v2 `
  --db <database.duckdb> `
  --backup <new-backup.duckdb> `
  --output .runtime\storage-migration.json `
  --pretty --yes

uv run --frozen stratweb storage rollback-v1 `
  --db <database.duckdb> `
  --pretty --yes

uv run --frozen stratweb storage restore-backup `
  --backup <backup.duckdb> `
  --destination <new-restored.duckdb> `
  --pretty --yes
```

`migrate-v2` refuses an existing backup target and refuses to overwrite the database with its
JSON report. Activation requires both exact parity and the latency budget. `rollback-v1`
backfills any mirror rows missing after V2 writes, verifies payload equality and switches only
inside one transaction. `restore-backup` refuses an existing destination and verifies the
restored file table by table.

## Retention and Parquet decisions

- Original uploaded demos are owner evidence and are never automatically deleted.
- A newer analytical run does not make an older run deletion-safe; evidence and downstream run
  dependencies must be traversed first.
- Parquet is not used for interactive point lookups. It may be evaluated later for immutable,
  versioned archives with a manifest and restore test.
- Dropping legacy mirrors and compacting DuckDB require a separate owner-approved stage after
  the acceptance window. Stage 9.2b contains no such deletion.

## Recovery boundary

The verified backup is a complete DuckDB database produced with `COPY FROM DATABASE`. DuckDB
copies schema, constraints, indexes and data. The application can open the backup as V1, or a
future restore operation can copy it into a new destination. The source path is never used as
an output target.

## Verification

- 307 non-integration tests passed; 6 private-demo integration tests were deselected;
- formatting and lint passed for 240 files;
- strict typing passed for 191 source files;
- production V2 repository returned 10 canonical snapshots for the sampled real tick;
- package import, wheel `0.7.0` build and Compose validation passed.
