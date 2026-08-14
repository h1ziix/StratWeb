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
tests, application import, wheel creation and Docker Compose syntax.

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
