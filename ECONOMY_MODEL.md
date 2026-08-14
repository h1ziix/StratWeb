# Economy and Equipment Context 1.0

Status: Stage 8.3 implementation, schema `1.0.0`, rule `freeze_end_team_buy_v1`.

## Purpose

The Economy layer records what each player and each physical team demonstrably had at
the canonical freeze-end tick. It exists so later analytics never compare pistol, eco,
force, semi and full-buy rounds as if their starting conditions were equivalent.

This layer records facts and a deterministic buy label. It does not produce tactical
findings, recommendations or LLM text.

## Source contract

`Demoparser2EconomyExtractor` uses the installed and pinned
`demoparser2==0.41.4` Python API:

```python
DemoParser.parse_ticks(wanted_props, ticks=freeze_end_ticks)
```

Requested properties are `current_equip_value`, `round_start_equip_value`,
`cash_spent_this_round`, `balance`, `inventory`, `inventory_as_ids`, `armor_value`,
`has_helmet`, `has_defuser`, `team_num` and `total_rounds_played`. Identity columns
`tick`, `steamid` and `name` are required from the parser result. The exact source
columns returned by a demo are persisted on the Economy run.

The extractor checks the `.dem` stamp and exact SHA-256 against the canonical match.
Unknown, omitted, null, non-finite and malformed values become typed unavailable
evidence. They are never replaced with zero.

## Evidence model

Every recorded value is an `EvidenceValue[T]` with:

- `value`, nullable;
- `availability`: `available`, `partial`, `missing_from_source`, `unresolved` or
  `not_applicable`;
- `source`;
- `population` and `available_count`;
- warnings.

Player snapshots preserve raw inventory names/IDs and explicit armor, helmet and kit
fields. `weapons` and `utility` are deterministic views of parser inventory names under
`inventory_names_v1`; no price is inferred from an inventory ID.

Team totals are complete only when every expected player value is available. A partial
sum is retained as `partial`, but it cannot drive a definitive buy classification when
complete equipment is required.

## Classification rule

Default policy (persisted in every run):

| Class | Required evidence |
|---|---|
| `pistol` | regulation, non-overtime score before the round totals 0 or 12 |
| `full` | complete team equipment value is at least 20,000 |
| `force` | below full threshold and proven team spend is at least 10,000 |
| `eco` | equipment value is at most 7,500 and proven spend is at most 5,000 |
| `semi` | equipment is between eco and full bands and no force rule matched |
| `unknown` | required evidence or eligibility is absent/conflicting |

These are versioned StratWeb product rules, not claims about Valve's own labels.
Thresholds are config fields and part of the run fingerprint. No locally reconstructed
item-price table is used: equipment/spend values come directly from the parser fields.

`force` is deliberately conservative. If low equipment exists without complete spend
evidence, the result is `unknown`, not `eco`.

## Eligibility and exclusions

Default computation excludes classification for:

- warmup rounds;
- incomplete rounds;
- rounds without a canonical freeze-end tick;
- unresolved physical T/CT team;
- roster sizes other than the configured five;
- incomplete team equipment value.

Excluded rows remain persisted for diagnostics with `buy_type=unknown` and explicit
`exclusion_reasons`.

## Persistence and selection

Migration 018 creates:

- `economy_runs` — immutable provenance, versions, config, capabilities and summary;
- `player_equipment_snapshots` — indexed identity columns plus full evidence JSON;
- `team_economy_snapshots` — indexed round/side/buy columns plus full evidence JSON.

Default queries select the latest run compatible with schema/rule 1.0. A page or query
never combines rows from multiple Economy runs. Canonical match deletion removes
Economy children first.

## Interfaces

CLI:

```powershell
stratweb economy compute MATCH_ID match.dem --db stratweb.duckdb --pretty
stratweb economy status MATCH_ID --db stratweb.duckdb --pretty
stratweb economy runs MATCH_ID --db stratweb.duckdb --pretty
stratweb economy teams MATCH_ID --buy-type full --side CT --db stratweb.duckdb
stratweb economy players MATCH_ID --round 1 --db stratweb.duckdb
```

Read-only API:

- `GET /api/economy/{match_id}/summary`
- `GET /api/economy/{match_id}/runs`
- `GET /api/economy/{match_id}/teams?buy_type=full&side=CT`
- `GET /api/economy/{match_id}/players?round=1`

New local upload jobs compute Economy immediately after canonical persistence. Existing
matches require the exact original `.dem`; derived database rows cannot recreate
freeze-end inventory that was never stored.

## Known limitations

- The label is team-side context, not a prediction of player intent.
- Equipment value cannot prove why a team bought or saved.
- Inventory naming can change with parser/game versions; the parser version is pinned.
- Missing/disconnected players reduce availability instead of being assumed to own
  nothing.
- Current saved matches whose original upload is absent cannot be backfilled.
