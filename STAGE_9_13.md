# Stage 9.13 — CT Setup & Anchors

## Result

For each map, Tactical V2 now summarizes the selected opponent team's observed CT setup:

- A anchor;
- B anchor;
- mid/sniper player;
- rotator.

Every role includes the player's confirmed identity, numerator, denominator, frequency, primary
zones and links to the exact match, round, tick range and spatial snapshots.

## Deterministic population

Only complete, non-warmup CT rounds with a known live-start tick are eligible. A player-round is
included in that player's denominator only when at least one alive, named-zone position exists
inside the versioned 1,280-tick early window. The UI calls this the first 20 seconds because the
current policy explicitly assumes 64 ticks per second; no hidden tick-rate estimate is made.

Site and mid membership uses an explicit, versioned map-zone table. Unknown and newly authored
zone IDs remain unclassified until that table is reviewed. They are never assigned from a fuzzy
substring or an LLM guess.

## Roles

- A/B anchor: the player with the highest share of observed early rounds in the corresponding
  site group.
- Mid/sniper: the player with the highest mid-group share; confirmed AWP frequency is a
  deterministic tie-breaker only.
- Rotator: the player with the highest share of rounds visiting at least two of A/B/mid in the
  early window, subject to the configured minimum count and frequency.

Roles are scored independently. The same player may appear in more than one role when the
observed positions genuinely overlap; the engine does not force a five-player lineup or invent a
second-best candidate.

The role label describes a historical positional repetition. It does not prove responsibility,
intent, a called setup or future behaviour.

## Identity and equipment

Players are merged across matches only by Steam ID. A missing Steam ID creates a match-scoped
occurrence and nicknames are never used as identity. Tactical source pins optionally include one
compatible economy run; AWP frequency is absent when its freeze-end weapon evidence is absent.

## Storage and UI

Each assignment is stored as a `ct_setup_role` Tactical V2 insight, so it inherits the immutable
run fingerprint and evidence tables. `CTSetupProfile` is reconstructed from that single pinned run
for both the Tactical V2 page and the one-page cheat sheet; runs are never mixed.
