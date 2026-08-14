# StratWeb report export contract

Status: Stage 8.9, export schema `1.0.0`, rule `evidence_report_export_v1`.

## Boundary

`ScoutingReportExporter` accepts exactly one `ScoutingReportSource` and one matching
`OpponentWorkspace`. The source already pins the Strategy run and its Analysis, Pattern,
Readiness and Validation provenance. Export performs ordering and rendering only. It does
not query a parser, recompute a statistic, select a different run or create tactical text.

UI filters and pagination are deliberately absent from the export endpoints. A filter may
hide a saved finding on screen, but it cannot silently change the exported denominator.

## Formats

- `export.json` is the stable machine contract and uses UTF-8, sorted keys and schema/rule
  versions. Repeated export of the same source bundle produces identical bytes.
- `report/print` is a complete light-background HTML document with print CSS. The browser
  can print it or save it as PDF without the application navigation.
- `export.pdf` is generated server-side from the same typed contract. It embeds a Unicode
  font, includes page numbers and carries the JSON export fingerprint in the footer and ETag.

The PDF renderer uses ReportLab `5.0.0`. Windows resolves Arial from the system font
directory. The Docker image installs `fonts-dejavu-core`; if neither supported font is
present, the endpoint returns typed HTTP 503 instead of producing unreadable glyphs.

## JSON top-level fields

- export schema, rule and SHA-256 fingerprint;
- opponent profile identity and persisted Analysis/Strategy run dates;
- Analysis and Strategy run IDs/fingerprints;
- acceptance status;
- all opponent, pattern, analysis, readiness, strategy, validation and export versions;
- analysis scope and coverage counters;
- complete corpus manifest;
- deterministic validation and readiness audits;
- all findings, recommendations and skipped findings;
- sample limitations and warnings.

Each corpus row keeps `match_id`, `demo_file_id`, original upload name, demo SHA-256, map,
confirmed opponent team, round count, input status and exclusion reason. Unavailable values
are `null`; export never substitutes zero, an empty identity or an inferred name.

Each finding preserves numerator, denominator, frequency, sample size, Wilson confidence,
separate observation/interpretation/recommendation fields, limitations and the complete
denominator evidence. JSON and printable HTML keep match, round, tick, event, feature,
spatial snapshot, economy snapshot and demo SHA-256 references. The compact server PDF lists
all event IDs and the exact counts of supporting feature/spatial/economy IDs; their complete
machine-readable values remain in the matching evidence record in JSON.

## Reproducibility and safety

The export fingerprint is SHA-256 over canonical JSON excluding the fingerprint field itself.
Collections receive explicit stable ordering before hashing. PDF is built with ReportLab's
invariant mode and no wall-clock generation timestamp, so the same export produces the same
PDF bytes.

Attachment names contain only the fixed `stratweb-report` prefix plus profile/run UUIDs.
Original filenames are document metadata only and never become filesystem paths or response
headers.

Exports are generated on demand and are not written to DuckDB. Replacing a source run creates
a different pinned export; old and new runs are never mixed.

## Deliberate limitations

- Large corpora create long PDFs because denominator evidence is intentionally not truncated.
- PDF contains textual evidence references, not map screenshots or heatmaps.
- No signing, encryption, LLM wording, live data or causal inference is added.
- HTML/PDF are human-readable projections; JSON remains the authoritative export contract.
