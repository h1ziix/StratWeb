# Stage 8.8.4 — product UI polish

Stage 8.8.4 completes the current visual cleanup before StratWeb returns to analytical
features. It is a presentation-only release: no parser, stored evidence, deterministic
statistics, findings, recommendations or fingerprints are recalculated.

## What changed

- The shared design-system contract is version `1.1.0`.
- A final global polish layer keeps cards, reports, filters, facts and diagnostics readable
  on phone-sized screens.
- Long evidence identifiers wrap inside their own technical surfaces instead of widening
  the complete page; wide tables keep local horizontal scrolling.
- Empty states, headings, disclosures, focus rings and reduced-motion behavior are consistent.
- Remaining user-facing layer names, spatial accessibility labels and diagnostics actions
  are presented in Russian.

## Responsive contract

At widths up to 700 px, analytical grids become one column, recommendation headers stack,
breadcrumbs scroll locally and definition lists use a vertical layout. At widths up to
520 px, page padding is reduced and ordinary action buttons can fill the available width.
The 2D map keeps its own specialized playback layout and is not reimplemented by this stage.

## Deliberate limitations

UUIDs, fingerprints, schema/rule versions and raw JSON are still available in explicit
technical disclosures because they are required for reproducibility. Internal enum values
are not translated in storage or APIs. English, Spanish and Chinese locale catalogs remain
future work.

## Acceptance

- `/ui`, match diagnostics, round facts, economy, 2D playback, temporal views and scouting
  reports render through the same versioned style foundation.
- Desktop and phone-sized pages do not acquire page-level horizontal overflow from cards,
  reports or long identifiers.
- The Python test suite, Ruff and Mypy remain the release gate.
