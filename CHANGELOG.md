# Changelog

## [0.25.0] - 2026-09-04

### Added

- Optional local Ollama rephrasing of a pinned, validated match plan into short Russian coach
  sections: what to expect, how to play and what to avoid.
- Immutable DuckDB AI artifacts with source/model fingerprints, prompt/schema/rule versions and
  direct evidence links for every generated point.
- A coach-report action and readable offline/error states; deterministic reports remain usable
  when Ollama is stopped or its answer is rejected.

### Safety

- Ollama is restricted to loopback HTTP and receives at most six already-published source items,
  never raw demos, coordinates or Steam IDs.
- Structured responses are rejected for unknown source IDs, source-absent numbers, absolute
  claims and several unsafe literal translations. AI text is labelled as a draft and never
  replaces the original statistics, evidence or limitations.

## [0.24.4] - 2026-09-04

### Fixed

- `STRATWEB_CS2_DEMO_DIR` now accepts the CS2 `game/csgo` directory and creates its dedicated
  `StratWeb` child on the first local export. The previous explicit `game/csgo/StratWeb` value
  remains supported, while arbitrary destinations are still rejected before creating files.

## [0.24.3] - 2026-09-04

### Fixed

- Declared the telestrator schema version as a typing `Final`, preserving the literal default
  expected by `TelestratorBoard` and restoring a clean strict `mypy src` run.

## [0.24.2] - 2026-09-03

### Fixed

- The tactical overview offers **Prepare the match plan** when its separate report pipeline has
  not run. Only an existing compatible strategy enables the **Open the match plan** link.
- One localhost-only POST composes existing patterns, findings, readiness and strategy stages,
  then opens the pinned report. Repeated preparation reuses identical persisted runs.
- A missing current report now has a readable preparation screen instead of an English Stage 8.7
  error. No-ready-match and recoverable storage errors include retry/navigation actions.
- GET requests remain read-only, missing explicitly pinned reports remain 404, and analytical
  thresholds, evidence validation and small-sample restrictions are unchanged.

## [0.24.1] - 2026-08-29

### Fixed

- Tactical V2 now selects the latest compatible partial run when some confirmed matches have not
  reached the compatible Stage 8.4 feature layer yet. Previously the run was successfully saved
  but hidden from the overview unless every selected match was fully processed.
- Run freshness still checks the exact confirmed team for every processed match; an unprocessed
  selection can no longer make an otherwise valid tactical overview look broken.

## [0.24.0] - 2026-08-29

### Added

- A map-specific one-page match cheat sheet with at most two deterministic signals for opponent
  T-side, CT-side, recurring risks and recommended responses.
- One-click plain-text copy for Discord/team chat and a compact A4 landscape print layout.
- Explicit map selection and map-scoped corpus reliability instead of mixing findings from
  different maps on one preparation sheet.

### Safety

- The cheat sheet is only a projection of pinned findings and recommendations; it does not
  recalculate statistics, infer missing values or use an LLM.
- Failed strategy validation suppresses recommendations. Small samples remain visibly labelled,
  and every shown signal links back to its evidence.

## [0.23.0] - 2026-08-29

### Added

- An interactive coach telestrator in every exact 2D round view: arrow, pencil, zone and text
  tools behind one compact **Разметка** button.
- Per-match/per-round DuckDB boards with normalized map coordinates, schema version `1.0.0`,
  revision conflict protection, undo, clear, visibility and explicit save controls.
- A separate SVG annotation layer that is not touched by the playback renderer, including a
  mobile bottom-sheet layout.

### Safety

- Telestrator marks are user-authored notes, not demo evidence, analytical findings or inferred
  game facts. They never modify playback, canonical events or deterministic statistics.
- Writes remain localhost/same-origin only, malformed geometry is rejected and concurrent tabs
  cannot silently overwrite a newer board.

## [0.22.0] - 2026-08-29

### Added

