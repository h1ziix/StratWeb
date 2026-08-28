"""Deterministic team display-name inference from completed-demo evidence."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from uuid import UUID

from stratweb.application.canonical_models import CanonicalPlayer, CanonicalRound, CanonicalTeam
from stratweb.application.normalization_utils import optional_text, stable_rows, value
from stratweb.application.round_assignment import RoundAssignmentService
from stratweb.contracts import ParsedDemo

TEAM_NAME_INFERENCE_RULE_VERSION = "1.0.0"

_ROUND_EVENT_PRECEDENCE = (
    "round_freeze_end",
    "round_start",
    "round_poststart",
    "round_prestart",
    "round_end",
)
_GENERIC_NAMES = {
    "ct",
    "counter-terrorist",
    "counter-terrorists",
    "counterterrorist",
    "counterterrorists",
    "t",
    "terrorist",
    "terrorists",
    "teamalpha",
    "teambravo",
    "unknown",
    "unassigned",
}
_BRACKET_TAG = re.compile(r"^\[([A-Za-z0-9_-]{2,12})\]")
_SEPARATOR_TAG = re.compile(r"^([A-Za-z0-9_-]{2,12})\s*[|:]\s*")
_NUMBERED_TEAM_PLACEHOLDER = re.compile(r"^team[_ -]?\d+$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TeamNameInference:
    team_id: UUID
    display_name: str | None
    source: str | None
    numerator: int
    denominator: int
    frequency: float | None
    limitations: tuple[str, ...] = ()


def apply_inferred_team_names(
    parsed: ParsedDemo,
    teams: tuple[CanonicalTeam, ...],
    rounds: tuple[CanonicalRound, ...],
    players: tuple[CanonicalPlayer, ...],
) -> tuple[CanonicalTeam, ...]:
    """Apply only names supported by stable round evidence or a roster-majority tag."""

    inferences = {item.team_id: item for item in infer_team_names(parsed, teams, rounds, players)}
    result: list[CanonicalTeam] = []
    for team in teams:
        inference = inferences[team.team_id]
        if inference.display_name is None or inference.source is None:
            result.append(team)
            continue
        provenance = (
            "team_display_name_inferred: "
            f"source={inference.source}; support={inference.numerator}/{inference.denominator}; "
            f"rule={TEAM_NAME_INFERENCE_RULE_VERSION}"
        )
        result.append(
            team.model_copy(
                update={
                    "display_name": inference.display_name,
                    "warnings": tuple(dict.fromkeys((*team.warnings, provenance))),
                }
            )
        )
    return tuple(result)


def infer_team_names(
    parsed: ParsedDemo,
    teams: tuple[CanonicalTeam, ...],
    rounds: tuple[CanonicalRound, ...],
    players: tuple[CanonicalPlayer, ...],
) -> tuple[TeamNameInference, ...]:
    assignment = RoundAssignmentService(rounds)
    rounds_by_number = {item.round_number: item for item in rounds}
    # One candidate per physical team and round. Lower rank is a more reliable event source.
    observations: dict[tuple[UUID, int], tuple[int, set[str]]] = {}
    for rank, event_name in enumerate(_ROUND_EVENT_PRECEDENCE):
        for row in stable_rows(event_name, parsed.tables.get(event_name)):
            if row.tick is None:
                continue
            assigned = assignment.assign(row.tick)
            if assigned.round_number is None:
                continue
            round_item = rounds_by_number.get(assigned.round_number)
            if round_item is None:
                continue
            for team_id, aliases in (
                (round_item.t_team_id, ("t_team_clan_name", "t_clan_name")),
                (round_item.ct_team_id, ("ct_team_clan_name", "ct_clan_name")),
            ):
                if team_id is None:
                    continue
                candidate = _normalized_demo_name(value(row.data, *aliases))
                if candidate is None:
                    continue
                key = (team_id, round_item.round_number)
                current = observations.get(key)
                if current is None or rank < current[0]:
                    observations[key] = (rank, {candidate})
                elif rank == current[0]:
                    current[1].add(candidate)

    players_by_id = {item.player_id: item for item in players}
    team_votes: dict[UUID, Counter[str]] = defaultdict(Counter)
    for (team_id, _round_number), (_rank, candidates) in observations.items():
        if len(candidates) == 1:
            team_votes[team_id][next(iter(candidates))] += 1

    result: list[TeamNameInference] = []
    for team in sorted(teams, key=lambda item: str(item.team_id)):
        roster = tuple(
            players_by_id[player_id]
            for player_id in team.starting_player_ids
            if player_id in players_by_id
        )
        accepted = _majority_demo_name(team_votes[team.team_id], roster)
        if accepted is not None:
            display_name, numerator, denominator = accepted
            result.append(
                TeamNameInference(
                    team_id=team.team_id,
                    display_name=display_name,
                    source="round_team_clan_name",
                    numerator=numerator,
                    denominator=denominator,
                    frequency=numerator / denominator,
                )
            )
            continue
        nickname_tag = _majority_nickname_tag(roster)
        if nickname_tag is not None:
            tag, numerator, denominator = nickname_tag
            result.append(
                TeamNameInference(
                    team_id=team.team_id,
                    display_name=tag,
                    source="player_nickname_clan_tag",
                    numerator=numerator,
                    denominator=denominator,
                    frequency=numerator / denominator,
                    limitations=("Name inferred from an explicit tag shared by roster nicknames.",),
                )
            )
            continue
        denominator = sum(team_votes[team.team_id].values())
        result.append(
            TeamNameInference(
                team_id=team.team_id,
                display_name=None,
                source=None,
                numerator=0,
                denominator=denominator,
                frequency=None,
                limitations=("No unambiguous majority team name was present in the demo.",),
            )
        )
    return tuple(result)


def _majority_demo_name(
    votes: Counter[str],
    roster: tuple[CanonicalPlayer, ...],
) -> tuple[str, int, int] | None:
    denominator = sum(votes.values())
    if denominator == 0:
        return None
    ordered = sorted(votes.items(), key=lambda item: (-item[1], item[0].casefold(), item[0]))
    name, numerator = ordered[0]
    if len(ordered) > 1 and ordered[1][1] == numerator:
        return None
    if numerator / denominator < 0.6 or not _is_supported_demo_name(name, roster):
        return None
    return name, numerator, denominator


def _is_supported_demo_name(name: str, roster: tuple[CanonicalPlayer, ...]) -> bool:
    folded = name.casefold()
    if folded in _GENERIC_NAMES or folded.isdigit() or _NUMBERED_TEAM_PLACEHOLDER.fullmatch(name):
        return False
    if folded.startswith("team_"):
        suffix = folded.removeprefix("team_").strip()
        if not suffix or suffix.isdigit():
            return False
        known_names = {
            known.casefold()
            for player in roster
            for known in (player.current_name, *player.known_names)
        }
        return suffix in known_names
    return 2 <= len(name) <= 100


def _majority_nickname_tag(
    roster: tuple[CanonicalPlayer, ...],
) -> tuple[str, int, int] | None:
    denominator = len(roster)
    if denominator < 3:
        return None
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    for player in roster:
        tag = _nickname_tag(player.current_name)
        if tag is not None:
            spellings[tag.casefold()][tag] += 1
    if not spellings:
        return None
    ordered = sorted(
        ((folded, sum(values.values())) for folded, values in spellings.items()),
        key=lambda item: (-item[1], item[0]),
    )
    folded, numerator = ordered[0]
    if len(ordered) > 1 and ordered[1][1] == numerator:
        return None
    if numerator < 3 or numerator / denominator <= 0.5:
        return None
    spelling = sorted(spellings[folded].items(), key=lambda item: (-item[1], item[0]))[0][0]
    return spelling, numerator, denominator


def _nickname_tag(name: str) -> str | None:
    for pattern in (_BRACKET_TAG, _SEPARATOR_TAG):
        match = pattern.match(name.strip())
        if match is not None:
            tag = match.group(1)
            if tag.casefold() not in _GENERIC_NAMES:
                return tag
    return None


def _normalized_demo_name(raw: object) -> str | None:
    text = optional_text(raw)
    if text is None:
        return None
    normalized = " ".join(text.split())
    return normalized[:100] if normalized else None


__all__ = [
    "TEAM_NAME_INFERENCE_RULE_VERSION",
    "TeamNameInference",
    "apply_inferred_team_names",
    "infer_team_names",
]
