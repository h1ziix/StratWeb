# Stage 8.6.1 — Finding Readiness Gate

Stage 8.6.1 is a deterministic, read-only quality gate between evidence-backed
findings (Stage 8.6) and future counter-strategy rules (Stage 8.7). It does not
create tactical interpretations or recommendations.

## Default policy

- at least 20 included matches in the opponent corpus;
- a finding must cover at least 2 different matches;
- a source pattern marked `partial` blocks recommendation generation;
- unknown buy type blocks recommendation generation;
- the source finding's own small-sample warning blocks recommendation generation;
- a missing evidence tick is a visible limitation by default and can be promoted to
  a blocker with `require_all_evidence_ticks`.

The thresholds and strictness flags are part of `FindingReadinessConfig` and are
included in `configuration_hash` and `audit_fingerprint`. Unknown values stay
unknown; the gate never infers a buy type or tick.

## Result states

- `ready`: no blocker or limitation; eligible for Stage 8.7;
- `limited`: no blocker, but at least one explicit limitation; not eligible;
- `blocked`: at least one blocking reason; not eligible.

Every record is tied to one immutable `analysis_run_id`. The audit ID is a UUIDv5
derived from the source analysis fingerprint, the versioned rules, configuration,
and sorted finding results. Repeating the audit over the same input produces the
same identifiers and output.

The audit is deliberately derived rather than persisted. The source Analysis run
is already immutable, so the exact audit can be reproduced from its fingerprint
and the returned configuration. This avoids another storage layer before Stage
8.7 defines how a readiness run will be consumed.

## CLI and API

```powershell
python -m stratweb.cli readiness audit <profile-id> --db <database.duckdb> --summary-only --pretty
```

```text
GET /api/opponents/{profile_id}/analysis/readiness
```

Both surfaces accept explicit thresholds. API computation is read-only.

## Important interpretation

`stage_8_7_ready=false` does not mean the parsed match is invalid. It means that
the current evidence is not strong or complete enough for StratWeb to turn those
observations into pre-match advice under the selected policy.
