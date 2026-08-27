# Stage 9.7 — Match Hub

## Goal

Make the match overview the obvious starting point for an ordinary player or coach. The first
screen should answer who played, what the score was and where to go next without showing internal
pipeline status, raw counters or a wall of buttons.

## Product experience

- One hero with map atmosphere, teams, score and a single primary action.
- Three core destinations: rounds, verified game facts and economy.
- One click per round. The hub prefers the available 2D view, then the compatible timeline.
- Team rosters are readable cards; exact player statistics are one disclosure deeper.
- Team-name editing, opponent-profile linking, event counters and technical lineage remain
  available under service settings.
- Match navigation shows Overview, Map and Timeline; secondary destinations live under “More”.
- Desktop and phone layouts share the same information order and respect reduced motion.

## Deterministic contract

`MatchHubView` is a versioned presentation projection (`1.0.0`) over existing persisted summary
availability. Economy and feature cards are marked ready only when persisted summaries exist.
Missing values remain unavailable. The hub never calculates statistics, selects tactics or fills
evidence gaps.

## Non-goals

- No demo parser or event-normalization changes.
- No new analytics or recommendation rules.
- No DuckDB migration or API response changes.
- No LLM-generated text.
