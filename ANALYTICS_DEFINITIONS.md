# Analytics Definitions 1.1.0

Этот документ — normative specification для Gameplay Analytics Engine V1.
Все rules детерминированы, parser-independent и работают только с
`CanonicalMatchDataset 1.1.0` либо эквивалентным typed `MatchAnalyticsInput`.

## Population и ordering

Combat population состоит из complete, non-warmup rounds. Event учитывается,
если он assigned к такому round, имеет `phase=live`, валидные actor/team IDs,
когда они нужны definition. Events сортируются по `(tick, event_id)`.

Игрок участвует в round, если его typed membership interval пересекает
round window и membership team равен `t_team_id` или `ct_team_id`. Side в record
берётся из round team assignment. Starting roster и число 5v5 не создают
participation. Пересекающиеся memberships одного player с разными teams
делают lineup invalid для advantage metrics.

## Valid enemy kill и deaths

Valid enemy kill — `CanonicalKill`, для которого attacker и victim являются
доказанными participants, оба team IDs известны и различны, attacker
не равен victim, а event не помечен teamkill/suicide. World kill, suicide и
teamkill не дают ordinary kill, opening, assist, trade и multikill, но
хранятся отдельными counters. Любая первая death event участника,
включая world/teamkill/suicide, даёт `deaths=1` и `survived=false`.
Повторная death в одном competitive round — anomaly: alive count не уменьшается
повторно.

Assist засчитывается только на valid enemy kill, если assister — participant
и teammate attacker, не attacker и не victim.

## Damage и ADR

Canonical `damage_health` хранит raw source value и не изменяется. Аудит
FACEIT demo подтвердил overkill values. Analytics ведёт health state по
victim/round, начиная с 100. Effective damage event равен
`min(raw_damage_health, previous_confirmed_health)`. После event state заменяется
на `victim_health_after`, если он доступен, иначе уменьшается на effective
damage. Events одного tick следуют stable event-ID ordering.

`enemy_damage` — effective damage между разными physical teams. `team_damage` —
effective damage teammate, кроме self. `damage` — весь effective health damage
с валидным attacker. ADR = `enemy_damage / rounds_played`; denominator zero
даёт `null`.

## Opening duel и conversion

Opening duel — первый по `(tick,event_id)` valid enemy kill раунда. Предшествующие
suicide/teamkill/world deaths пропускаются. Без valid enemy kill opening
отсутствует. `opening_team_won_round` и conversions вычисляются только
при available winner. Counts opening kills/deaths остаются available без winner.
Seconds from freeze end равны `(tick-freeze_end_tick)/tickrate` только при
явном tickrate; иначе `null`.

## Trade и trade opportunity

Trade window имеет два взаимоисключающих typed mode. В `ticks` mode обязательны
`requested_ticks` и равный им `resolved_ticks`; seconds и tickrate равны `null`.
Default — **320 ticks**. Это не утверждение о пяти секундах: такое равенство было бы
верно только при доказанном 64 tick/s, которого StratWeb не предполагает.

В `seconds` mode обязательны requested seconds и доказанный canonical tickrate с
source. `resolved_ticks = round_half_up(seconds * tickrate)`, минимум один tick:
точные половины округляются от нуля (`2.5 -> 3`). Если tickrate отсутствует или
конфликтует, весь compute отклоняется configuration error и не меняет policy молча.
Config hash и analytics fingerprint включают mode, requested/resolved values,
tickrate и provenance.

Каждый valid enemy kill A, являющийся первой observed death своей victim в раунде,
создаёт team trade opportunity: teammate victim может
убить именно attacker A в окне. Valid enemy kill B закрывает A, если
attacker B и victim A в одной team, victim B равен attacker A, а team victim B
равна team attacker A. B также должна быть первой observed death своего victim:
уже умершего killer нельзя «обменять» повторно. Каждые A и B используются не более
одного раза. Если B совпадает с несколькими A, закрывается самое позднее A
(`tick,event_id` descending), что минимизирует delta. Team trade success =
closed opportunities / opportunities.

