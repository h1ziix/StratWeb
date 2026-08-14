# StratWeb Per-Round Tactical Feature Model

## Scope

Stage 8.4 materializes deterministic facts inside one completed CS2 round. It does not
name tactics, compare matches, infer intent, generate recommendations, or use an LLM.
Stage 8.5 may aggregate these records only after pinning their input runs and rule version.

The feature run pins one compatible version of each input:

- canonical dataset fingerprint;
- Analytics fingerprint;
- Temporal run and fingerprint;
- Spatial run and fingerprint;
- Zone Assignment run and fingerprint;
- optional Economy run and fingerprint.

Rows from different input runs must never be combined in one feature run.

## Common record contract

Every `RoundFeature` stores:

- `match_id`, `round_id`, `round_number`, physical `team_id`, and `side`;
- `feature_type`, `availability`, schema/rule/config versions;
- a tick or inclusive tick range when known;
- zone identity only when resolved by the pinned Zone Assignment rules;
- the team's freeze-end `buy_type` when an Economy snapshot exists;
- canonical event IDs, Spatial snapshot IDs, and Economy snapshot IDs used as evidence;
- typed payload, limitations, and warnings.

`available` means the positive or negative statement in the payload is proven by the
declared evidence. `partial` means a useful fact exists but coverage or same-tick ordering
is incomplete. `unavailable` contains no payload. Unknown values are never replaced by
zero, a default site, a nearest zone, a five-player assumption, or UUID ordering.

## V1 feature rules

### Starting and checkpoint zone distribution

The starting checkpoint is the canonical `freeze_end_tick`. Additional checkpoints are
explicit tick offsets from freeze end. The nearest common sampled tick at or after the
target may be used only inside one configured Spatial sampling interval; the requested
and observed ticks are both stored. A player zone is resolved only through the pinned
Zone Assignment row. Partial player coverage produces a partial distribution.

The default offsets are 640, 1280, and 1920 ticks. They are ticks, not seconds. V1 does
not silently assume a 64/128 tickrate.

### First contact

Contact candidates are live enemy damage with positive health damage or, if no earlier
damage exists, a valid enemy death. Participants and physical teams come from the pinned
Temporal participant states. All candidates at the earliest tick are preserved. More
than one candidate at that tick makes intermediate ordering partial; event UUID is not
treated as physical order. One mirrored record is emitted for each involved team with
`initiator` or `receiver` role.

### Opening duel

The pinned Analytics opening-duel record is reused. StratWeb does not recompute it. If
Temporal 1.1 says the same-tick order is ambiguous, the feature is partial and records
that Analytics used a deterministic tie-break that is not a physical-order claim.

### First utility

V1 uses the first live canonical grenade observation per team, excluding lifecycle
`expired`. All observations at the earliest tick are preserved. A detonation/start event
does not prove the original throw tick, so the limitation is stored and availability is
partial unless the source lifecycle explicitly represents a throw.

### Early zone presence

A positive record is emitted for each distinct resolved zone entered by a team between
freeze end and the configured early-window tick. It proves presence only; missing zones
must not be interpreted as proven absence when Zone coverage is incomplete.

### Bomb route, site, plant timing, and post-plant roster

The route is the ordered, de-duplicated sequence of resolved zones for Spatial snapshots
whose `has_bomb=true`. Gaps make the route partial. Plant tick/player/site come from the
canonical plant event. If canonical site is absent, a bombsite zone may provide the zone
but must not be converted to A/B unless the authored zone ID/name explicitly identifies
that site. The post-plant roster is the Temporal post-tick-group state; ambiguous final
group state stays unavailable/partial.

### Lost man advantage

Pinned Analytics transitions are reused. A team loses advantage when its signed advantage
changes from its side to even or the opponent. Suicide, teamkill, and world-death effects
remain included exactly as defined in `ANALYTICS_DEFINITIONS.md`; the event classification
is stored. An ambiguous same-tick intermediate state makes this feature partial.

### Untraded death

A valid enemy death is untraded when the pinned Analytics run contains no `TradeEvent`
whose `original_kill_event_id` is that death. The Analytics trade window and its tick
resolution are pinned in the feature run. Same-tick ambiguous ordering is marked partial.

### First CT rotation, retake, and save/exit

V1 intentionally does not claim a general CT rotation without versioned map adjacency and
site-role semantics. A positive retake attempt may be recorded only when a planted bombsite
zone is resolved and a living CT who was outside that site at plant is later observed in
that exact site. A negative retake requires complete relevant zone coverage; otherwise it
is unavailable. Save/exit remains unavailable in V1 because surviving at round end alone
does not prove intent or carried-equipment preservation.

## Reproducibility and limitations

- Same canonical/input fingerprints and config produce the same feature fingerprint and IDs.
- Incomplete/warmup rounds are excluded by default and counted explicitly.
- A missing optional Economy run yields `buy_type=null`, never `unknown` by assumption.
- Zone coverage is coverage of authored polygons, not a probability of correctness.
- Correlation, tactical names, intent, causality, and recommendations are outside Stage 8.4.
