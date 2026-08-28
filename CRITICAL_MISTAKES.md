# Critical Mistakes — deterministic round filters

The Critical Mistakes view is a coach-facing shortcut over already persisted canonical,
Temporal, Analytics and Economy evidence. It does not call an LLM and does not infer intent.

## Rules (`critical_round_filters_v1`)

- **Lost +2 advantage**: the selected physical team reached an alive-player advantage of at
  least two and then lost the complete round. Simultaneous tick groups are evaluated only from
  a deterministic post-group state. Ambiguous final groups never contribute an invented state.
- **Lost versus full eco**: the opponent's eligible freeze-end team snapshot is explicitly
  classified as `eco`, and the selected team lost. `force`, `semi`, `full`, `pistol`, `unknown`,
  partial and unavailable classifications are excluded.
- **Early untraded death**: an enemy-caused death of a selected-team player happened no later
  than 15.0 seconds after the canonical live start and no persisted trade references that kill.
  The rule is unavailable when a proven tickrate is unavailable.

Warmup and incomplete rounds are excluded. Unknown outcomes never enter a denominator.
Every card retains `match_id`, `round_number`, optional `tick`, source event IDs and any temporal
group or economy snapshot ID. Observation, tactical interpretation and recommendation remain
separate fields.

## Product flow

Open an opponent workspace and choose **Критические ошибки**. One compute action produces an
immutable run. Filter chips show all errors, lost advantages, eco losses or early deaths. Each
card links to the exact temporal round and 2D playback. Technical lineage and limitations stay
inside the disclosure at the bottom.

Runs are content-addressed and source-pinned. If selected matches or compatible source runs
change, an older result is not presented as current; the page asks for a recalculation.
