# Opponent Workspace Model

Status: Stage 8.1 contract, version `1.0.0`.

## Purpose

An opponent workspace defines which physical team from each completed demo belongs to
one scouting scope. It does not compute tactics or findings. The persisted fact is a
user confirmation:

```text
(profile_id, match_id) -> physical team_id
```

Side is not identity. A selected physical team remains the same opponent through T/CT
switches.

## Persisted records

`opponent_profiles` stores the user-facing profile name and timestamps.
`opponent_match_selections` stores exactly one selected physical team per profile and
match. `selection_source=user_confirmed` is the only Stage 8.1 source.

No inferred roster link is persisted as user confirmation. Reassigning a match replaces
that match's selected physical team explicitly.

## Player identity

Identity rule: `steam_id_else_match_occurrence_v1`.

- A valid canonical Steam ID is the only automatic cross-match identity key.
- Missing Steam IDs receive
  `occurrence:{match_id}:{canonical_player_id}`.
- Equal nicknames never merge missing identities.
- Known/current names are presentation attributes, not identity evidence.
- Multiple occurrences with one Steam ID merge even if the nickname changed.

`core` means the Steam identity appeared in every currently selected match. `partial`
means it appeared in only a subset and may represent a substitute, roster change, or
missing observation. `unresolved_identity` means no cross-match identity assertion is
available.

## Roster overlap

Overlap rule: `candidate_known_steam_ids_v1`.

For every unselected match team:

```text
numerator   = candidate Steam IDs intersect confirmed profile Steam IDs
denominator = candidate players with a known Steam ID
frequency   = numerator / denominator
```

Strength is deterministic:

- `unscored`: the profile has no confirmed Steam IDs yet;
- `strong`: at least three shared Steam IDs and frequency at least `0.60`;
- `possible`: at least two shared Steam IDs;
- `weak`: every other measured result.

The strength is advisory. It never assigns a team, changes a profile, or becomes a
tactical conclusion. Missing candidate Steam IDs are displayed separately and excluded
from the denominator rather than treated as non-matches.

All profile mutations require a loopback client. Browser requests that include `Origin`
must also use a loopback origin, preventing an unrelated website from submitting forms
to the local application.

## Deletion and provenance

Deleting a canonical match removes its opponent selections transactionally but keeps the
profile. This prevents orphaned evidence scope. Deleting or renaming profiles is not
part of Stage 8.1.

The workspace JSON exposes:

- opponent schema `1.0.0`;
- identity rule `steam_id_else_match_occurrence_v1`;
- overlap rule `candidate_known_steam_ids_v1`.

## Non-goals

Stage 8.1 does not implement:

- automatic team confirmation;
- nickname or fuzzy-name identity;
- organization/team-name scraping;
- roster history from the internet;
- zones, tactics, findings, recommendations, reports or LLM calls.
