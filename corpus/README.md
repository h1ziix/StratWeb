# StratWeb Golden Corpus

This directory contains review metadata only. Never commit `.dem` files, player-private
notes, DuckDB databases, FACEIT credentials or downloaded archives.

## Safe local layout

Keep corpus demos outside the repository. Each file must be named by its SHA-256:

```text
C:\Users\<user>\StratWeb-data\golden-corpus\demos\
  <64 lowercase hex characters>.dem
```

The filename is an integrity address, not an original upload name. The original filename
is unnecessary for evaluation and is deliberately excluded from the public-safe manifest.

## Review workflow

1. Calculate SHA-256 and copy the demo to the external directory using `<sha256>.dem`.
2. Add a `candidate` case. Unknown facts remain JSON `null`; do not infer them.
3. Parse the demo with the exact parser version recorded in the compatibility matrix.
4. Have an analyst confirm the source, opponent identity, expected facts and edge cases.
5. Change the case to `confirmed` and record `reviewed_at` and `reviewed_by_role`.
6. Add positive, negative or indeterminate finding labels. Positive labels require evidence.
7. Run the readiness and file-integrity gate.

Readiness requires both positive and negative determinate labels. This is necessary to
measure recall and false positives; a collection containing only successful findings is not
an evaluation corpus.

```powershell
uv run --frozen stratweb corpus validate `
  --manifest corpus/golden-corpus-v1.json `
  --demo-root C:\Users\<user>\StratWeb-data\golden-corpus\demos `
  --pretty
```

Add `--require-ready` in an acceptance job. It returns exit code `11` while any mandatory
coverage is missing. A normal validation deliberately returns JSON successfully even when
the corpus is blocked, so operators can inspect all blockers at once.

After the manifest and external files pass review, rerun canonicalization and compare every
known expected fact. One damaged demo is isolated and cannot abort the remaining cases:

```powershell
uv run --frozen stratweb corpus run `
  --manifest corpus/golden-corpus-v1.json `
  --demo-root C:\Users\<user>\StratWeb-data\golden-corpus\demos `
  --require-pass `
  --pretty
```

Only confirmed cases run by default. `--include-candidates` is an explicit analyst/debug
action and never promotes those cases or counts them toward readiness.

## Finding evaluation

A prediction artifact must pin the exact `manifest_fingerprint` and an immutable algorithm
version. Evaluation never treats a missing or unavailable prediction as `absent`.

```powershell
uv run --frozen stratweb corpus evaluate `
  --manifest corpus/golden-corpus-v1.json `
  --predictions C:\path\predictions.json `
  --require-complete `
  --pretty
```

The output stores TP, FP, TN, FN, sample size, precision, recall, false-positive rate and F1.
Metrics with a zero denominator are `null`, not guessed.
