# Stage 9.2a — Storage Audit & Benchmarks

Status: implemented. This stage is strictly read-only and performs no migration, cleanup,
checkpoint or retention action.

Package baseline: `0.6.0`.

## Reproducible command

```powershell
uv run --frozen stratweb storage audit `
  --db C:\Users\<user>\StratWeb-data\faceit-spatial.duckdb `
  --output .runtime\storage-audit.json `
  --pretty
```

The database is opened with `read_only=True`. The command refuses to use the DuckDB file as
its JSON output, even when `--force` is supplied.

## Observed local database

Observation date: 2026-08-14. DuckDB: 1.5.4. Imported matches: 5.

| Metric | Observed |
|---|---:|
| File size | 1,557,409,792 bytes (about 1.45 GiB) |
| Used DuckDB blocks | 5,521 × 262,144 bytes |
| Free DuckDB blocks | 420 × 262,144 bytes |
| Tables / explicit secondary indexes | 65 / 67 |
| Exact rows across tables | 2,199,091 |
| Uncompressed JSON payload bytes | 1,479,879,853 |

`duckdb_tables().estimated_size` was materially stale for high-volume tables. For example,
it estimated 1,169,210 `spatial_snapshots`, while exact read-only counting found 753,000.
Reports therefore preserve both values and never present the catalog estimate as exact.

## Proven duplication

| Relationship | Source rows | Mirror rows | Equal payload rows | Duplicated JSON bytes |
|---|---:|---:|---:|---:|
| Spatial snapshot → query row | 753,000 | 753,000 | 753,000 | 677,367,517 |
| Bomb position → query row | 40,118 | 40,118 | 40,118 | 18,270,057 |

The mirror lookup tables are useful for their narrow indexed keys, but storing the complete
JSON payload in both the canonical and lookup row is unnecessary. `zone_assignments` is a
derived table, not an identical mirror: 481,740 rows cover about 64% of current Spatial
snapshots and contain zone results that cannot simply be discarded.

## Warm-cache query observations

Five iterations on the owner's current machine:

| Query shape | Median | P95 | Returned rows |
|---|---:|---:|---:|
| Recent matches | 1.335 ms | 1.418 ms | 5 |
| Spatial tick lookup | 0.883 ms | 0.948 ms | 10 |
| Spatial player path | 2.645 ms | 2.822 ms | 263 |
| Temporal round events | 4.582 ms | 5.727 ms | 242 |
| Zone round assignments | 54.941 ms | 61.449 ms | 4,600 |

These are machine/cache observations, not deterministic product metrics or service-level
guarantees.

## Scale warning

A deliberately naive current-file-size-per-match extrapolation produces approximately
6.23 GB for 20 matches, 31.15 GB for 100 and 155.74 GB for 500. It includes old runs, free
blocks and current duplication, so it is a risk signal rather than a capacity forecast.

## Stage 9.2b migration design

1. Back up the DuckDB file and verify the backup before schema mutation.
2. Create shadow slim lookup tables containing lookup keys and canonical snapshot IDs, but
   no JSON payload.
3. Backfill in bounded transactions and validate row count, key uniqueness and 100% mirror
   resolution for every compatible Spatial run.
4. Benchmark lookup-plus-key-join against the current mirror lookup. Define an explicit
   latency regression budget before switching reads.
5. Add repository compatibility routing by storage schema version; do not mix old and new
   layouts in one query result.
6. Switch reads only after parity tests pass. Keep old mirror tables for rollback during an
   acceptance window.
7. Audit every run/evidence dependency before proposing retention. Extra immutable runs are
   not automatically obsolete or safe to delete.
8. Evaluate Parquet only for immutable archived high-volume samples after the slim lookup
   experiment; do not move interactive lookup data based on file size alone.

No item in this plan authorizes deletion of the current mirror tables or user data.

## Verification

- 303 non-integration tests passed and 6 private-demo integration tests were deselected;
- formatting and lint passed for 235 files;
- strict typing passed for 187 source files;
- full audit preserved the production DuckDB file size and modification timestamp;
- package import, wheel `0.6.0` build, isolated wheel installation/import and Compose
  validation passed.

## DuckDB references

- [PRAGMA database_size and storage_info](https://duckdb.org/docs/stable/configuration/pragmas)
- [duckdb_tables and duckdb_indexes metadata functions](https://duckdb.org/docs/current/sql/meta/duckdb_table_functions)
- [EXPLAIN ANALYZE profiling](https://duckdb.org/docs/current/guides/meta/explain_analyze)
