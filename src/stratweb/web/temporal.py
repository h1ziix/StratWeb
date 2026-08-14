"""Server-rendered Temporal 1.1 inspection UI and JSON endpoints."""

from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBTemporalRepository
from stratweb.application.temporal import TemporalQueryService
from stratweb.exceptions import TemporalNotFoundError, TemporalSnapshotError
from stratweb.temporal.models import (
    DeathEffectStatus,
    FinalStateStatus,
    IntermediateStateStatus,
    RoundSnapshot,
    RoundTimeline,
    SimultaneousEventGroup,
    SimultaneousOrderingStatus,
    TemporalDeathClassification,
    TemporalEvent,
    TemporalEventKind,
    TemporalRunRecord,
    TemporalRunSummary,
)
from stratweb.web.context import build_match_context
from stratweb.web.rendering import render_legacy_content

_DIAGNOSTIC_KINDS = {
    "simultaneous_groups": "Одновременные группы",
    "ambiguous_order_groups": "Группы с неоднозначным порядком",
    "ambiguous_intermediate_groups": "Группы с неоднозначным промежуточным состоянием",
    "ambiguous_final_groups": "Группы с неоднозначным финальным состоянием",
    "conflicting_groups": "Конфликтующие группы",
    "deaths_without_victim": "Смерти без установленной жертвы",
}