Player trade opportunity — team opportunity, в момент которой player был живым
teammate victim. Это логическая, а не spatial opportunity. Successful player trade =
trade kill этого player. Traded death percentage = deaths, закрытые trade,
делённые на deaths от valid enemy kill.

## Survival, KAST и multikill

Participant survives complete round, если он не был victim ни одной death event.
Disconnect без death не измышляется как death; membership, не разрешающий
participation, не создаёт survivor.

KAST flags не взаимоисключающие: K = valid enemy kill; A = valid assist;
S = survived; T = death player была closed trade teammate. `kast=K or A or S or T`.
KAST% = KAST rounds / rounds played. T зависит от trade policy. При explicit tick
window KAST доступен, а capability metadata явно сообщает tick-based semantics.
При seconds mode KAST доступен только после успешного разрешения доказанного
tickrate; отсутствие evidence отклоняет весь compute.

У trade event `tick_delta` всегда authoritative. `seconds_delta` и его source
доступны только в seconds mode с доказанным tickrate; в ticks mode значение и source
равны `null`, а conversion status равен `unavailable`. Старые записи до rule 1.1.0
сохраняются с status `legacy_ambiguous`.

Multikill count — число valid enemy kills player в round. Categories: `zero`, `one`,
`two`, `three`, `four`, `five`, `five_plus`; 6+ не clamp-ится.

## Man advantage и conversions

Initial alive count равен числу доказанных participants каждой round-side;
5v5 не предполагается, но advantage conversion требует равного ненулевого initial
count обеих сторон. Неравный 4v5/5v4 и неоднозначный lineup помечаются invalid: alive
timeline остаётся наблюдаемым, а conversion — `null`. Каждая первая death participant уменьшает его
side alive count на 1; classification сохраняет enemy/teamkill/suicide/world.
Signed advantage — `T_alive-CT_alive`.

First advantage — первое ненулевое signed difference после death. It is lost,
если later difference становится 0 или меняет знак. `reached_plus_two`
означает, что physical team имела advantage >=2. Conversion/recovery имеет
nullable value без valid lineup или authoritative winner. Opening conversion и first
advantage conversion хранятся отдельно.

## Bomb metrics

V1 учитывает assigned live `planted`, `defused`, `exploded`. Player plants/defuses
требуют valid player ID; team plant/explosion относится к physical T team раунда, а
defuse — к physical CT team, поэтому optional event actor/team не меняет outcome.
Site raw сохраняется,
но A/B не выводится. Plant/post-plant conversion = planted rounds, выигранные
planting physical team, / planted rounds с authoritative winner. Defuse success без
attempt events не вычисляется на player level. Team CT defuse success = CT rounds с
observed defuse / CT rounds, где opposing T team имела observed plant; нулевой
denominator даёт `null`. Bomb outcome coverage = planted rounds с
terminal defused/exploded event / planted rounds. Retake/fake/save/clutch не выводятся.

## Stage 5 ordering versus Temporal 1.1 ordering

Stage 5 retains its versioned deterministic `(tick, event_id)` tie-break for opening,
trade, and man-advantage calculations. This makes analytics reproducible; it does not
claim that two kills with the same tick occurred in UUID order. The analytics rule and
schema version are unchanged in Stage 6.1.

Temporal 1.1 supplies the physical-order metadata: an opening event can be
deterministically selected by Stage 5 while its `SimultaneousEventGroup` reports
`ambiguous_order`. Cross-checks compare the complete Stage 5 death stream and the last
alive counts after each tick against Temporal post-group state. Intermediate same-tick
counts are never compared as authoritative.

## Denominators, null и availability

Counts — integer и могут быть zero. Ratio/percentage равен `null`, если
denominator/population zero или required capability unavailable. `0.0` означает
доказанный zero numerator при positive denominator.

`AnalyticsAvailability`: `available`, `partial`, `unavailable`. Typed reasons:
`missing_round_winner`, `incomplete_rounds`, `missing_participants`, `missing_tickrate`,
`unsupported_event_semantics`, `no_population`, `source_conflict`, `legacy_ambiguous`.
Winner-dependent metrics
используют Stage 4.5 outcome status и не принимают missing за loss/draw.
