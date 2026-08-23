# Statistical Trust Model 1.0

Schema: `1.0.0`. Rule version: `match_clustered_trust_v1`.

## Purpose and boundary

This layer answers one narrow question: how reliably does a persisted Stage 8.5 observation
repeat between completed matches? It does not infer intent, causality, tactical value or a response
to play. Source observations and recommendations remain separate immutable artifacts.

## Unit of uncertainty

The source numerator and denominator still count eligible rounds. For uncertainty, every included
round is grouped by `match_id`; a match contributes its own numerator, denominator and frequency.
Rounds inside one match are never counted as independent clusters.

The 95% interval resamples complete match clusters with replacement for 2,000 iterations. Each
resample reports the size-weighted pooled round frequency. The random seed is derived from the
source `pattern_id` and configuration hash, making the run byte-for-byte reproducible.

At least two clusters are required for an interval. The acceptance gate defaults to at least five
matches, while match-stability measures require at least three.

## Testable hypotheses

The V1 null frequency is 0.5 only for:

- `BinaryPatternValue` observations;
- the explicitly registered `site:A` / `site:B` mutually exclusive site pair.

Player, route, setup, timing bucket and other categorical patterns do not automatically receive a
uniform baseline. Their decision is `not_testable` and null/effect/p/q values remain null.

For a testable pattern, practical effect is `observed_frequency - null_frequency`. The default
minimum is `0.10`. Hypothesis evidence uses an exact one-sided sign test across matches: matches
above the null are successes, matches below are failures, and exact ties are excluded. This avoids
pretending that rounds from the same match are independent.

Raw match-level p-values form one global family for the pinned pattern run. Benjamini–Hochberg
adjustment controls the configured false-discovery rate, default `0.05`. A q-value is evidence
against the registered null, not the probability that the observation is true.

## Stability

Match stability removes each complete match cluster in turn and recomputes pooled frequency.
Defaults require:

- leave-one-match-out frequency range no greater than `0.20`;
- more-than-null frequency in at least `60%` of match clusters.

Patch and roster-period stability are unavailable in V1. `imported_at` is not match time, a parser
version is not a CS2 patch, and nickname changes do not prove roster periods. These dimensions need
canonical match time, game-build/patch evidence and explicit versioned roster-period definitions.

## Decision gates

`supported` requires every gate to pass:

1. source pattern availability is complete rather than partial;
2. minimum match clusters;
3. minimum practical effect;
4. cluster-bootstrap lower bound above the registered null;
5. adjusted q-value at or below the configured FDR;
6. match stability.

Otherwise a testable result is `not_supported`, or `insufficient_data` when cluster/stability data
are below their minimum. `not_supported` does not prove the pattern is absent.

## Reliability ranking

Only assessments that pass every support gate receive a rank. Rejected, partial, insufficient and
not-testable rows deliberately remain unranked. The versioned score combines clustered lower-bound support, positive practical
effect and direction consistency. It is explicitly an evidence-reliability order—not tactical
importance, recommendation priority or expected win impact.

V1 score is
`0.5 * max(0, lower_bound - null) + 0.3 * max(0, effect) + 0.2 * direction_consistency`.
Supported rows sort by score, match count and stable pattern ID. This formula is versioned
as `evidence_reliability_rank_v1`.

## Persistence and lineage

Migration 025 stores immutable `statistical_trust_runs` and
`statistical_trust_assessments`. Every assessment pins profile, pattern run, pattern ID, versions,
configuration hash, match contributions, gates, limitations and unavailable dimensions. Deleting
its source pattern run cascades to the dependent trust run.
