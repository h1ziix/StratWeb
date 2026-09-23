"""Read-only product queries composed from existing evidence repositories."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from stratweb.application.canonical_models import (
    CanonicalPlayer,
    CanonicalTeam,
    PlayerTeamMembership,
)
from stratweb.application.persistence_models import MatchQueryFilters, StoredMatch
from stratweb.domain.enums import Side
from stratweb.exceptions import DatabaseInitializationError, MatchNotFoundError
from stratweb.ports import (
    AnalyticsRepository,
    MatchRepository,
    SpatialRepository,
    TeamNameRepository,
    TemporalRepository,
)
from stratweb.web.view_models import (
    HealthItemView,
    MatchLibraryItemView,
    MatchLibraryPageView,
    MatchOverviewView,
    PlayerSummaryView,
    RoundStripItemView,
    TeamScoreView,
)
from stratweb.web.view_models.product import ProductReadinessStatus


class ProductQueryService:
    """Build human-facing read models without changing evidence semantics."""

    def __init__(
        self,
        matches: MatchRepository,
        analytics: AnalyticsRepository,
        temporal: TemporalRepository,
        spatial: SpatialRepository,
        team_names: TeamNameRepository | None = None,
    ) -> None:
        self._matches = matches
        self._analytics = analytics
        self._temporal = temporal
        self._spatial = spatial
        self._team_names = team_names

    def list_matches(
        self,
        *,
        search: str = "",
        sort: str = "newest",
        page: int = 1,
        page_size: int = 24,
    ) -> MatchLibraryPageView:
        base_filters = MatchQueryFilters(search=search, sort=sort, limit=page_size)
        try:
            total_count = self._matches.count_matches(base_filters)
        except DatabaseInitializationError:
            self._matches.initialize()
            total_count = self._matches.count_matches(base_filters)
        page_count = max(1, (total_count + page_size - 1) // page_size)
        selected_page = min(page, page_count)
        filters = base_filters.model_copy(update={"offset": (selected_page - 1) * page_size})
        stored = self._matches.list_matches(filters)
        return MatchLibraryPageView(
            items=tuple(self._library_item(item) for item in stored),
            total_count=total_count,
            page=selected_page,
            page_size=page_size,
            page_count=page_count,
        )

    def overview(self, match_id: UUID) -> MatchOverviewView:
        stored = self._matches.get_match(match_id)
        if stored is None:
            raise MatchNotFoundError(f"Match not found: {match_id}")
        item = self._library_item(stored)
        rounds = self._matches.get_rounds(match_id)
        analytics_summary = self._analytics.get_summary(match_id)
        temporal_summary = self._temporal.get_summary(match_id)
        spatial_summary = self._spatial.get_summary(match_id)
        stats = (
            {row.player_id: row for row in self._analytics.list_player_stats(match_id)}
            if analytics_summary is not None
            else {}
        )
        players = tuple(
            PlayerSummaryView(
                player_id=player.player_id,
                name=player.current_name,
                kills=stats[player.player_id].kills if player.player_id in stats else None,
                deaths=stats[player.player_id].deaths if player.player_id in stats else None,
                assists=stats[player.player_id].assists if player.player_id in stats else None,
                adr=stats[player.player_id].adr if player.player_id in stats else None,
            )
            for player in self._matches.get_players(match_id)
        )
        opening_duels = (
            len(self._analytics.list_opening_duels(match_id)) if analytics_summary else 0
        )
        trades = len(self._analytics.list_trade_events(match_id)) if analytics_summary else 0
        plants = 0
        defuses = 0
        for round_item in rounds:
            events = self._matches.get_round_events(match_id, round_item.round_number)
            if events is None:
                continue
            for event in events.bomb_events:
                event_type = event.event_type.casefold()
                plants += int("plant" in event_type)
                defuses += int("defus" in event_type)
        health = (
            HealthItemView(label="Canonical", status="available", detail="Imported dataset"),
            HealthItemView(
                label="Analytics",
                status="available" if analytics_summary else "unavailable",
                detail=(
                    f"{analytics_summary.summary.players} player summaries"
                    if analytics_summary
                    else "Not computed"
                ),
            ),
            HealthItemView(
                label="Temporal",
                status="available" if temporal_summary else "unavailable",
                detail=(
                    f"Temporal {temporal_summary.temporal_rule_version}"
                    if temporal_summary
                    else "Not computed"
                ),
                href=f"/ui/temporal/{match_id}/diagnostics" if temporal_summary else None,
            ),
            HealthItemView(
                label="Spatial",
                status=(
                    spatial_summary.capabilities.positions.status.value
                    if spatial_summary
                    else "unavailable"
                ),
                detail=(
                    f"{spatial_summary.summary.requested_ticks} authoritative samples"
                    if spatial_summary
                    else "Not computed"
                ),
                href=f"/ui/matches/{match_id}/diagnostics" if spatial_summary else None,
            ),
        )
        team_order = tuple(team.team_id for team in item.teams)
        team_names = {team.team_id: team.name for team in item.teams}
        round_views = tuple(
            RoundStripItemView(
                round_number=row.round_number,
                winner=_physical_winner_label(row, team_names),
                score=_physical_round_score(row, team_order),
                complete=row.is_complete,
                map_href=(
                    f"/ui/spatial/{match_id}/rounds/{row.round_number}" if spatial_summary else None
                ),
                timeline_href=(
                    f"/ui/temporal/{match_id}/rounds/{row.round_number}"
                    if temporal_summary
                    else None
                ),
            )
            for row in rounds
        )
        developer = {
            "match_id": str(match_id),
            "dataset_fingerprint": stored.dataset_fingerprint,
            "parser": f"{stored.parser_name} {stored.parser_version}",
            "canonical": (
                f"schema {stored.canonical_schema_version} / rule "
                f"{stored.normalization_rule_version}"
            ),
        }
        if analytics_summary:
            developer["analytics"] = (
                f"schema {analytics_summary.analytics_schema_version} / rule "
                f"{analytics_summary.analytics_rule_version}"
            )
        if temporal_summary:
            developer["temporal_run_id"] = str(temporal_summary.temporal_run_id)
            developer["temporal"] = (
                f"schema {temporal_summary.temporal_schema_version} / rule "
                f"{temporal_summary.temporal_rule_version}"
            )
        if spatial_summary:
            developer["spatial_run_id"] = str(spatial_summary.spatial_run_id)
            developer["spatial"] = (
                f"schema {spatial_summary.spatial_schema_version} / rule "
                f"{spatial_summary.spatial_rule_version}"
            )
        return MatchOverviewView(
            match=item,
            rounds=round_views,
            players=players,
            health=health,
            opening_duels=opening_duels,
            trades=trades,
            plants=plants,
            defuses=defuses,
            developer_details=developer,
        )

    def _library_item(self, stored: StoredMatch) -> MatchLibraryItemView:
        match_id = stored.match_id
        teams = self._matches.get_teams(match_id)
        players = {item.player_id: item for item in self._matches.get_players(match_id)}
        memberships = self._matches.get_memberships(match_id)
        labels = (
            {item.team_id: item for item in self._team_names.list_for_match(match_id)}
            if self._team_names is not None
            else {}
        )
        rounds = self._matches.get_rounds(match_id)
        scores = _physical_scores(rounds)
        analytics = self._analytics.get_summary(match_id)
        temporal = self._temporal.get_summary(match_id)
        spatial = self._spatial.get_summary(match_id)
        warning_count = len(self._matches.get_validation_issues(match_id))
        warning_count += len(analytics.warnings) if analytics else 0
        warning_count += len(temporal.warnings) if temporal else 0
        warning_count += len(spatial.warnings) if spatial else 0
        analytics_status = "available" if analytics else "unavailable"
        temporal_status = "available" if temporal else "unavailable"
        spatial_status = spatial.capabilities.positions.status.value if spatial else "unavailable"
        readiness = _library_readiness(
            canonical_status="partial" if stored.validation_has_fatal_errors else "available",
            analytics_status=analytics_status,
            temporal_status=temporal_status,
            spatial_status=spatial_status,
            warning_count=warning_count,
        )
        return MatchLibraryItemView(
            match_id=match_id,
            short_id=str(match_id).split("-")[0],
            map_name=stored.map_name or "Unknown map",
            source_name=stored.source_original_name or stored.server_name or "Completed demo",
            imported_at=stored.imported_at,
            round_count=stored.round_count,
            teams=tuple(
                TeamScoreView(
                    team_id=team.team_id,
                    name=(
                        labels[team.team_id].display_name
                        if team.team_id in labels
                        else team.display_name or team.internal_name
                    ),
                    name_source=(
                        labels[team.team_id].source.value
                        if team.team_id in labels
                        else "demo"
                        if team.display_name
                        else "fallback"
                    ),
                    name_source_reference=(
                        labels[team.team_id].source_reference if team.team_id in labels else None
                    ),
                    player_names=_team_player_names(team, memberships, players),
                    score=scores.get(team.team_id),
                )
                for team in teams
            ),
            score_available=bool(scores) and all(team.team_id in scores for team in teams),
            canonical_status="partial" if stored.validation_has_fatal_errors else "available",
            analytics_status=analytics_status,
            temporal_status=temporal_status,
            spatial_status=spatial_status,
            warning_count=warning_count,
            **readiness,
        )


def _library_readiness(
    *,
    canonical_status: str,
    analytics_status: str,
    temporal_status: str,
    spatial_status: str,
    warning_count: int,
) -> dict[str, object]:
    """Return the explicit product-truth contract used by the match library."""

    layer_statuses = {
        "analytics": analytics_status,
        "temporal": temporal_status,
        "spatial": spatial_status,
    }
    missing_layers = tuple(
        layer for layer, status in layer_statuses.items() if status == "unavailable"
    )
    reasons: list[str] = []
    if canonical_status != "available":
        reasons.append("Структурная проверка импортированных данных не пройдена")
    labels = {
        "analytics": "Аналитика ещё не рассчитана",
        "temporal": "Хронология раундов ещё не рассчитана",
        "spatial": "Позиционные данные ещё не рассчитаны",
    }
    reasons.extend(labels[layer] for layer in missing_layers)
    if spatial_status in {"partial", "unreliable"}:
        reasons.append("Позиционные данные доступны не полностью")
    if warning_count and not reasons:
        reasons.append("Импорт или аналитические слои содержат предупреждения")

    if canonical_status != "available":
        status = ProductReadinessStatus.BLOCKED
        severity = "unavailable"
        label = "Нужна проверка"
        next_action = "Откройте диагностику матча и устраните ошибки структуры данных."
    elif reasons:
        status = ProductReadinessStatus.LIMITED
        severity = "partial"
        label = "Данные неполные"
        next_action = "Дождитесь расчёта отсутствующих слоёв или откройте диагностику матча."
    else:
        status = ProductReadinessStatus.READY
        severity = "available"
        label = "Данные и аналитика готовы"
        next_action = "Откройте разбор матча."
    return {
        "readiness_status": status,
        "readiness_severity": severity,
        "readiness_label": label,
        "readiness_reasons": tuple(reasons),
        "missing_layers": missing_layers,
        "next_action": next_action,
    }


def _team_player_names(
    team: CanonicalTeam,
    memberships: tuple[PlayerTeamMembership, ...],
    players: dict[UUID, CanonicalPlayer],
) -> tuple[str, ...]:
    player_ids = set(team.starting_player_ids)
    player_ids.update(item.player_id for item in memberships if item.team_id == team.team_id)
    return tuple(
        sorted(
            (players[player_id].current_name for player_id in player_ids if player_id in players),
            key=str.casefold,
        )
    )


def _physical_scores(rounds: tuple[object, ...]) -> dict[UUID, int]:
    result: dict[UUID, int] = {}
    for item in rounds:
        t_team_id = getattr(item, "t_team_id", None)
        ct_team_id = getattr(item, "ct_team_id", None)
        score_t = getattr(item, "score_t_after", None)
        score_ct = getattr(item, "score_ct_after", None)
        if t_team_id is not None and score_t is not None:
            result[t_team_id] = score_t
        if ct_team_id is not None and score_ct is not None:
            result[ct_team_id] = score_ct
    return result


def _physical_round_score(item: object, team_order: tuple[UUID, ...]) -> str:
    """Render one round score in stable physical-team order across side switches."""

    scores: dict[UUID, int] = {}
    t_team_id = getattr(item, "t_team_id", None)
    ct_team_id = getattr(item, "ct_team_id", None)
    score_t = getattr(item, "score_t_after", None)
    score_ct = getattr(item, "score_ct_after", None)
    if t_team_id is not None and score_t is not None:
        scores[t_team_id] = score_t
    if ct_team_id is not None and score_ct is not None:
        scores[ct_team_id] = score_ct
    if len(team_order) != 2 or any(team_id not in scores for team_id in team_order):
        return "—"
    return ":".join(str(scores[team_id]) for team_id in team_order)


def _physical_winner_label(item: object, team_names: dict[UUID, str]) -> str:
    """Name the physical winner while retaining the observed round side."""

    winner_side = getattr(item, "winner_side", None)
    if winner_side not in {Side.T, Side.CT}:
        return "—"
    winner_team_id = cast(
        UUID | None,
        (
            getattr(item, "t_team_id", None)
            if winner_side is Side.T
            else getattr(item, "ct_team_id", None)
        ),
    )
    team_name = team_names.get(winner_team_id) if winner_team_id is not None else None
    return f"{team_name} · {winner_side.value}" if team_name else winner_side.value
