# demoparser2 Economy Field Audit

Audit target: installed `demoparser2==0.41.4`.

## Verified Python surface

The installed typed stub and runtime introspection expose:

```text
DemoParser.parse_ticks(wanted_props, *, players=None, ticks=None, prop_states=None)
DemoParser.list_updated_fields()
DemoParser.parse_event(event_name, *, player=None, other=None)
DemoParser.parse_events(event_name, *, player=None, other=None)
```

Stage 8.3 uses `parse_ticks`; it does not invent a purchase-event API.

The upstream primary documentation lists these supported player/game-state names used
by the adapter:

| StratWeb request | documented sendtable/derived source |
|---|---|
| `current_equip_value` | `m_unCurrentEquipmentValue` |
| `round_start_equip_value` | `m_unRoundStartEquipmentValue` |
| `cash_spent_this_round` | `m_iCashSpentThisRound` |
| `balance` | `m_iAccount` |
| `inventory` | parser-derived names |
| `inventory_as_ids` | parser-derived item IDs |
| `armor_value` | `m_ArmorValue` |
| `has_helmet` | `m_bPawnHasHelmet` |
| `has_defuser` | `m_bPawnHasDefuser` |
| `team_num` | `m_iTeamNum` |
| `total_rounds_played` | `m_totalRoundsPlayed` |

Primary reference: <https://github.com/LaihoE/demoparser>.

## Runtime audit behavior

The adapter requests all fields only at canonical freeze-end ticks and persists the
actual returned columns. Omitted columns produce `missing_from_source`; present null or
invalid row values produce `unresolved`. Required identity columns are `tick`,
`steamid`, and `name`.

Automated adapter tests use a dataframe-shaped backend to lock the exact
`demoparser2==0.41.4` call and conversion contract.

## Corpus status

The working DuckDB contains imported FACEIT match rows, but after the project move the
corresponding retained upload file is absent. A real Stage 8.3 re-parse therefore cannot
be honestly reconstructed from existing spatial/event rows. The next uploaded demo is
retained by the current import job path and will execute this audit automatically.

Until that run is captured, real-demo field coverage across FACEIT/Valve/HLTV remains a
declared validation gap rather than a guessed success.
