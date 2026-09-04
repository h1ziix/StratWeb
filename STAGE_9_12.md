# Stage 9.12 — Player/Team Stratbooks

## Product outcome

An opponent profile now declares what it represents:

- `team` — a confirmed physical team across completed demos;
- `player` — one confirmed Steam identity within those selected teams.

The distinction is persisted, visible in the library and enforced before rendering. Existing
profiles are migrated to `team`; StratWeb never guesses that a profile named after a nickname is
automatically a player.

## Stored subject contract

Migration 034 adds `subject_type`, `target_steam_id` and `target_player_name` to
`opponent_profiles`. `OpponentProfile` validates the invariant that team profiles have no player
target and that a configured player target has both a Steam ID and a name.

Selecting an individual target is an explicit localhost-only mutation. The selected Steam ID must
occur in every team already included in the personal corpus. Future match assignments are rejected
when that player is absent from the selected physical team.

## Subject-scoped report rules

Team stratbooks retain the existing team findings and deterministic counter-strategy rules.
Player stratbooks accept only `PlayerPatternValue` findings whose `steam_id` equals the persisted
target. Direct finding URLs apply the same guard. The JSON, print and PDF exporters apply the same
filter before serialisation.

This intentionally means that a personal report can be short. A missing personal fact is safer
than presenting a team pattern as the behaviour of one person.

## Personal movement chapter

`PlayerMovementStratbookService` reads the latest compatible immutable round-feature runs and
uses only `EARLY_ZONE_PRESENCE` rows containing the match-scoped player ID resolved from the target
Steam ID.

For each map, side and zone:

- numerator — observed target rounds containing that zone;
- denominator/sample size — rounds where any early zone for that target was actually observed;
- frequency — numerator divided by denominator;
- evidence — match, round, tick, feature ID, snapshot IDs and a direct smooth 2D link;
- source pins — every feature-run ID used by the chapter;
- limitations — positive presence does not prove absence elsewhere or future intent.

The chapter has a deterministic SHA-256 fingerprint over its versioned inputs and output.

## Export

Export schema `2.0.0` / rule `subject_scoped_stratbook_export_v1` includes the explicit subject,
filtered findings and optional personal movement chapter. Browser print, JSON download and the
ReportLab PDF all use the same projection.

## Current limits

- Personal movement V1 covers confirmed early zone presence, not a full route cluster.
- Profiles with missing Steam IDs cannot become stable cross-match player targets.
- Team-only pages such as Head-to-Head, Tactical V2 and Critical Mistakes are hidden from the
  personal workspace and reject direct requests for a player profile.
- Ollama rephrasing is intentionally disabled for personal mode until its prompt contract is
  subject-scoped end to end.
