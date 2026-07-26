# Temporal Round State Model 1.1.0

Этот документ — normative specification для Stage 6 Temporal Round State Engine.
Независимая реализация, получившая тот же `CanonicalMatchDataset 1.1.0` и temporal
config, должна построить тот же ordered timeline, transitions, snapshots и fingerprint.

## Scope и source boundary

Temporal domain принимает только immutable typed canonical entities: rounds,
memberships, players, teams, kills, damages, shots, grenades и bomb events. Raw parser
rows, DuckDB records и analytics results не являются источником temporal truth.
Analytics 1.1.0 используется только для независимой consistency-проверки.

Positions, coordinates, paths, visibility, utility trajectories, economy, inventory,
tactics и strategy не входят в модель. Grenade coordinates намеренно не переносятся в
temporal events.

## Authoritative time

Tick — единственная обязательная и authoritative единица. `TemporalTime` содержит
tick, nullable seconds, conversion status/source и nullable tickrate. Seconds равны
`tick / tickrate` только при одном доказанном canonical tickrate. Без него seconds и
source равны `null`, status равен `unavailable`; 64 tick/s не предполагается.
Непустой conversion source обязан ссылаться на proven `canonical:*` evidence;
user-supplied/assumed tickrate отклоняется.

Конфликтующие tickrate sources отклоняют compute configuration error. Tickrate,
source и conversion rule входят в config hash и fingerprint.

## Round boundaries и phases

`start_tick`, `freeze_end_tick`, `end_tick`, `official_end_tick` и их provenance берутся
только из `CanonicalRound`. `live_start_tick` равен доказанному `freeze_end_tick`.
`effective_end_tick` равен `official_end_tick`, иначе `end_tick`. Fallback остаётся
явным через `end_source=fallback:*`.

Интервалы half-open, кроме конечного `ended`:

- `[start, freeze_end)` — `freeze_time`, если обе границы доказаны;
- `[freeze_end, end_tick)` — `live`;
- `[end_tick, official_end_tick)` — `post_round`, если границы различаются;
- `[effective_end_tick, +∞)` — `ended`;
- отсутствующие необходимые границы дают `unknown/partial`, а не выдуманный tick.

Negative/reversed boundaries не исправляются предположением: capability становится
`unresolved`, а structural contradiction — fatal validation issue.

## Unified event ordering

Все events сортируются по `(round_number, tick, priority, stable_event_id)`. Synthetic
boundary IDs детерминированно строятся через UUIDv5 от `round_id`.

Priority — serialization policy, а не утверждение о физическом micro-order:

1. phase/boundary start — 10;
2. damage — 20;
3. shot — 30;
4. grenade lifecycle — 40;
5. bomb plant — 50;
6. death — 60;
7. bomb defuse — 70;
8. bomb explode — 70;
9. round end/fallback end — 90;
10. official end — 100.

Events одного tick, для которых относительный порядок способен изменить state, получают
общий deterministic simultaneous-group ID и `simultaneous_ambiguous`. Stable event ID
делает serialization воспроизводимой, но не снимает ambiguity. В частности, несколько
deaths и несколько bomb state events одного tick (включая `plant+defuse` или
`defused+exploded`) не объявляются физически упорядоченными.

Snapshot на tick означает state после всех definitively ordered events `<= tick` и
содержит ambiguity flags для затронутых simultaneous groups. Before-event применяет
events, строго предшествующие event в canonical serialization; если event находится в
ambiguous group, snapshot явно помечен `simultaneous_event_order`. Ambiguity будущего
tick не переносится назад в более ранний snapshot.

## Participants и side/team identity

Physical team и side независимы. Side берётся из round `t_team_id/ct_team_id`, а не из
порядка team rows. Membership участвует в round, если его interval пересекает round
window и physical team совпадает с одним из round teams.

Priority evidence:

1. round-specific authoritative assignment (если появится в canonical contract);
2. canonical membership interval — `inferred_from_membership`;
3. consistent gameplay event identity — `event_observed`;
4. conflicting identity — `unresolved`;
5. отсутствие evidence — `not_participating`.

Модель не создаёт 5v5/10-player lineup автоматически. Membership participant начинает
round как `alive`; event-only participant — как `unknown`. Unknown event player ID может
быть сохранён как event-observed participant с partial coverage.

## Life state

Любая доказанная kill/death event переводит victim в `dead`, независимо от combat
classification: enemy, teamkill, suicide или world. Допустимы `alive -> dead` и
`unknown -> dead`; второе снижает coverage. `dead -> dead` — duplicate anomaly.
`dead -> alive` не создаётся без authoritative respawn event, которого canonical 1.1.0
не содержит.

Temporal death event сохраняет исходную `combat_death_classification` отдельно от
stateful `LifeTransition.death_classification`. Поэтому повторная смерть может быть
`repeated` как transition anomaly, не теряя исходный enemy/teamkill/suicide/world факт
для независимой Stage 5 сверки.

