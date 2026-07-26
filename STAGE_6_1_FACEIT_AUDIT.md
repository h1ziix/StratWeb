# Stage 6.1 FACEIT audit

Date: 2026-07-18. Parser: `demoparser2==0.41.4`. No `parse_ticks` was used.

## 30-round persisted fixture

Match `3a778135-d1ea-5966-972a-65038b7c6036`, round 10, tick `70937` contains two
`player_death` events:

- `8edf7a3d-d46b-5222-8b32-8b57dd10f380`, victim
  `b9532ca4-d8e6-56ed-b577-121d2618f499`;
- `af521452-2f3c-5d4b-9415-34a419211593`, victim
  `c44d5967-bcf5-5753-b33c-8f1727eb21eb`.

The victims are distinct and alive before the group. The 1.1 CLI run classified it as
ambiguous ordering, ambiguous intermediate state, and deterministic final state. The
pre-state is 5T/5CT, the two bounded intermediate states are both 4T/5CT with a
different victim dead, and the post-state is 3T/5CT. The final round snapshot at tick
`74018` is available (0T/3CT). The match remains `alive_state=partial` only because of
two victimless deaths; it is not unresolved. `per_event_state=partial` correctly
localizes the round-10 ordering ambiguity.

Temporal fingerprint `e130f295a55e702e0d103e87a724eb6076536f632205caf4488ce2dd93bad0e1`
coexists with the preserved 1.0 fingerprint
`c568b3f0cfe2d1e7ab3631b266dd9e6d2024ac2521c67f408681d6a290e6d8b3`.

The
original `.dem` for this persisted fixture is no longer present locally, so exact raw
reinspection of rounds 26/27 is impossible and is recorded as an audit limitation.

Persisted canonical round 26 event
`cbff2a61-4902-5e85-aef9-ab63bfbd146f` at tick `177012` has attacker evidence but no
victim. Round 27 event `39ce03bf-4f39-54db-9bb7-72a2a9b9fa1a` at tick `183011` is a
`weapon=world` death with neither attacker nor victim. Canonical payload and the
nullable `kills.victim_player_id` SQL round-trip both preserve those nulls; the
temporal layer does not remove the identity.

## Available second FACEIT source fixture

The 17-round source demo
`1-c380734e-5abb-4a90-b836-9ea8a3d38c40-1-1.dem` was parsed with the production
normalization event/property request. Raw `player_death` rows at ticks `8042` and
`9425` both contain null `user_steamid`, `user_name`, and `user_team_name`; attacker
identity is also null and `weapon=world`. Thus an analogous victimless result already
exists in demoparser2 source output, before identity resolution, canonicalization, or
SQL mapping.

Conclusion: no StratWeb adapter/SQL victim loss was found. The 30-round exact raw
source cannot be proven retroactively because its demo is unavailable. Those events
remain typed local partial coverage; no victim is inferred.
