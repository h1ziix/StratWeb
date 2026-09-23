# StratWeb Release Checklist

This checklist creates a recoverable local release. It does not publish source, images,
containers or Python packages to an external service.

## Before the release

1. Store the DuckDB file and retained demos outside the repository and synced folders.
2. Back up the source tree and Git history to a different directory or disk.
3. Confirm that `.env`, `.dem`, `.duckdb`, map assets, `tmp/` and `output/` are untracked.
4. Confirm that every intended change has a focused commit and the worktree is clean.
5. Run:

```powershell
uv lock --check
.\scripts\release_check.ps1
```

The gate validates frozen dependencies, formatting, lint, strict typing, non-integration
tests, JavaScript syntax, application import, isolated HTTP smoke for `/health` and `/ui`,
the Golden Corpus manifest contract, wheel creation and Docker Compose syntax. Golden Corpus
data readiness is a separate strict gate because private demos and analyst labels are intentionally
unavailable in ordinary source CI. A successful manifest validation does not mean real-data
acceptance has passed.

For Product Truth releases also verify that the library consumes the explicit readiness view
contract (`status`, `severity`, `reasons`, `missing_layers`, `next_action`) and never derives a
positive badge from `warning_count`. A small-sample recommendation must retain its reliability
limitation. A blocked finding and a blocked Golden Corpus must not be presented as accepted.

For Import & Database Reliability releases also verify deterministic concurrency coverage,
CAS-protected terminal states, rollback of batch registration, restart recovery and filesystem
cleanup ownership. Partial batch success must never be labelled full success.

## Release identity

- package version must agree between `pyproject.toml` and `stratweb.__version__`;
- tag format is `vMAJOR.MINOR.PATCH`;
- schema/rule versions are not inferred from the package version;
- a tag is created only after the quality gate passes on a clean worktree;
- source is not pushed or published without an explicit owner instruction.

## Recovery

Verify a Git bundle before relying on it:

```powershell
git bundle verify C:\path\to\stratweb.bundle
```

Restore the history into a new directory:

```powershell
git clone C:\path\to\stratweb.bundle StratWeb-restored
```

Restore runtime data separately. Source recovery does not restore DuckDB, uploaded demos
or proprietary map overview assets.

## Public-release blockers

- choose and review a project license;
- complete third-party dependency and asset license review;
- do not distribute Valve radar assets without permission;
- do not expose the current unauthenticated application to the public internet.
