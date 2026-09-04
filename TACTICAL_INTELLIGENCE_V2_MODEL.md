# Tactical Intelligence V2 model

Stage 9.5 computes reproducible tactical observations from completed demos. It does not create
recommendations, infer a caller's intent or treat temporal association as causality.

## Versioned boundary

- schema: `1.2.0`;
- rules: `tactical_intelligence_v2.2.0`;
- persistence migration: `026`;
- input: one user-confirmed opponent team per match and one exact compatible Stage 8.4 lineage;
- output: immutable profile run, typed capabilities, ratio observations and evidence references.

Each source pin stores dataset, Analytics, Temporal, Spatial, Zone Assignment, optional Round
Feature lineage and optional compatible Economy lineage. The run fingerprint covers sorted pins, configuration,
excluded matches, capabilities and complete observation payloads. Identical inputs produce the same
run and insight IDs.

The default query selects only a current-rule run whose exact match/team input set still equals the
profile's current user-confirmed selection. Older or differently scoped runs remain visible in run
history but are never silently presented as current.

## Observation families

| Family | Population and numerator | Important limitation |
|---|---|---|
| CT setup role | complete CT rounds with known live start and early alive player zones; player rounds observed in the explicit A/B/mid group or in multiple groups | player identity merges only by Steam ID; roles summarize first-20-second positions and do not prove responsibility or intent; unknown zones stay unclassified |
| Path cluster | complete known-alive checkpoint formations; rounds sharing an exact compressed zone signature | unknown alive state is excluded; this is exact-key clustering, not a guessed geometric route or called strategy |
| Execute package | T rounds with a proven plant site; identical site plus pre-plant utility-effect bundle | unplanted executes and intent are not inferred |
| Utility outcome | owned HE/fire effects; effects with uniquely associated same-owner, matching-weapon enemy damage in a versioned tick window | overlapping candidate windows are excluded; association is not proof of causality; flash/smoke effectiveness is unavailable |
| Spacing profile | valid known-alive team checkpoints; checkpoints with a player farther than the configured world-unit threshold from every teammate | unknown alive state is excluded; Source 2 units are not a quality score |
| Entry structure | rounds with one unambiguous first enemy kill; selected team wins that duel | same-tick competing openings are excluded |
| Trade structure | unambiguous opening deaths; deaths with a persisted Stage 5 trade event | no trade event does not prove that no trade was attempted |
| Rotation transition | observed CT zone edges after first contact; edge count over all observed edges | movement is not proof of rotation intent |
| Clutch behaviour | proven post-tick-group 1v2+ states; rounds subsequently won | ordering inside a tick is never invented |
| Save behaviour | available Stage 8.4 save-exit contexts; contexts marked saved | absent/unavailable facts do not become false |
| Heatmap cell | alive authoritative position samples in a fixed world-coordinate grid | frequency is sample share, not seconds or round probability |

All observations store `numerator`, `denominator`, `frequency`, `sample_size`, distinct match count,
small-sample warning, limitations and evidence. Evidence points to match, round, tick range and the
available event, snapshot, feature, projectile and utility-effect IDs. Unknown fields remain null;
missing observations are expressed through capabilities rather than fabricated zeroes.

## Data flow

```text
confirmed opponent selections
  -> exact Stage 8.4 source pins
  -> typed round inputs
  -> pure TacticalV2Engine
  -> immutable run / insights / evidence
  -> DuckDB query service
  -> JSON API and Russian inspection UI
```

The pure engine does not read DuckDB. The source adapter performs only exact lineage selection and
typed loading. Persistence validates that every referenced source run still exists before writing.
Deleting a source feature run, match or opponent profile removes dependent Tactical V2 runs first.

## Explicitly unavailable claims

- flash blindness without authoritative blind-state events;
- smoke line-of-sight denial without a proven visibility model;
- causal attribution of damage to an effect merely because time and owner match;
- unplanted execute intent;
- tactical purpose of a movement transition;
- quality or optimality of spacing, clutch and save decisions;
- cross-match statistical support for this new family before it receives a separately versioned
  Statistical Trust adapter.

These limitations are part of the persisted contract and UI. An LLM is not used anywhere in the
calculation.