- A local-only **Скопировать команды CS2** action in the 2D round viewer. It prepares the exact
  retained demo in `game/csgo/StratWeb` and copies separate verified `playdemo` and
  `demo_gototick ...; demo_pause` commands for the currently displayed tick.
- SHA-256 verification before export, safe UUID destination names, verified-file reuse and an
  atomic hard-link/copy fallback.

### Safety

- StratWeb never launches CS2, executes console commands, injects code, reads game memory or
  automates spectator input. Missing retained demos and mismatched hashes are explicit errors.
- Automatic first-person/player selection is deliberately unavailable until a CS2 spectator
  entity index can be proven from source data.

## [0.21.0] - 2026-08-29

### Added

- A Russian coach-first **Критические ошибки** page with one-click deterministic filtering for
  lost +2 advantages, losses against confirmed full eco and untraded deaths in the first 15 seconds.
- Exact round, tick, event, Temporal group and Economy snapshot evidence with immutable DuckDB
  runs under migration 031.
- Conservative simultaneous-event handling: only deterministic post-group alive state can prove
  an advantage; ambiguous final state is excluded instead of ordered by event ID.

### Safety and limitations

- Warmup, incomplete rounds, unknown outcomes and unknown/force/semi economy are not guessed.
- The 15-second filter is unavailable without a proven tickrate; no default 64-tick assumption is
  used.

All notable StratWeb changes are recorded here. The project uses semantic versions for
release baselines; analytics, persistence and report contracts keep their own independent
schema and rule versions.

## [0.20.0] - 2026-08-28

### Added

- A deterministic “Мы против них” workflow comparing two user-confirmed team profiles using
  their latest compatible Tactical V2 runs.
- Evidence-backed opening-pressure versus trade-support and opening-pressure versus early-spacing
  matchup rules, always scoped to the same map and opposite T/CT sides.
- A coach-first comparison page with one profile selector, plain observations, separate tactical
  interpretation and recommendation, two-sided sample counts and links to both teams' rounds.
- Immutable DuckDB migration 030 for versioned Head-to-Head runs and source Tactical V2 lineage.

### Safety

- Unknown sides are excluded. Different maps, same-side samples and stale Tactical V2 runs are not
  silently paired.
- Risk is a deterministic alignment of two historical samples, not a causal claim or a prediction
  that the opponent will repeat the behaviour.
- Economy- and zone-specific wording is withheld until both typed evidence dimensions exist; the
  engine does not invent “eco banana push” labels from unrelated observations.

## [0.19.0] - 2026-08-28

### Added

- Utility ROI in Tactical V2: teammate/enemy blind duration for player-owned flashes,
  utility retained immediately before death with a versioned price estimate, and smoke timing
  in deterministic five-second buckets.
- A dedicated plain-language grenade section in the tactical report with direct links to the
  stored match, round, event, projectile, effect and spatial snapshot evidence.
- Canonical `player_blind` normalization and persisted source clock fields verified against the
  pinned `demoparser2==0.41.4` API and bundled test demo.

### Changed

- Canonical schema is now `1.2.0`, normalization rules `1.3.0`, spatial schema `1.3.0`,
  spatial rules `1.4.0`, and Tactical V2 schema/rules `1.1.0` / `2.1.0`.
- Spatial samples retain normalized utility inventory so pre-death evidence can be evaluated
  without reconstructing or guessing purchases.
- DuckDB migration 029 persists blind events, source time and round-start time while preserving
  compatibility with older partial migration fixtures.

### Safety

- “No recorded direct effect” is not presented as proof that a grenade was tactically useless.
- Smokes are never classified as wasted without line-of-sight evidence. The displayed smoke
  contact window ends at first confirmed enemy damage and is not described as an inferred execute.
- Missing blind, inventory or source-clock values are excluded and reported as unavailable rather
  than filled with estimates.

## [0.18.0] - 2026-08-28

