# Automatic team-name inference

StratWeb infers presentation names only from completed-demo evidence. It does not call FACEIT,
HLTV or another network service and does not nominate an arbitrary roster member as captain.

## Verified parser source

The pinned `demoparser2==0.41.4` was checked against the retained FACEIT fixture. Requesting the
documented player property `team_clan_name` on `round_freeze_end` produced these real columns:

- `t_team_clan_name`;
- `ct_team_clan_name`;
- `t_team_name`;
- `ct_team_name`.

The clan-name values followed the physical rosters after the side switch. `parse_player_info()`
contained only `steamid`, `name` and `team_number`; it exposed no captain/leader flag. This is why
the algorithm never treats player order as captain evidence.

## Rule 1.0.0

1. Resolve physical teams and round side assignments first.
2. Take at most one clan-name observation per physical team and round, preferring freeze end.
3. Require one unique value with at least 60% of available round observations.
4. Reject generic side labels, numeric values and generated `team_123456` placeholders.
5. Accept `team_<nickname>` only when the suffix exactly matches a known nickname in that
   physical roster. The complete source value is retained for familiar FACEIT presentation.
6. If demo clan names are unavailable, accept only an explicit `[TAG]name` or `TAG | name`
   prefix shared by at least three players and a strict roster majority.
7. Otherwise leave the display name unknown and keep the neutral internal fallback.

Manual labels in `team_display_labels` retain priority over inferred canonical display names.
Removing a manual override reveals the inferred demo name again. The inference support and rule
version are persisted in the canonical team's warnings for reproducibility.