def temporal_ui_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    matches = DuckDBMatchRepository(database_path)

    def service() -> TemporalQueryService:
        return TemporalQueryService(DuckDBTemporalRepository(database_path))

    def player_labels(match_id: UUID) -> dict[UUID, str]:
        return {player.player_id: player.current_name for player in matches.get_players(match_id)}

    def match_context(match_id: UUID) -> dict[str, Any] | None:
        stored = matches.get_match(match_id)
        if stored is None:
            return None
        teams = matches.get_teams(match_id)
        rounds = matches.get_rounds(match_id)
        return build_match_context(stored, teams, rounds)

    @router.get("/ui/temporal/{match_id}", response_class=HTMLResponse, include_in_schema=False)
    def match_overview(match_id: UUID, run_id: UUID | None = None) -> HTMLResponse:
        query = service()
        summary = _summary(query, match_id, run_id)
        runs = _runs(query, match_id)
        selected = summary.temporal_run_id
        run_query = _run_query(selected)
        capabilities = _capability_cards(summary)
        rounds = "".join(
            f'<a class="round-link" href="/ui/temporal/{match_id}/rounds/{number}{run_query}">'
            f"Раунд {number}</a>"
            for number in range(1, summary.summary.rounds + 1)
        )
        content = f"""
        {_breadcrumbs(("Матчи", "/ui"), ("Хронология", None))}
        {_run_banner(summary)}
        <section class="hero compact">
          <p class="eyebrow">Хронология матча</p><h1>Раунды</h1>
          <p class="mono">отпечаток {escape(summary.temporal_fingerprint)}</p>
          <div class="actions">
            <a class="button" href="/ui/temporal/{match_id}/diagnostics{run_query}">Диагностика</a>
            <a class="button" href="/ui/spatial/{match_id}">Позиционные данные</a>
            <a class="button ghost" href="/api/temporal/{match_id}/summary{run_query}">JSON</a>
          </div>
        </section>
        <h2>Возможности</h2>{capabilities}
        <h2>Раунды</h2><div class="round-grid">{rounds}</div>
        <h2>Расчёты хронологии</h2>{_runs_table(runs, match_id)}
        """
        return HTMLResponse(_page(f"Temporal match {match_id}", content, match_context(match_id)))

    @router.get(
        "/ui/temporal/{match_id}/rounds/{round_number}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def round_timeline(
        match_id: UUID,
        round_number: int,
        run_id: UUID | None = None,
        show_raw_events: bool = False,
    ) -> HTMLResponse:
        query = service()
        summary = _summary(query, match_id, run_id)
        timeline = _timeline(query, match_id, round_number, summary.temporal_run_id)
        content = _round_page(
            summary,
            timeline,
            player_labels(match_id),
            show_raw_events=show_raw_events,
        )
        return HTMLResponse(_page(f"Round {round_number}", content, match_context(match_id)))

    @router.get(
        "/ui/temporal/{match_id}/rounds/{round_number}/events/{event_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def event_detail(
        match_id: UUID,
        round_number: int,
        event_id: UUID,
        run_id: UUID | None = None,
    ) -> HTMLResponse:
        query = service()
        summary = _summary(query, match_id, run_id)
        timeline = _timeline(query, match_id, round_number, summary.temporal_run_id)
        event = next((item for item in timeline.ordered_events if item.event_id == event_id), None)
        if event is None:
            raise HTTPException(status_code=404, detail="Temporal event not found in selected run")
        before: RoundSnapshot | None = None
        after: RoundSnapshot | None = None
        if not _is_legacy(summary):
            try:
                before, after = query.get_event_snapshots(
                    match_id, round_number, event_id, summary.temporal_run_id
                )
            except TemporalSnapshotError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        content = _event_page(summary, timeline, event, before, after, player_labels(match_id))
        return HTMLResponse(_page(f"Event {event_id}", content, match_context(match_id)))

    @router.get(
        "/ui/temporal/{match_id}/rounds/{round_number}/groups/{group_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def group_detail(
        match_id: UUID,
        round_number: int,
        group_id: UUID,
        run_id: UUID | None = None,
    ) -> HTMLResponse:
        query = service()
        summary = _summary(query, match_id, run_id)
        if _is_legacy(summary):
            raise HTTPException(
                status_code=409,
                detail="Simultaneous groups are unavailable for Temporal 1.0 runs",
            )
        timeline = _timeline(query, match_id, round_number, summary.temporal_run_id)
        group = next(
            (item for item in timeline.simultaneous_groups if item.group_id == group_id), None
        )
        if group is None:
            raise HTTPException(status_code=404, detail="Group not found in selected run")
        before = query.get_group_snapshot_before(
            match_id, round_number, group_id, summary.temporal_run_id
        )
        after = query.get_group_snapshot_after(
            match_id, round_number, group_id, summary.temporal_run_id
        )
        content = _group_page(summary, timeline, group, before, after, player_labels(match_id))
        return HTMLResponse(_page(f"Tick group {group.tick}", content, match_context(match_id)))

    @router.get(
        "/ui/temporal/{match_id}/rounds/{round_number}/snapshots/{tick}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def tick_snapshot(
        match_id: UUID,
        round_number: int,
        tick: int,
        run_id: UUID | None = None,
    ) -> HTMLResponse:
        query = service()
        summary = _summary(query, match_id, run_id)
        if _is_legacy(summary):
            snapshot_html = _legacy_snapshot_card("Состояние после тика")
        else:
            snapshot = query.get_tick_snapshot(
                match_id, round_number, tick, summary.temporal_run_id
            )
            snapshot_html = _snapshot_card("Состояние после тика", snapshot)
        content = f"""
        {_round_breadcrumbs(summary, round_number, f"Снимок на тике {tick}")}
        {_run_banner(summary)}<h1>Снимок на тике {tick}</h1>
        <p class="notice">Снимок на тике означает состояние после всей группы событий этого тика.</p>
        {snapshot_html}
        """
        return HTMLResponse(_page(f"Snapshot {tick}", content, match_context(match_id)))

    @router.get(
        "/ui/temporal/{match_id}/rounds/{round_number}/final",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def final_snapshot(
        match_id: UUID,
        round_number: int,
        run_id: UUID | None = None,
    ) -> HTMLResponse:
        query = service()
        summary = _summary(query, match_id, run_id)
        if _is_legacy(summary):
            snapshot_html = _legacy_snapshot_card("Финальное состояние раунда")
        else:
            snapshot = query.get_final_snapshot(match_id, round_number, summary.temporal_run_id)
            snapshot_html = _snapshot_card("Финальное состояние раунда", snapshot)
        content = f"""
        {_round_breadcrumbs(summary, round_number, "Финальный снимок")}
        {_run_banner(summary)}<h1>Финальный снимок раунда</h1>{snapshot_html}
        """
        return HTMLResponse(
            _page(
                f"Final snapshot round {round_number}",
                content,
                match_context(match_id),
            )
        )

    @router.get(
        "/ui/temporal/{match_id}/diagnostics",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def diagnostics(match_id: UUID, run_id: UUID | None = None) -> HTMLResponse:
        query = service()
        summary = _summary(query, match_id, run_id)
        items = _collect_diagnostics(query, summary)
        content = _diagnostics_page(summary, _runs(query, match_id), items)
        return HTMLResponse(_page("Temporal diagnostics", content, match_context(match_id)))

    @router.get(
        "/ui/temporal/{match_id}/diagnostics/{kind}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def diagnostic_list(match_id: UUID, kind: str, run_id: UUID | None = None) -> HTMLResponse:
        if kind not in _DIAGNOSTIC_KINDS:
            raise HTTPException(status_code=404, detail="Unknown diagnostic counter")
        query = service()
        summary = _summary(query, match_id, run_id)
        items = _collect_diagnostics(query, summary)[kind]
        content = _diagnostic_list_page(summary, kind, items)
        return HTMLResponse(_page(_DIAGNOSTIC_KINDS[kind], content, match_context(match_id)))

    @router.get("/api/temporal/{match_id}/summary", tags=["temporal-ui"])
    def api_summary(match_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        query = service()
        summary = _summary(query, match_id, run_id)
        return {
            "selected_run": summary.model_dump(mode="json"),
            "runs": [item.model_dump(mode="json") for item in _runs(query, match_id)],
        }

    @router.get("/api/temporal/{match_id}/rounds/{round_number}", tags=["temporal-ui"])
    def api_round(match_id: UUID, round_number: int, run_id: UUID | None = None) -> dict[str, Any]:
        query = service()
        summary = _summary(query, match_id, run_id)
        timeline = _timeline(query, match_id, round_number, summary.temporal_run_id)
        if _is_legacy(summary):
            timeline = timeline.model_copy(update={"simultaneous_groups": ()})
        return {
            "temporal_run_id": str(summary.temporal_run_id),
            "temporal_schema_version": summary.temporal_schema_version,
            "temporal_rule_version": summary.temporal_rule_version,
            "timeline": timeline.model_dump(mode="json"),
        }

    @router.get("/api/temporal/{match_id}/diagnostics", tags=["temporal-ui"])
    def api_diagnostics(match_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        query = service()
        summary = _summary(query, match_id, run_id)
        items = _collect_diagnostics(query, summary)
        return {
            "temporal_run_id": str(summary.temporal_run_id),
            "versions": {
                "schema": summary.temporal_schema_version,
                "rule": summary.temporal_rule_version,
            },
            "capabilities": summary.summary.availability.model_dump(mode="json"),
            "warnings": summary.warnings,
            "counters": {key: len(value) for key, value in items.items()},
            "items": items,
            "runs": [item.model_dump(mode="json") for item in _runs(query, match_id)],
        }

    return router


def _summary(
    service: TemporalQueryService, match_id: UUID, run_id: UUID | None
) -> TemporalRunSummary:
    try:
        return service.get_temporal_run_summary(match_id, run_id)
    except TemporalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _runs(service: TemporalQueryService, match_id: UUID) -> tuple[TemporalRunRecord, ...]:
    try:
        return service.list_temporal_runs(match_id)
    except TemporalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _timeline(
    service: TemporalQueryService,
    match_id: UUID,
    round_number: int,
    run_id: UUID,
) -> RoundTimeline:
    try:
        return service.get_round_timeline(match_id, round_number, run_id)
    except TemporalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _round_page(
    summary: TemporalRunSummary,
    timeline: RoundTimeline,
    player_labels: dict[UUID, str],
    *,
    show_raw_events: bool = False,
) -> str:
    run_query = _run_query(summary.temporal_run_id)
    events_by_tick: dict[int, list[TemporalEvent]] = defaultdict(list)
    for event in timeline.ordered_events:
        events_by_tick[event.time.tick].append(event)
    groups_by_tick = (
        {} if _is_legacy(summary) else {item.tick: item for item in timeline.simultaneous_groups}
    )
    opening = next(
        (
            item.event_id
            for item in timeline.ordered_events
            if item.combat_death_classification is TemporalDeathClassification.ENEMY
        ),
        None,
    )
    grouped_event_ids = {
        event_id for group in timeline.simultaneous_groups for event_id in group.ordered_event_ids
    }
    displayed_by_tick = {
        tick: tuple(
            event
            for event in events
            if show_raw_events
            or _is_significant_event(event)
            or event.event_id in grouped_event_ids
        )
        for tick, events in events_by_tick.items()
    }
    displayed_by_tick = {tick: events for tick, events in displayed_by_tick.items() if events}
    hidden_count = len(timeline.ordered_events) - sum(
        len(events) for events in displayed_by_tick.values()
    )
    buckets = "".join(
        _tick_bucket(
            summary,
            timeline,
            tick,
            tuple(events),
            groups_by_tick.get(tick),
            opening,
            player_labels,
        )
        for tick, events in sorted(displayed_by_tick.items())
    )
    fallback = (
        '<span class="badge warning">резервное завершение</span>'
        if timeline.end_source and timeline.end_source.startswith("fallback:")
        else ""
    )
    return f"""
    {_round_breadcrumbs(summary, timeline.round_number, None)}
    {_run_banner(summary)}
    <section class="hero compact"><p class="eyebrow">Хронология раунда</p>
      <h1>Раунд {timeline.round_number} {fallback}</h1>
      <p>начало {timeline.start_tick} · live {timeline.live_start_tick} · конец
      {timeline.effective_end_tick} · источник {escape(str(timeline.end_source))}</p>
      <div class="actions"><a class="button" href="/ui/temporal/{summary.match_id}/rounds/{timeline.round_number}/final{run_query}">Финальный снимок</a></div>
    </section>
    <div class="notice">По умолчанию показаны значимые события. Малозначимых событий свёрнуто: {hidden_count}; они не удалены.
    <a href="/ui/temporal/{summary.match_id}/rounds/{timeline.round_number}{run_query}{"&" if "?" in run_query else "?"}show_raw_events={"false" if show_raw_events else "true"}">
    {"Скрыть все исходные события" if show_raw_events else "Показать все исходные события"}</a></div>
    <div class="timeline">{buckets}</div>
    """


def _is_significant_event(event: TemporalEvent) -> bool:
    return event.kind in {
        TemporalEventKind.PHASE_BOUNDARY,
        TemporalEventKind.DEATH,
        TemporalEventKind.BOMB,
        TemporalEventKind.ROUND_END,
        TemporalEventKind.OFFICIAL_END,
        TemporalEventKind.FALLBACK_END,
    }


def _tick_bucket(
    summary: TemporalRunSummary,
    timeline: RoundTimeline,
    tick: int,
    events: tuple[TemporalEvent, ...],
    group: SimultaneousEventGroup | None,
    opening_event_id: UUID | None,
    player_labels: dict[UUID, str],
) -> str:
    event_rows = "".join(
        _event_row(
            summary,
            timeline,
            event,
            event.event_id == opening_event_id,
            player_labels,
        )
        for event in events
    )
    snapshot_link = (
        f"/ui/temporal/{summary.match_id}/rounds/{timeline.round_number}/snapshots/{tick}"
        f"{_run_query(summary.temporal_run_id)}"
    )
    if group is None:
        bucket_note = (
            '<span class="muted">События одного тика; неоднозначности состояния нет.</span>'
            if len(events) > 1
            else ""
        )
        return f"""
        <section class="tick-bucket"><div class="tick-marker">тик {tick}</div>
          <div class="tick-card"><div class="tick-heading"><strong>событий: {len(events)}</strong>
          <span><a href="{snapshot_link}">снимок после тика</a> ·
          <a href="/ui/spatial/{summary.match_id}/rounds/{timeline.round_number}?tick={tick}">2D-карта</a></span></div>{bucket_note}
          <div class="events">{event_rows}</div></div></section>
        """
    group_link = (
        f"/ui/temporal/{summary.match_id}/rounds/{timeline.round_number}/groups/{group.group_id}"
        f"{_run_query(summary.temporal_run_id)}"
    )
    intermediate = _possible_states(group, player_labels)
    return f"""
    <section class="tick-bucket group"><div class="tick-marker">тик {tick}</div>
      <div class="tick-card group-card">
        <div class="tick-heading"><strong>Одновременная группа · событий тика: {len(events)} · событий состояния: {group.event_count}</strong>
          <a href="{group_link}">открыть группу</a></div>
        <div class="status-row">
          {_status_badge("ordering", group.ordering_status.value)}
          {_status_badge("intermediate", group.intermediate_state_status.value)}
          {_status_badge("final", group.final_state_status.value)}
        </div>
        <p><b>Игроки:</b> {", ".join(_player_label(item, player_labels) for item in group.involved_player_ids) or "не подтверждены"}</p>
        <p><b>Причины неоднозначности:</b> {", ".join(map(escape, group.ambiguity_reasons)) or "нет"}</p>
        {_projection_pair(group)}
        {intermediate}
        <p class="notice">События произошли в одном тике. Их физический порядок не определяется по event ID.</p>
        <div class="events simultaneous">{event_rows}</div>
        <a href="{snapshot_link}">Снимок после всей группы</a> ·
        <a href="/ui/spatial/{summary.match_id}/rounds/{timeline.round_number}?tick={tick}">2D-карта</a>
      </div></section>
    """


def _event_row(
    summary: TemporalRunSummary,
    timeline: RoundTimeline,
    event: TemporalEvent,
    opening: bool,
    player_labels: dict[UUID, str],
) -> str:
    link = (
        f"/ui/temporal/{summary.match_id}/rounds/{timeline.round_number}/events/{event.event_id}"
        f"{_run_query(summary.temporal_run_id)}"
    )
    victimless = (
        event.kind is TemporalEventKind.DEATH
        and event.death_effect_status is DeathEffectStatus.UNAVAILABLE
    )
    if victimless:
        label = "Смерть от мира / жертва не установлена"
    else:
        label = event.event_type
    badges = []
    if opening:
        badges.append('<span class="badge accent">первое событие</span>')
    if victimless:
        badges.append('<span class="badge warning">диагностика: нет жертвы</span>')
    if event.kind is TemporalEventKind.BOMB and event.event_type == "bomb:planted":
        badges.append('<span class="badge bomb">установка</span>')
    return f"""
    <a class="event-row {"victimless" if victimless else ""}" href="{link}">
      <span><b>{escape(label)}</b> {"".join(badges)}</span>
      <details><summary>Технические данные</summary><code>{escape(str(event.event_id))}</code></details>
      <span>участник {_optional_player_label(event.actor_player_id, player_labels)} · жертва
      {_optional_player_label(event.victim_player_id, player_labels)}</span>
    </a>
    """


def _event_page(
    summary: TemporalRunSummary,
    timeline: RoundTimeline,
    event: TemporalEvent,
    before: RoundSnapshot | None,
    after: RoundSnapshot | None,
    player_labels: dict[UUID, str],
) -> str:
    victimless = (
        event.kind is TemporalEventKind.DEATH
        and event.death_effect_status is DeathEffectStatus.UNAVAILABLE
    )
    heading = "Смерть от мира / жертва не установлена" if victimless else event.event_type
    diagnostic = (
        """
        <div class="notice warning"><b>Жертва не установлена.</b> Событие остаётся доказательством,
        не привязывается к игроку, не изменяет число живых и попадает в диагностику.
        Жертва не додумывается.</div>
        """
        if victimless
        else ""
    )
    snapshots = (
        f"{_snapshot_card('До события', before)}{_snapshot_card('После события', after)}"
        if before is not None and after is not None
        else f"{_legacy_snapshot_card('До события')}{_legacy_snapshot_card('После события')}"
    )
    return f"""
    {_round_breadcrumbs(summary, timeline.round_number, "Событие")}
    {_run_banner(summary)}<h1>{escape(heading)}</h1>{diagnostic}
    <dl class="facts">
      <dt>тик</dt><dd>{event.time.tick}</dd><dt>источник</dt><dd>{escape(event.source_event)}</dd>
      <dt>участник</dt><dd>{_optional_player_label(event.actor_player_id, player_labels)}</dd>
      <dt>жертва</dt><dd>{_optional_player_label(event.victim_player_id, player_labels)}</dd>
      <dt>классификация боя</dt><dd>{escape(str(event.combat_death_classification or "нет"))}</dd>
      <dt>влияние смерти</dt><dd>{escape(str(event.death_effect_status or "нет"))}</dd>
      <dt>одновременная группа</dt><dd>{escape(str(event.simultaneous_group_id or "нет"))}</dd>
    </dl>
    <p><a class="button" href="/ui/spatial/{summary.match_id}/rounds/{timeline.round_number}?tick={event.time.tick}">Открыть 2D-карту на тике {event.time.tick}</a></p>
    <div class="snapshot-grid">{snapshots}</div>
    """


def _group_page(
    summary: TemporalRunSummary,
    timeline: RoundTimeline,
    group: SimultaneousEventGroup,
    before: RoundSnapshot,
    after: RoundSnapshot,
    player_labels: dict[UUID, str],
) -> str:
    event_by_id = {item.event_id: item for item in timeline.ordered_events}
    events = "".join(
        _event_row(summary, timeline, event_by_id[event_id], False, player_labels)
        for event_id in group.ordered_event_ids
    )
    return f"""
    {_round_breadcrumbs(summary, timeline.round_number, f"Группа на тике {group.tick}")}
    {_run_banner(summary)}<h1>Одновременная группа · тик {group.tick}</h1>
    <div class="status-row">{_status_badge("ordering", group.ordering_status.value)}
    {_status_badge("intermediate", group.intermediate_state_status.value)}
    {_status_badge("final", group.final_state_status.value)}</div>
    <p><b>Событий: {group.event_count}.</b> Игроки: {", ".join(_player_label(item, player_labels) for item in group.involved_player_ids)}</p>
    <p>Причины неоднозначности: {", ".join(map(escape, group.ambiguity_reasons)) or "нет"}</p>
    <div class="snapshot-grid">{_snapshot_card("До группы тика", before)}{_snapshot_card("После группы тика", after)}</div>
    {_possible_states(group, player_labels)}
    <h2>События одного тика — без выдуманного порядка</h2>
    <p class="notice">Порядок событий внутри тика не доказан. Единственный промежуточный порядок не рисуется.</p>
    <div class="events simultaneous">{events}</div>
    """


def _snapshot_card(title: str, snapshot: RoundSnapshot) -> str:
    possible = ""
    if snapshot.possible_states:
        possible = (
            '<div class="possible"><b>Возможные состояния</b>'
            + "".join(
                f"<span>{item.t_alive}T / {item.ct_alive}CT · погибло {len(item.dead_players)}</span>"
                for item in snapshot.possible_states
            )
            + "</div>"
        )
    reasons = ", ".join(item.value for item in snapshot.unavailable_reasons)
    return f"""
    <article class="snapshot {escape(snapshot.state_status.value)}"><h3>{escape(title)}</h3>
      {_status_badge("state", snapshot.state_status.value)}
      <p class="alive-count"><strong>{snapshot.t_alive}T</strong> / <strong>{snapshot.ct_alive}CT</strong></p>
      <p>фаза {escape(snapshot.phase.value)} · бомба {escape(snapshot.bomb_state.value)}</p>
      {f'<p class="warning-text">{escape(reasons)}</p>' if reasons else ""}{possible}
    </article>
    """


def _legacy_snapshot_card(title: str) -> str:
    return f"""
    <article class="snapshot unavailable"><h3>{escape(title)}</h3>
      {_status_badge("state", "unavailable")}
      <p class="warning-text">Temporal 1.0 не подтверждает семантику групп тика и снимков отдельных событий Temporal 1.1.
      Пересчитайте матч с Temporal 1.1.</p>
    </article>
    """


def _possible_states(group: SimultaneousEventGroup, player_labels: dict[UUID, str]) -> str:
    if group.intermediate_state_status is IntermediateStateStatus.DETERMINISTIC:
        return '<p class="notice good">Промежуточное состояние детерминировано.</p>'
    if not group.possible_intermediate_states:
        return '<p class="notice warning">Порядок событий внутри tick не доказан.</p>'
    cards = "".join(
        f"<article><b>Вариант {index}</b><span>{state.t_alive}T / {state.ct_alive}CT</span>"
        f"<small>кандидат на первую смерть: "
        f"{', '.join(_player_label(item, player_labels) for item in state.dead_players if item not in group.pre_group_state.dead_players) or 'не подтверждено'}"
        f"</small></article>"
        for index, state in enumerate(group.possible_intermediate_states, start=1)
    )
    return f'<div class="possible-states"><h3>Возможные промежуточные состояния</h3>{cards}</div>'


def _projection_pair(group: SimultaneousEventGroup) -> str:
    pre = group.pre_group_state
    if group.post_group_state is None:
        post = '<span class="unavailable-text">состояние после группы не детерминировано</span>'
    else:
        post = f"<strong>{group.post_group_state.t_alive}T / {group.post_group_state.ct_alive}CT</strong>"
    return f'<div class="state-flow"><strong>{pre.t_alive}T / {pre.ct_alive}CT</strong><span>→ вся группа →</span>{post}</div>'


def _capability_cards(summary: TemporalRunSummary) -> str:
    availability = summary.summary.availability
    selected = (
        ("Состояние группы тика", availability.tick_group_state),
        ("Состояние отдельных событий", availability.per_event_state),
        ("Промежуточный порядок", availability.intermediate_ordering),
        ("Финальное число живых", availability.final_alive_state),
    )
    return (
        '<div class="capability-grid">'
        + "".join(
            f'<article class="capability {item.status.value}"><span>{escape(label)}</span>'
            f"<strong>{escape(item.status.value)}</strong><small>{item.covered}/{item.population}</small>"
            f"<small>{escape(', '.join(reason.value for reason in item.reasons))}</small></article>"
            for label, item in selected
        )
        + "</div>"
    )


def _collect_diagnostics(
    service: TemporalQueryService, summary: TemporalRunSummary
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {key: [] for key in _DIAGNOSTIC_KINDS}
    for round_number in range(1, summary.summary.rounds + 1):
        timeline = service.get_round_timeline(
            summary.match_id, round_number, summary.temporal_run_id
        )
        groups = () if _is_legacy(summary) else timeline.simultaneous_groups
        for group in groups:
            item = _group_diagnostic(summary, timeline, group)
            result["simultaneous_groups"].append(item)
            if group.ordering_status is SimultaneousOrderingStatus.AMBIGUOUS_ORDER:
                result["ambiguous_order_groups"].append(item)
            if group.intermediate_state_status is IntermediateStateStatus.AMBIGUOUS:
                result["ambiguous_intermediate_groups"].append(item)
            if group.final_state_status is FinalStateStatus.AMBIGUOUS:
                result["ambiguous_final_groups"].append(item)
            if (
                group.ordering_status is SimultaneousOrderingStatus.CONFLICTING
                or group.final_state_status is FinalStateStatus.CONFLICTING
            ):
                result["conflicting_groups"].append(item)
        for event in timeline.ordered_events:
            if event.death_effect_status is DeathEffectStatus.UNAVAILABLE:
                result["deaths_without_victim"].append(
                    {
                        "round_number": round_number,
                        "tick": event.time.tick,
                        "event_ids": [str(event.event_id)],
                        "label": "Victim not proven; alive state unchanged",
                        "href": (
                            f"/ui/temporal/{summary.match_id}/rounds/{round_number}/events/"
                            f"{event.event_id}{_run_query(summary.temporal_run_id)}"
                        ),
                    }
                )
    return result


def _group_diagnostic(
    summary: TemporalRunSummary,
    timeline: RoundTimeline,
    group: SimultaneousEventGroup,
) -> dict[str, Any]:
    return {
        "round_number": timeline.round_number,
        "tick": group.tick,
        "event_ids": [str(item) for item in group.ordered_event_ids],
        "label": (
            f"{group.ordering_status.value}; {group.intermediate_state_status.value}; "
            f"{group.final_state_status.value}"
        ),
        "href": (
            f"/ui/temporal/{summary.match_id}/rounds/{timeline.round_number}/groups/"
            f"{group.group_id}{_run_query(summary.temporal_run_id)}"
        ),
    }


def _diagnostics_page(
    summary: TemporalRunSummary,
    runs: tuple[TemporalRunRecord, ...],
    items: dict[str, list[dict[str, Any]]],
) -> str:
    counters = "".join(
        f'<a class="counter" href="/ui/temporal/{summary.match_id}/diagnostics/{kind}'
        f'{_run_query(summary.temporal_run_id)}"><span>{escape(label)}</span>'
        f"<strong>{len(items[kind])}</strong></a>"
        for kind, label in _DIAGNOSTIC_KINDS.items()
    )
    warnings = "".join(f"<li>{escape(item)}</li>" for item in summary.warnings) or "<li>Нет</li>"
    return f"""
    {_breadcrumbs(("Хронология матча", f"/ui/temporal/{summary.match_id}{_run_query(summary.temporal_run_id)}"), ("Диагностика", None))}
    {_run_banner(summary)}<h1>Диагностика</h1>{_capability_cards(summary)}
    <div class="counter-grid">{counters}</div>
    <h2>Предупреждения</h2><ul class="warnings">{warnings}</ul>
    <h2>Расчёты</h2>{_runs_table(runs, summary.match_id)}
    """


def _diagnostic_list_page(
    summary: TemporalRunSummary, kind: str, items: list[dict[str, Any]]
) -> str:
    rows = (
        "".join(
            f'<a class="diagnostic-row" href="{escape(str(item["href"]))}">'
            f"<strong>Раунд {item['round_number']} · тик {item['tick']}</strong>"
            f"<span>{escape(str(item['label']))}</span>"
            f"<small>{escape(', '.join(item['event_ids']))}</small></a>"
            for item in items
        )
        or '<p class="notice good">В этом расчёте таких диагностических записей нет.</p>'
    )
    return f"""
    {_breadcrumbs(("Диагностика", f"/ui/temporal/{summary.match_id}/diagnostics{_run_query(summary.temporal_run_id)}"), (_DIAGNOSTIC_KINDS[kind], None))}
    {_run_banner(summary)}<h1>{escape(_DIAGNOSTIC_KINDS[kind])}</h1>
    <p>Записей в выбранном расчёте: {len(items)}.</p><div class="diagnostic-list">{rows}</div>
    """


def _runs_table(runs: tuple[TemporalRunRecord, ...], match_id: UUID) -> str:
    rows = "".join(
        f"<tr><td>{escape(item.temporal_schema_version)}</td><td>{escape(item.temporal_rule_version)}</td>"
        f'<td class="mono">{escape(str(item.temporal_run_id))}</td>'
        f"<td>{escape(item.created_at.isoformat(sep=' ', timespec='seconds'))}</td>"
        f"<td>{_run_status(item)}</td>"
        f"<td>{_run_link(item, match_id)}</td></tr>"
        for item in runs
    )
    return f'<div class="table-wrap"><table><thead><tr><th>Схема</th><th>Правило</th><th>ID расчёта</th><th>Создан</th><th>Статус</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>'


def _run_banner(summary: TemporalRunSummary) -> str:
    legacy = summary.temporal_schema_version == "1.0.0"
    message = (
        "Устаревший расчёт Temporal 1.0. Классификация одновременных групп недоступна; "
        "данные Temporal 1.1 на этой странице не смешиваются."
        if legacy
        else "Выбран расчёт Temporal 1.1. Все страницы и ссылки закреплены за этим ID расчёта."
    )
    return f"""
    <div class="run-banner {"legacy" if legacy else "current"}">
      <b>Схема {escape(summary.temporal_schema_version)} · правило {escape(summary.temporal_rule_version)}</b>
      <span>{escape(message)}</span><code>{escape(str(summary.temporal_run_id))}</code>
    </div>
    """


def _run_status(run: TemporalRunRecord) -> str:
    if run.selected_by_default:
        return "текущий по умолчанию" if not run.legacy else "резервный устаревший"
    if run.legacy:
        return "совместимый устаревший"
    return "совместимый" if run.compatible else "несовместимый"


def _run_link(run: TemporalRunRecord, match_id: UUID) -> str:
    if not run.compatible:
        return '<span class="muted">нельзя открыть в этой версии</span>'
    return f'<a href="/ui/temporal/{match_id}?run_id={run.temporal_run_id}">открыть отдельно</a>'


def _is_legacy(summary: TemporalRunSummary) -> bool:
    return summary.temporal_schema_version == "1.0.0" and summary.temporal_rule_version == "1.0.0"


def _player_label(player_id: UUID, labels: dict[UUID, str]) -> str:
    name = labels.get(player_id)
    if name is None:
        return "Игрок без подтверждённого имени"
    return escape(name)


def _optional_player_label(player_id: UUID | None, labels: dict[UUID, str]) -> str:
    return _player_label(player_id, labels) if player_id is not None else "не подтверждено"


def _status_badge(label: str, value: str) -> str:
    css = (
        "bad"
        if value in {"conflicting", "unresolved", "unavailable"}
        else ("warn" if value in {"ambiguous", "ambiguous_order", "partial"} else "good")
    )
    labels = {"ordering": "порядок", "intermediate": "промежуточное", "final": "финальное", "state": "состояние"}
    values = {"available": "доступно", "partial": "частично", "unavailable": "недоступно", "deterministic": "детерминировано", "ambiguous": "неоднозначно", "ambiguous_order": "порядок неоднозначен", "conflicting": "конфликт", "unresolved": "не разрешено"}
    return f'<span class="status {css}">{escape(labels.get(label, label))}: {escape(values.get(value, value))}</span>'


def _round_breadcrumbs(summary: TemporalRunSummary, round_number: int, leaf: str | None) -> str:
    values: list[tuple[str, str | None]] = [
        (
            "Хронология матча",
            f"/ui/temporal/{summary.match_id}{_run_query(summary.temporal_run_id)}",
        ),
        (
            f"Раунд {round_number}",
            None
            if leaf is None
            else f"/ui/temporal/{summary.match_id}/rounds/{round_number}{_run_query(summary.temporal_run_id)}",
        ),
    ]
    if leaf is not None:
        values.append((leaf, None))
    return _breadcrumbs(*values)


def _breadcrumbs(*values: tuple[str, str | None]) -> str:
    content = " / ".join(
        f'<a href="{escape(href)}">{escape(label)}</a>' if href else escape(label)
        for label, href in values
    )
    return f'<nav class="breadcrumbs">{content}</nav>'


def _run_query(run_id: UUID) -> str:
    return f"?run_id={run_id}"


def _page(title: str, content: str, match_context: dict[str, Any] | None = None) -> str:
    return render_legacy_content(title, content, match_context=match_context)