### Added

- Deterministic automatic team names from the round-level `t_team_clan_name` and
  `ct_team_clan_name` fields verified in the pinned `demoparser2==0.41.4` output.
- Conservative explicit nickname-tag fallback when at least three players and a strict roster
  majority share `[TAG]` or `TAG |` notation.
- Persisted inference source, support ratio and rule version in canonical team provenance.

### Changed

- Canonical normalization rule version is now `1.2.0` and parser requests include
  `team_clan_name`. Stale cached canonical worker artifacts are invalidated automatically.
- Manual team labels still override demo-derived names; resetting a manual label reveals the
  automatically detected name.

### Safety

- Generic T/CT labels, numeric placeholders, tied/weak observations and unsupported
  `team_<value>` names are never promoted.
- `team_<nickname>` is accepted only when the suffix matches a known player in the resolved
  physical roster. The demo exposes no captain flag, so player order is never used as a guess.

## [0.17.0] - 2026-08-27

### Added

- Bulk upload accepts multiple `.dem` files, a selected folder or a ZIP archive and persists them
  as one named training pool linked to an opponent profile.
- A dedicated pool page shows aggregate progress plus the independent status and match link for
  every demo. Recent pools remain discoverable from the match library.
- Folder drag-and-drop and ordinary multi-file/folder pickers are available in the local UI.

### Changed

- The default bounded import queue now holds 16 waiting jobs, enough for a normal 5–6 demo
  practice day while retaining the single DuckDB writer.
- Duplicate, invalid and failed demos are isolated per file instead of aborting the whole batch.

### Safety

- ZIP members are streamed to UUID-named files without trusting archive paths. Count, individual
  size, total uncompressed size, encryption, compression-ratio, disk-space and CS2 signature
  guards run before parser submission.
- A batch is linked to the chosen opponent, but StratWeb does not guess which physical team is the
  opponent when roster evidence is ambiguous; the existing explicit confirmation flow remains.

## [0.16.0] - 2026-08-27

### Added

- Deterministic corpus reliability grades: facts from a specific game for 1–2 matches,
  tactical trend for 3–7, stable tactical trend for 8–14 and high statistical reliability
  for 15 or more matches.
- Readiness summaries, ordinary and analyst reports, recommendation cards and stable JSON
  exports now carry a plain-language reliability label and limitation message.

### Changed

- A corpus below 15 matches and a small finding sample are limitations, not automatic blockers.
- Limited findings may enter the deterministic recommendation rules while preserving their
  exact numerator, denominator, confidence interval, evidence and limitations.
- Corpus validation reports a warning below 15 instead of rejecting an otherwise valid report.
- Default corpus target changed from 20 to 15 in pattern, readiness, strategy validation and
  Tactical V2 configuration.

### Safety

- One or two matches are explicitly labelled as facts of those games, not a proven opponent habit.
- Missing evidence, partial source data under the strict policy, unknown buy context and integrity
  failures can still block publication. No LLM statistics or causal claims were introduced.

## [0.15.0] - 2026-08-27

### Added

- Stage 9.7.1 adds a plain-language round story for every round: a short verified event sequence,
  a separately identified turning point and a separately identified confirmed problem.
- Story selection is deterministic. It uses persisted round facts, prefers fully available
  evidence, orders milestones by source tick and links every shown fact to the exact 2D moment.
- Explicit unavailable cards replace guesses when no lost-advantage or untraded-death fact exists.

### Changed

- The round-facts page now opens as responsive story cards instead of a technical evidence table.
- Filters, counters, coverage, identifiers, JSON payloads and the complete paginated evidence table
  remain intact inside one collapsed analyst mode.
- Raw grenade lifecycle codes and tick counters are omitted from the ordinary story layer; exact
  values remain available in analyst mode.

### Safety

- No parser, analytical rule, persisted fact, API response or DuckDB schema changed. The story is
  a typed presentation projection and does not infer intent, causality or an undocumented error.

