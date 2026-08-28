# Utility ROI

Utility ROI is a deterministic Tactical V2 extension for completed CS2 demos. It answers three
practical questions without assigning player intent or using an LLM:

1. How often and for how long did a player's flash blind teammates?
2. How much utility was still carried immediately before a player died, and how often did a
   damaging grenade or flash have no directly recorded effect?
3. When did the team repeatedly deploy smokes, and how long was it until the first confirmed
   enemy damage after the smoke appeared?

## Verified parser inputs

The adapter targets the pinned `demoparser2==0.41.4` release. The implementation uses only
verified methods and fields:

- `parse_event("player_blind", player=..., other=...)` for attacker, victim,
  `blind_duration`, entity and tick;
- `parse_event(...)` source fields `game_time` and `round_start_time` for the event clock;
- `parse_ticks(["inventory", "inventory_as_ids"])` for inventory evidence;
- `parse_grenades(extra=...)` and the existing canonical grenade/effect pipeline for projectile
  identity and timing.

The parser header is not treated as a reliable tick-rate source. Smoke timing therefore uses the
event clock directly; it is not derived by assuming 64 or 128 ticks per second.

## Deterministic calculations

### Team flash

The eligible population is player-owned flash effects from the selected physical team. A blind
event is associated only by the versioned entity/tick rule. Per player and side, StratWeb stores:

- numerator: flash effects that produced at least one teammate blind;
- denominator and sample size: player-owned flash effects with blind-event coverage;
- frequency: `numerator / denominator`;
- total teammate blind seconds and enemy blind seconds reported by the parser;
- match, round, tick, event, projectile and effect references.

An enemy turning away may produce no blind event, so absence of a blind is not proof of a bad
flash.

### Utility retained on death

For each confirmed death of a selected-team player, the engine reads the latest available alive
spatial snapshot strictly before the death tick. The insight records the number of retained
utility items and a value estimate under price policy
`cs2_competitive_utility_prices_2026_08_v1`:

| Item | Estimate |
| --- | ---: |
| Flashbang | $200 |
| Smoke | $300 |
| HE | $300 |
| Molotov | $400 |
| Incendiary | $500 |
| Decoy | $50 |

Prices are versioned analytical configuration, not silently updated external data. A death with
no proven pre-death inventory snapshot is excluded rather than counted as zero.

### No directly recorded effect

HE and fire effects use the existing unique owner/weapon/time damage association; flashes use
associated enemy blind events. The result is deliberately named “no direct effect recorded”. It
does not prove that the grenade was wasted: it may have denied space, forced movement or made an
enemy turn. Smokes are excluded because the current offline data does not prove line-of-sight
denial.

### Smoke timing

Smoke appearance time is `game_time - round_start_time`, grouped into deterministic five-second
buckets. An optional contact window ends at the first confirmed enemy damage after that smoke.
This is a timing proxy, not a claim that the smoke caused an execute. Records without both source
clock fields are excluded rather than estimated.

## Versions and persistence

- canonical schema: `1.2.0`;
- normalization rule: `1.3.0`;
- spatial schema/rule: `1.3.0` / `1.4.0`;
- Tactical V2 schema/rule: `1.1.0` / `tactical_intelligence_v2.1.0`;
- Utility rules: `entity_tick_attacker_team_blind_v1`,
  `predeath_inventory_and_direct_effect_v1`, `source_clock_five_second_bucket_v1`;
- DuckDB migration: `029 utility_roi_evidence`.

Old runs remain identifiable by their stored versions and are not silently presented as Utility
ROI-capable. A demo must be reprocessed with the new canonical/spatial versions before the new
section can contain complete evidence.

## Product display

Open an opponent and choose the Tactical V2 report. The “Как команда использует гранаты” section
shows representative cards and evidence links. Empty or partial capability is preserved as such;
the presentation layer does not invent observations, values or tactical recommendations.
