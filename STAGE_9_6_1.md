# Stage 9.6.1 — Tactical V2 product view

Status: implemented. Package baseline: `0.10.1`. No database migration and no analytics rule
change.

## Delivered

- Russian analyst-facing Tactical V2 page instead of the raw observation table;
- representative overview with at most one high-denominator item from each family;
- readable observation cards with frequency, ratio, match count and evidence-round count;
- server-side type, map and side filters with a fixed 18-card page size;
- interleaved family ordering so high-cardinality rotations or heatmap cells cannot monopolize the
  first page;
- responsive overview, card, filter and capability layouts;
- plain-language methodological limitations;
- technical IDs, fingerprints and JSON links isolated in a collapsed section.

## Invariants

- the presenter does not recalculate statistics;
- filtering and pagination do not modify stored insights;
- the overview is not a strength ranking or recommendation;
- unknown and unavailable values remain explicit;
- exact provenance remains available for reproducibility.

## Real-profile acceptance

The saved `hanak1ri` run renders with HTTP 200. The default page hides internal route/execute keys,
the CT entry filter returns exactly one existing observation, and heatmap pagination reaches page 2
without server errors. The underlying run remains 191 insights and 674 evidence references.

## Deferred

- complete multi-locale contract (Stage 9.6.2);
- dedicated HTML evidence drill-down (Stage 9.6.3);
- full mobile/manual acceptance and analyst notes (Stage 9.6.4).