## [0.14.0] - 2026-08-26

### Added

- Stage 9.7 introduces Match Hub: one product-first home for a completed match with a clear
  scoreboard, one primary viewing action, three core destinations, rounds and team rosters.
- A versioned `MatchHubView` chooses the best available round destination deterministically:
  2D playback first, compatible timeline second, and no fabricated fallback.
- A dedicated responsive visual layer provides map atmosphere, compact round cards, mobile
  stacking and reduced-motion support.

### Changed

- The shared match navigation now keeps Overview, Map and Timeline visible and moves secondary
  destinations into one accessible “More / Ещё” menu. Locale contract `3.3.0` records the label.
- Each round has one complete-card action instead of separate Map and Timeline buttons.
- Technical health, event counters, player statistics, team-name editing and source identifiers
  remain available but are collapsed below the ordinary match experience.

### Safety

- Match Hub reads existing canonical, analytics, Temporal, Spatial, economy, feature and map
  summaries. It does not recalculate or mutate evidence, recommendations or DuckDB records.

## [0.13.0] - 2026-08-24

### Added

- Stage 9.6.7 replaces the match diagnostics landing page with a human-facing demo-quality
  experience: one readiness answer, one primary action and three plainly described capabilities.
- Deterministic presentation models translate existing availability and map/zone metadata into
  user-impact limitations without changing or guessing analytical results.
- A dedicated responsive visual layer adds the map backdrop, graphite/mint depth, restrained
  motion and a single-column phone layout with reduced-motion support.

### Changed

- The match navigation now calls the page “Demo quality” / “Качество демки”.
- Locale contract `3.2.0` records the renamed navigation label.
- Coverage percentages, run IDs, schema versions, internal warnings and JSON exports are hidden
  by default inside one technical disclosure instead of dominating the page.
- Limitations explain what the user may notice in the report; raw diagnostic wording remains
  available for exact verification.

### Safety

- Readiness is a deterministic projection of existing canonical, analytics, Temporal, Spatial,
  map-revision and zone-assignment state. No parser, calculation, persistence or API contract was
  changed.

## [0.12.2] - 2026-08-24

### Fixed

- Evidence links now keep their exact source tick but open the round player in smooth mode;
  report, Tactical V2 and round-feature entry points no longer force stepwise playback.
- Dense combat and utility sequences no longer perform a complete exact render immediately
  before the smooth render of the same animation frame.
- Playback waits for a small time-based buffer before starting, reducing stalls when event-dense
  chunks cover fewer seconds than ordinary movement chunks.

### Performance

- Stored state, labels and the bomb marker are committed without a redundant player, projectile,
  effect and event draw pass.
- Prefetching remains based on demo time rather than sample count, so fights do not change the
  playback clock or analytical evidence.

### Safety

- The initially selected tick is still the exact persisted evidence tick. Smooth mode only
  interpolates the visual movement after playback begins; API responses and authoritative
  snapshots remain unchanged.

## [0.12.1] - 2026-08-24

### Fixed

- The one-tap coach report now converts typed pattern values into short Russian phrases instead
  of exposing parser-oriented English labels and long arrow-separated routes.
- Bomb routes are reduced to their proven destination and a known corridor, for example
  “Бомбу несли через лонг к точке A”; the full source route remains in analyst mode.
- Internal outcome labels, grenade names, common zone names and starting setups no longer leak
  into coach cards as raw technical text.
- Unknown utility locations are described as not determined and are never guessed.

### Changed

- Trivial spawn-presence findings, spawn-only CT setups and utility findings without a resolved
  zone no longer consume one of the three representative coach cards.
- Coach projection rule `coach_report_projection_v2` keeps this selection and wording change
  independently identifiable from the immutable analytical run.

### Safety

- Findings, source values, ratios, confidence, evidence, recommendations, APIs and DuckDB rows
  are unchanged; only the short coach projection is affected.

