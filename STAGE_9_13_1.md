# Stage 9.13.1 — Map-scoped Stratbook UX

## Result

The default coach journey no longer opens a mixed-map report. It first presents one card per map
actually present in the opponent corpus. Selecting a card opens a stratbook scoped to exactly that
map.

Maps pinned into the report but excluded from deterministic analysis remain visible as disabled
cards with a plain-language readiness message. They are not hidden and cannot open a misleading
empty report.

Each card uses the pinned Valve overview extracted from the user's installed CS2 client. No remote
image service, scraped screenshot or guessed fallback map is introduced. When a supported image is
not installed, the card remains usable with a neutral visual placeholder.

## Scope boundary

The selected map filters deterministic findings, coach recommendations and the individual player's
early movement chapter. Existing AI wording is displayed only when its pinned source belongs to the
selected map. Statistics are never recomputed in the template and evidence links still target the
original match, round and tick.

Advanced analyst mode intentionally retains an explicit all-map option for auditing. Full JSON,
print and PDF exports also remain complete corpus exports; the one-page cheat sheet is the existing
map-specific export surface.

An unknown or stale `map` query is rejected. It cannot silently produce an empty report that looks
like evidence of absence.
