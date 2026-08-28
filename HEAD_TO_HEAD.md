# Head-to-Head: «Мы против них»

Head-to-Head compares evidence from an opponent profile with evidence from a separate profile
representing our own team. Both profiles use the existing user-confirmed physical-team selection:
there is no nickname matching, roster guessing or hidden external data source.

## Product workflow

1. Create an ordinary profile for the opponent and select the opponent's physical team in its
   completed matches.
2. Create another profile for our team, add our completed demos and select our physical team.
3. Compute Tactical V2 for both profiles.
4. Open the opponent workspace, choose **Мы против них**, select our profile and compute.

The page displays one card per compatible matchup, the exact numerator and denominator from both
teams, a tactical interpretation, a separate recommendation and evidence links to both corpora.

## Deterministic rules v1

Every comparison requires the same canonical map and opposite sides: opponent CT is paired only
with our T, and opponent T only with our CT. `UNKNOWN` sides are excluded.

### Opening pressure versus trade support

- opponent source: `entry_structure / opening_duel_success`;
- own-team source: `trade_structure / opening_death_traded`;
- risk score: `opponent opening frequency × (1 − our trade frequency)`.

This identifies a preparation risk when the opponent historically wins many first contacts while
our first deaths are historically traded infrequently.

### Opening pressure versus early spacing

- opponent source: `entry_structure / opening_duel_success`;
- own-team source: the earliest available `spacing_profile / checkpoint:<tick>`;
- risk score: `opponent opening frequency × our isolated-spacing frequency`.

This identifies an alignment between opponent opening success and our tendency to leave a player
without nearby support at the first versioned checkpoint.

Scores are classified as high at `≥ 0.45`, medium at `≥ 0.25`, otherwise low. These are versioned
product thresholds, not probabilities of winning or losing a future round.

## Reliability

The smaller match count of the two paired findings controls the displayed reliability:

- 15+ matches: high reliability;
- 8–14: stable trend;
- 3–7: tactical trend;
- 1–2: facts from individual games.

Small samples remain visible as hypotheses and are not blocked.

## Reproducibility

- Head-to-Head schema: `1.0.0`;
- rule version: `opposite_side_evidence_pairing_v1`;
- DuckDB migration: `030 head_to_head_comparisons`;
- each run pins the two Tactical V2 run IDs and fingerprints;
- each card embeds the two immutable source insights and their match/round/tick/event evidence;
- a changed Tactical V2 corpus requires a new comparison and never masquerades as the old run.

## Current limits

The comparison aligns separate historical samples; it does not prove causality, player intent or
that a behaviour will repeat. The two corpora may cover different dates and opponents.

The example “they push Banana on eco while we default slowly without a trade” requires typed
evidence that combines zone, economy class, timing and trade outcome in both corpora. Tactical V2
does not yet expose that complete joint fact, so Head-to-Head v1 deliberately avoids making this
claim. Adding an economy-conditioned zone-aggression fact is the next analytical extension, not a
presentation shortcut.