## [0.12.0] - 2026-08-24

### Added

- Stage 9.6.6 adds a one-tap coach report with six short, swipeable steps: trust, attack,
  defence, risks, verified responses and source rounds.
- A deterministic coach projection selects at most three representative findings per section
  from the complete immutable report source.
- The former full report remains available as an explicit analyst mode.
- Keyboard, touch-swipe, reduced-motion and no-JavaScript fallbacks cover the new flow.

### Changed

- The opponent workspace now leads with one “Show match plan” action; tactical, trust and JSON
  tools moved into a secondary menu.
- Design system `2.0.0` replaces the orange/blue product identity with a graphite/mint palette,
  deeper surfaces and restrained functional motion.
- Locale schema `3.1.0` adds complete Russian/English coach-flow copy.

### Safety

- Coach curation is presentation-only and cannot change findings, ratios, confidence, evidence,
  source pins or recommendation gates.
- Empty risk and recommendation steps remain explicitly empty; weak evidence is never promoted
  into a tactical instruction.
- Exact statistics and exports remain available in analyst mode and evidence disclosures.

## [0.11.0] - 2026-08-24

### Added

- Stage 9.6.5 introduces a plain-language coach view for Tactical V2.
- Deterministic frequency bands explain results as rarely, sometimes, often or almost always.
- Every finding states sample reliability in ordinary language and links directly to its rounds.
- A primary match-plan action connects observations to the existing recommendation report.

### Changed

- The default list now shows one representative per finding family and only three key signals;
  selecting a family still reveals the complete persisted set.
- Attack/defence labels replace raw T/CT symbols in the reading layer.
- Exact percentages, ratios, counts, limitations, ticks and UUIDs moved behind explicit
  explanation or service-data disclosures.
- Evidence cards have one obvious primary action; alternate timeline and event tools are folded.
- Locale schema `3.0.0` rewrites the Tactical V2 Russian/English vocabulary for players and
  coaches.

### Safety

- Frequency bands are a pure deterministic projection over the persisted ratio.
- Exact numerator, denominator, percentage, sample size, limitations and source lineage remain
  available and unchanged.
- No analytical rule, Tactical schema, DuckDB table or recommendation was modified.

## [0.10.4] - 2026-08-24

### Added

- Stage 9.6.4 adds one local analyst note per exact Tactical V2 run and observation.
- DuckDB migration 027 stores notes separately from immutable evidence and statistics.
- Tactical calculation and note forms expose explicit submitting states.
- Missing or empty evidence receives dedicated Russian/English UI states.

### Changed

- Evidence actions, headings and note controls stack cleanly on phone-sized screens.
- Locale schema `2.2.0` covers analyst-note, loading, empty and error messages.

### Safety

- Notes never participate in analytical fingerprints, ratios, evidence or recommendations.
- Note mutation remains localhost- and same-origin-protected; deleting a Tactical run removes
  only notes pinned to that run.
- Missing evidence is presented as unavailable data and is never converted into a zero.

## [0.10.3] - 2026-08-24

### Added

- Stage 9.6.3 adds a Russian/English HTML evidence drill-down for every Tactical V2
  observation.
- Evidence cards navigate to the exact source match, round, tick, event detail, post-tick
  snapshot, exact-mode 2D map and round facts when the corresponding reference exists.
- Temporal tick groups and event rows now expose stable HTML anchors.

### Changed

- Tactical V2 persistence exposes one bounded insight lookup instead of loading the complete
  observation set for a detail page.
- Locale schema `2.1.0` includes all evidence navigation labels in both supported catalogs.

### Safety

- Every deep link pins the Temporal, Spatial or Feature run stored in the selected Tactical
  source lineage; latest-run data is never silently mixed into the page.
- Missing lineage or unavailable reference types remove the precise action instead of creating
  an inferred link.
