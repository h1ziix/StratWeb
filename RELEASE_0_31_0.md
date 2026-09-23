# StratWeb 0.31.0 — Import & Database Reliability

This release hardens the existing local import pipeline without changing analytics semantics or
adding public deployment features.

## Import jobs

- Existing detailed stages now follow an explicit transition table.
- Repository updates can compare the expected stage, preventing stale workers from overwriting a
  cancellation or terminal result.
- Queued jobs resume after restart when the retained demo is present. Interrupted running jobs
  become retryable failures; pending cancellation becomes cancelled.
- User-visible failures are selected from stable messages and do not include raw tracebacks,
  parser stderr or local paths.

## DuckDB and idempotency

- A process-wide coordinator serializes writers by resolved database path, including independent
  import-manager instances, canonical match persistence and batch registration.
- Canonical dataset persistence keeps its existing explicit transaction and rollback behavior.
- Demo SHA-256 reservation checks jobs and saved matches in the same serialized transaction, so
  concurrent duplicate submissions produce one job plus one controlled duplicate response.

## Batch and cleanup policy

- Batch metadata and all item outcomes are registered in one transaction. Individual demo jobs
  remain independent, so one failed file does not roll back successful matches.
- The API and UI report succeeded, failed, skipped and cancelled outcomes separately. Mixed
  terminal outcomes are `partial`, never full success.
- A successful job removes only its own retained upload and UUID-named parser artifact directory.
  Retryable failure and cancellation retain the demo required for an explicit retry.

## Boundaries

- No authentication, tenant, analytics-engine or visual redesign work is included.
- Golden Corpus manifest validity does not mean product acceptance. Product acceptance remains
  **BLOCKED** because there are zero confirmed matches and no analyst labels.
- Docker and Compose are validated by CI; absence of a local Docker result must not be reported as
  a local pass.