Death до live start сохраняется, но даёт warning/partial. Death после effective end
остаётся out-of-range temporal event и не меняет final state. Alive counts никогда не
clamp-ятся для сокрытия противоречия: negative/impossible transitions fatal.

## Bomb state machine

Canonical 1.1.0 доказывает только `planted`, `defused`, `exploded`. Поэтому initial
state — `unavailable`; carried/dropped/defusing не измышляются.

- `unavailable -> planted`;
- `planted -> defused`;
- `planted -> exploded`;
- `planted -> round_ended_before_resolution` на effective end;
- defuse/explode до plant, plant после terminal state и coexistence defuse+explode дают
  `unresolved` и conflict issue.

Actor/team/side/site_raw сохраняются как source evidence. `site_raw` не преобразуется в
A/B. Bomb capability остаётся partial из-за отсутствия carry/drop/defusing semantics,
даже когда terminal plant outcome доказан.

## Transitions и snapshots

Normalized transitions: `phase_changed`, `participant_observed`, `player_died`,
`bomb_planted`, `bomb_defused`, `bomb_exploded`, `round_ended`,
`ambiguity_detected`. Transition ID — UUIDv5 от round, tick, type, source event ID и
deterministic ordinal.

Snapshots вычисляются из immutable participant initial state и ordered transitions;
snapshot на каждый tick не сохраняется. Поддерживаются start, freeze-end, arbitrary,
before/after event и final. Snapshot содержит phase, participant/life groups, T/CT и
physical-team alive counts, bomb state, applied event IDs, capability metadata и
ambiguity flags.

## Availability и validation

Capabilities: tick timeline, seconds timeline, phases, participants, alive state, bomb
state и final state. Status: `available`, `partial`, `unavailable`, `unresolved`.
Reasons: missing tickrate/boundary/participants, conflicting events, out-of-range events,
incomplete round, unsupported bomb semantics и source conflict.

Fatal issues — duplicate IDs, nondeterministic ordering, impossible structural
transition, invalid phase overlap, доказанная physical-team/side mutation и
final-state mismatch. Conflicting identity sources без доказанного порядка дают
`unresolved` participant и warning, а не выдуманную mutation. Source gaps, unsupported
semantics, duplicate death and out-of-range source events are warning/partial unless
they create a structural contradiction.

Stage 5 cross-check compares opening event ID and man-advantage death stream/counts with
the same live-phase eligibility used by Stage 5. Pre-live temporal deaths remain partial
temporal evidence but are not falsely compared to a stream that excludes them. The
cross-check never changes temporal state; a mismatch is validation evidence, not
permission to copy analytics values.

## Fingerprint и persistence

`temporal_fingerprint` hashes canonical dataset fingerprint, schema/rule versions,
config, availability, ordered timelines/transitions, validation issues and derived
round-start/freeze-end/final milestone snapshots using canonical JSON. Runtime duration,
database path, timestamps, insertion order and machine data are excluded.

Migration 005 stores one `temporal_runs` row and normalized round/event/transition/
participant/life/bomb/validation rows. Arbitrary snapshots are replayed, not persisted
per tick. Same dataset/rule/config is idempotent; replacement never deletes canonical or
analytics runs.

## Temporal 1.1: simultaneous tick groups

A simultaneous group contains every in-range, state-affecting temporal event at one
round tick when at least two such events exist. Its UUIDv5 is derived from `round_id`
and tick. Stable event sorting is serialization only. It is not evidence of physical
ordering.

The group records separate `ordering_status`, `intermediate_state_status`, and
`final_state_status`, plus pre-state, a bounded set of possible intermediate states,
and a post-state only when that state is proven deterministic. Variant enumeration is
bounded at eight state effects; larger groups are classified conservatively.

Distinct-victim deaths commute for alive final state when all victims were alive in
the pre-state. Actor/victim cross-kills do not change that result. Duplicate victims,
already-dead victims, plant+defuse, and defuse+explode are conflicts or final
ambiguities; synthetic priority cannot resolve them.

`at_tick` and `after_tick_group` mean state after the complete tick group.
`before_tick_group` is the state before any event in the group. `before_event` and
`after_event` inside an ambiguous group return a typed ambiguous snapshot with
`ambiguous_same_tick_order` and possible states; they never expose UUID ordering as
physical truth. A deterministic post-group state remains available at later ticks.

Capabilities now separate `tick_group_state`, `per_event_state`,
`intermediate_ordering`, and `final_alive_state`. Local intermediate ambiguity makes
per-event state partial but does not make alive state unresolved. Only an ambiguous or
conflicting final group state propagates unresolved state within that round; another
round starts independently.

A death with no proven victim remains in the event stream with
`death_effect_status=unavailable`. It creates no life transition and cannot reduce an
alive count. No victim is inferred from attacker, weapon, damage, counts, ordering, or
Stage 5 aggregates.

Migration 006 adds `temporal_simultaneous_groups` and nullable
`temporal_events.death_effect_status`. Old 1.0 runs retain empty groups and explicit
`legacy_semantics` capability defaults; they are readable but are not reclassified.