- Evidence navigation is read-only and does not recalculate observations or mutate DuckDB.

## [0.10.2] - 2026-08-24

### Added

- Stage 9.6.2 introduces a versioned `2.0.0` locale contract for the shared shell and
  Tactical V2 product surface.
- Russian and English catalogs have identical stable keys and formatting placeholders.
- A page-level language selector persists a valid explicit choice in a same-site cookie.

### Changed

- Tactical card titles and descriptions are now locale-neutral presenter keys plus proven
  values instead of preformatted Russian strings.
- Status, neutral team labels and limitation messages render through the selected locale
  without changing canonical values or persisted analytical output.

### Safety

- Locale selection is presentation-only and cannot alter observations, ratios, evidence,
  fingerprints or JSON API responses.
- Unsupported locale values never poison the cookie and fall back deterministically.
- The release script resolves the installed package version instead of expecting obsolete
  `0.7.0` artifacts.
- Spanish and Chinese are not advertised until each catalog and surface passes the same
  no-mixed-language acceptance gate.

## [0.10.1] - 2026-08-23

### Changed

- Stage 9.6.1 replaces the Tactical V2 diagnostic table with a Russian product view.
- Adds representative overview cards, type/map/side filters and bounded pagination.
- Internal insight keys and run identifiers are removed from the primary reading flow.
- Capability coverage and per-observation limitations are presented in plain language.

### Safety

- Filtering and ordering are presentation-only; persisted ratios and evidence are never changed.
- The overview chooses the largest existing denominator per family and is explicitly not a ranking
  or recommendation.

## [0.10.0] - 2026-08-23

### Added

- Stage 9.5 Tactical Intelligence V2 with ten deterministic observation families.
- Source-pinned path, execute, utility, spacing, entry/trade, rotation, clutch/save and heatmap
  calculations.
- Immutable DuckDB migration 026 with normalized evidence lookup and dependency-aware cleanup.
- JSON API and Russian opponent inspection page.

### Safety

- Tactical intent, recommendation and causality are never inferred.
- Same-tick clutch state is evaluated only after the complete group.
- Flash/smoke effectiveness and unavailable save facts remain typed unavailable.
- Every observation retains numerator, denominator, frequency, sample size and source evidence.

## [0.9.0] - 2026-08-23

### Added

- Stage 9.4 immutable Statistical Trust runs and DuckDB migration 025.
- Deterministic match-cluster bootstrap intervals and leave-one-match-out stability.
- Exact one-sided match-cluster sign tests with global Benjamini–Hochberg FDR correction.
- Pre-registered practical-effect, cluster-count, interval, multiplicity and stability gates.
- Evidence-reliability ranking separate from observations and tactical recommendations.
- JSON API and Russian statistical-trust workspace for each opponent profile.

### Safety

- Multi-category patterns without a justified null hypothesis are `not_testable`.
- Patch and roster-period stability remain typed unavailable because match patch/time metadata is
  not proven by the current canonical schema.
- Existing findings and recommendations are not silently rewritten or re-ranked.
- Statistical support is explicitly not presented as causality or tactical value.

## [0.8.0] - 2026-08-23

### Added

- Stage 9.3 parser isolation: every native `demoparser2` call runs in a disposable child
  process and returns an atomically written, Pydantic-validated JSON artifact.
- Streaming upload SHA-256, early duplicate refusal, bounded admission and typed backpressure.
- Durable cancellation, retry checkpoints, worker PID/peak-memory diagnostics and reuse of
  hash/tick-matched canonical, economy and spatial artifacts.
- Parser timeout, working-set memory and free-disk guards with controlled error codes.

### Changed

- DuckDB writes remain in the single application process; parser children never open the
  database, preventing cross-process DuckDB writer conflicts.
- Graceful server shutdown stops parser children before final durable job-state writes.
- Import-job migration 024 stores source identity, worker/checkpoint and cancellation metadata.

