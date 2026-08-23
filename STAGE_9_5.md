# Stage 9.5 — Tactical Intelligence V2

Status: implemented. Package baseline: `0.10.0`. DuckDB migration: `026`.

## Delivered

- pure deterministic engine with ten independent tactical observation families;
- exact checkpoint formation clustering and planted execute packages;
- typed HE/fire outcome association with flash/smoke refusal;
- spacing, opening/trade, post-contact CT transitions and post-group clutch analysis;
- Stage 8.4 save-exit consumption and alive-position world-grid heatmaps;
- immutable source-pinned runs, normalized evidence index and dependency-aware cascade;
- localhost-only compute API, summary/runs/insights/evidence endpoints;
- Russian inspection page linked from the opponent workspace.

## Real-data acceptance smoke

The confirmed `hanak1ri` selection was loaded from the production DuckDB. The exact compatible
Dust II lineage contains 17 eligible rounds and 39,655 selected-team position samples. Run
`1f652d46-2c75-5c4e-86d8-6f1445d54e9a` produced 191 deterministic observations with 674
round-level evidence references in about 1.6 seconds; the second compute returned `already_exists`
with fingerprint `e02095a96ca9b1be22329461c2e03346effac5ab6714e02bbe4d480a099f7cd5`:

- path clusters: 10, partial zone coverage;
- planted execute packages: 3 over 4 proven T-side plants;
- utility outcomes: 4 aggregate signals over 54 HE/fire effects, typed partial;
- spacing: 6 signals, 49/51 checkpoints covered;
- entry/trade: 2 + 2 signals, 17 openings and 5 opening-death trade opportunities;
- post-contact CT transitions: 57 edges across 12 covered rounds;
- clutch: 2 side-scoped signals over 5 proven 1v2+ opportunities;
- save: 0/17 covered rounds; the current Stage 8.4 save-exit facts are typed unavailable and are
  never interpreted as a negative save observation;
- heatmap: 105 occupied cells over 29,541 authoritative alive samples.

All 191 observations carry a small-corpus warning because the owner target remains 20 matches and
the confirmed profile currently contains one match.

## Acceptance checks

- synthetic fixture exercises all ten families, deterministic equality and non-empty evidence;
- DuckDB round-trip, idempotency, JSON API, rendered UI and match cascade are covered;
- migration history remains append-only through version 026;
- Ruff, strict mypy, package build/import and the complete pytest suite are release gates.

## Limitations

- no recommendation is created or changed;
- exact route clustering groups identical checkpoint signatures and does not claim semantic tactic
  equivalence;
- utility association is not causality;
- flash/smoke outcome effectiveness remains unavailable;
- heatmap frequency is sample share, not time;
- Stage 9.6 was not started.

See [TACTICAL_INTELLIGENCE_V2_MODEL.md](TACTICAL_INTELLIGENCE_V2_MODEL.md).
