# StratWeb UI Design System

Version: `1.1.0`

Stage 8.8.1a introduces one visual contract for all server-rendered StratWeb pages. It
changes presentation only. Parsing, evidence, statistics, readiness, strategy rules and
report composition are unchanged.

## Principles

- Evidence remains more prominent than decoration.
- Primary actions use amber; links and evidence navigation use cyan.
- Green means available or successful, amber means partial or limited, and red means
  unavailable, failed or destructive.
- Raw UUIDs, fingerprints and schema versions stay in monospace technical disclosures.
- Unknown, partial and unavailable remain distinct states and are never hidden by color.
- Every interactive control has keyboard focus, hover, active and disabled treatment.
- Feature CSS consumes semantic tokens or the documented compatibility aliases.

## Layers

1. `tokens.css` owns typography, semantic color, spacing, radii, depth and motion.
2. `layout.css` owns the application bar, page shell, headings, grids and tables.
3. `components.css` owns controls, cards, statuses, notices and reusable data surfaces.
4. Feature stylesheets may define domain layouts but should reuse the global tokens.
5. `polish.css` is the final product-wide override layer for narrow-screen hardening,
   keyboard focus, overflow safety and consistent empty/card surfaces.

The compatibility aliases (`--surface`, `--line`, `--accent`, `--cyan`, and related
names) are intentionally retained so existing map, economy, report and playback styles
can migrate without an unsafe all-at-once rewrite.

## Reference and validation

Run the local application and open `http://127.0.0.1:8000/ui/style-guide`. The page is a
read-only component reference and visual-regression target. The root HTML element
publishes `data-design-system-version="1.1.0"`; the CSS publishes the same version as a
custom property. A mismatch is a release error.

Future theme customization must preserve semantic roles and accessibility contrast. It
must not allow a theme to redefine evidence meaning (for example, making an unavailable
state appear successful).

## Application shell

Stage 8.8.1b separates product navigation from the current match workspace. The global
bar contains only Matches and Opponents. When a match is open, a second contextual bar
shows its map, physical-team score and links to Overview, Rounds, Map, Timeline, Economy,
Facts, Players and Diagnostics.

`shell-nav.js` selects one active destination from the exact path, route prefix and
optional anchor. It changes presentation and `aria-current` only; it never selects or
loads evidence. On narrow screens the match navigation scrolls horizontally and keeps
the active destination visible.

## Product pages and technical detail

Stage 8.8.1c establishes progressive disclosure for high-traffic technical pages.
Diagnostics leads with readiness, readable tools, coverage and warnings. Economy adds
classification guidance and direct round navigation. The scouting report keeps its
acceptance gate and warnings visible while moving the full deterministic check matrix,
versions, fingerprints and raw JSON links into explicit disclosures.

Collapsing technical material does not discard it. All identifiers, versions, source
links and denominator evidence remain in the rendered document and are available on
demand. Computed values are passed through unchanged; the templates do not calculate a
new capability, statistic or recommendation.

## Stage 8.8.4 product polish

Version 1.1.0 hardens the shared shell for phones and narrow windows. Reports, filters,
fact grids and technical definitions collapse to one readable column before content can
overflow. Long evidence identifiers wrap only inside technical surfaces, table containers
remain horizontally scrollable, and reduced-motion preferences disable decorative motion.

User-facing navigation and accessibility labels are Russian. Stable machine values such as
schema versions, fingerprints, UUIDs and internal state enums remain unchanged and are shown
only in explicit technical disclosures.