### Safety

- Original upload names remain presentation metadata; files keep random internal names.
- Cancellation never invents partial evidence and retained demos can be retried explicitly.
- Stage 9.4 statistical work is not included.

## [0.7.0] - 2026-08-22

### Added

- Stage 9.2b verified DuckDB backup using `COPY FROM DATABASE` before any V2 mutation.
- Version-aware `canonical_key_indexes_v2` reads with three canonical lookup indexes.
- Deterministic key/payload parity, warm-cache latency gates and persisted migration status.
- `storage status`, `storage migrate-v2` and reversible `storage rollback-v1` commands.
- Migration and rollback tests covering backup refusal, payload parity and repository reads.

### Changed

- Active V2 writes store Spatial and bomb payload only in their canonical tables.
- A rehearsed slim-table join was rejected after exceeding the latency budget; direct canonical
  indexes matched legacy lookup performance and became the final design.
- Parquet remains an archive candidate only, not an interactive storage dependency.

### Safety

- Existing legacy mirror rows remain intact during the acceptance window.
- No mirror deletion, run retention or disk reclamation is performed in Stage 9.2b.
- Original uploaded demos are never classified as automatically deletable.

## [0.6.0] - 2026-08-14

### Added

- Stage 9.2a read-only DuckDB storage audit with exact rows, block attribution and JSON bytes.
- Mirror/derived relationship audits for Spatial, bomb-position and zone data.
- Bounded warm-cache benchmarks for five representative application query shapes.
- Explicit run-history inventory and limited 20/100/500-match growth projections.
- `stratweb storage audit` CLI with safe JSON output protection.

### Findings

- The five-match local database is about 1.45 GiB with 2,199,091 exact rows.
- Spatial and bomb lookup mirrors duplicate about 695.6 MB of identical JSON payload.
- Stage 9.2b should test slim key-only lookup tables before any destructive migration.

### Safety

- Stage 9.2a never mutates, checkpoints, compacts or deletes from the audited database.
- Additional immutable runs are inventoried but are not classified as deletion-safe.

## [0.5.0] - 2026-08-14

### Added

- Stage 9.1 versioned Golden Corpus manifest and external SHA-256 demo storage contract.
- Deterministic corpus readiness audit for opponent, map, source, edge-case and parser coverage.
- Analyst-labelled finding contracts with evidence and explicit indeterminate values.
- Deterministic TP/FP/TN/FN, precision, recall, false-positive-rate and F1 evaluation.
- `stratweb corpus validate` and `stratweb corpus evaluate` CLI commands.

### Known limitations

- The local manifest contains five FACEIT candidates, not 20 confirmed matches of one opponent.
- Valve, GOTV/HLTV, POV, damaged and incomplete fixtures still need real analyst-reviewed demos.
- Corpus readiness is intentionally `blocked` until those external data requirements are met.

## [0.4.0] - 2026-08-14

### Added

- deterministic economy, round-feature, cross-match pattern, finding, readiness and
  counter-strategy layers;
- evidence-first opponent report with stable JSON, printable HTML and PDF exports;
- Russian product presentation layer and versioned design system;
- `uv.lock`, Windows/Linux CI and a local release quality gate;
- a documented release and recovery procedure.

### Changed

- established commit `8351d5a` as the recoverable Stage 8.9 source baseline;
- bound Docker Compose to host loopback by default;
- made local Make targets use the frozen uv environment;
- ignored generated `output/`, `tmp/` and `.runtime/` artifacts.

### Known limitations

- the application is still a single-user, local-first product without authentication;
- the accepted opponent corpus is below the default 20-match gate;
- Valve/HLTV/GOTV corpus validation, storage compaction and worker isolation remain
  future hardening work;
- Valve radar assets are local-use inputs and are not included in the source release.

## [0.3.0] - 2026-07-27

- initial repository baseline through the opponent workspace and early Zone Engine work.
