# Stage 9.3 — Import Worker V2

Status: implemented. Package baseline: `0.8.0`. DuckDB migration: `024`.

## Outcome

An invalid, oversized or unusually expensive demo can fail its own import job without killing
the FastAPI server. Native `demoparser2==0.41.4` calls run in a child process. The application
process validates the resulting typed artifact and remains the only DuckDB writer.

## Data flow

```text
streamed .dem upload
  -> random internal filename + SHA-256 + size
  -> duplicate/backpressure gate
  -> durable import_jobs row
  -> isolated canonical parser -> atomic canonical.json
  -> canonical DuckDB import
  -> isolated economy parser -> atomic economy.json
  -> deterministic economy/analytics/temporal engines
  -> isolated spatial parser -> atomic spatial.json
  -> deterministic spatial/zones/features engines
  -> complete durable checkpoint
```

No parser child opens the database. No partial `.partial` artifact is accepted. Cached artifacts
must validate against their Pydantic model, source demo SHA-256 and requested tick tuple.

## Job and failure semantics

- Capacity is one active database pipeline plus `STRATWEB_IMPORT_QUEUE_SIZE` waiting jobs.
- Full admission returns HTTP 429 with `Retry-After`; the just-uploaded copy is removed.
- Duplicate SHA-256 returns HTTP 409 with the existing job/match reference when known.
- Cancellation is durable (`cancel_requested` -> `cancelled`) and retains the demo for retry.
- Abrupt restart converts unfinished rows to recoverable `import_interrupted` failures.
- Graceful shutdown signals parser children, waits for safe termination, then persists state.
- Retry uses the same `job_id`; only validated matching artifacts can be reused.

Progress percentages are coarse completed-stage indicators. They are not fabricated parser byte
progress. A database stage already inside a bounded transaction finishes before cancellation is
observed at the next safe boundary.

## Resource configuration

| Variable | Default | Meaning |
|---|---:|---|
| `STRATWEB_IMPORT_QUEUE_SIZE` | 4 | waiting jobs beyond the active writer |
| `STRATWEB_PARSER_TIMEOUT_SECONDS` | 1800 | limit per parser invocation |
| `STRATWEB_PARSER_MEMORY_LIMIT_BYTES` | 4294967296 | child working-set limit |
| `STRATWEB_IMPORT_MINIMUM_FREE_DISK_BYTES` | 2147483648 | free-space floor before parsing |
| `STRATWEB_IMPORT_CANCEL_GRACE_SECONDS` | 5 | terminate-to-kill grace period |

Memory observation uses process working set on Windows and resident memory on Linux. It is a
guardrail, not a full container/cgroup accounting boundary. The current single-user local product
does not provide fair scheduling between users or distributed workers.

## Persistence

Migration 024 extends `import_jobs` with demo hash/size, last completed stage, worker version/PID,
peak observed memory and cancellation/completion timestamps. Original upload names remain
separate from random internal `.dem` names. Pre-024 rows keep a null/unknown worker version rather
than being relabelled as V2. Uploaded demos and artifacts stay outside Git.

## Acceptance evidence

- Ruff: passed for `src` and `tests`.
- strict Mypy: passed for 193 source files.
- final full Pytest: 314 passed, 6 skipped.
- targeted Worker V2 tests cover migration round-trip, interrupted restart, retry, duplicate
  refusal, bounded queue, queued cancellation, artifact reuse, free-disk refusal and timeout
  process termination.
- Real retained FACEIT demo smoke (read-only database): canonical child returned Dust2/21 rounds;
  economy and spatial children each returned 30 samples for three requested freeze ticks; all
  artifacts reported the pinned `demoparser2==0.41.4` and the expected source SHA-256.

## Known limitations

- One import pipeline is intentional because DuckDB is a local embedded store.
- Cancellation of a deterministic DB stage is cooperative at the next stage boundary.
- Existing pre-024 job rows acquire SHA-256 on their next retry.
- Artifact cleanup/retention is not automated; original evidence is never deleted implicitly.
- Statistical Trust (Stage 9.4), distributed workers and multi-user auth are out of scope.
