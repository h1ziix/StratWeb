"use strict";

(() => {
  const config = JSON.parse(document.getElementById("spatialConfig").textContent);
  const initialChunk = JSON.parse(document.getElementById("initialChunk").textContent);
  window.StratWebSpatialRunId = config.spatial_run_id;
  const api = new window.StratWebApi();
  const prefetchApi = new window.StratWebApi();
  const renderer = new window.StratWebMapRenderer(
    document.getElementById("mapCanvas"),
    document.getElementById("eventCards"),
    config.label_roster || [],
  );
  const tickClock = new window.StratWebDemoTickClock.DemoTickClock(
    config.ticks,
    { tickDurationMs: config.playback_clock.tick_duration_ms },
  );
  const transientEvents = new window.StratWebEventBuffer.TransientEventBuffer({
    ttlMs: 120,
    limit: 32,
  });
  const UI_UPDATE_INTERVAL = 200;
  const PREFETCH_WALL_RESERVE_MS = 2500;
  const START_PLAYBACK_RESERVE_MS = 1200;
  const elementIds = [
    "scrubber", "sampleIndex", "playPause", "playbackMode", "playbackSpeed", "frameStatus",
    "tickStatus", "bufferStatus", "loadingState", "errorState", "errorMessage", "emptyState",
    "teamFilter", "playerFilter", "aliveFilter", "bombFilter", "roundSelect", "eventJump",
    "labelMode", "temporalLink", "jsonLink", "diagnosticsDrawer", "metricNodes", "metricFetches",
    "metricRender", "metricDropped", "metricBuffering", "metricRejected", "metricRepeated",
    "metricJumps", "metricProjectileSamples", "metricUtilityEffects", "mapStage", "mapCanvas",
    "developerCurrentTick", "developerNextTick", "developerProgress", "developerTickGap",
    "developerBuffered", "developerPending", "developerFps", "developerStale",
    "developerUnavailable", "developerRendered", "developerMaxRender", "developerApiMinute",
    "metricDom", "metricSvg", "metricSidebar", "metricEventList", "metricUpdatedNodes",
    "metricRecreatedNodes", "metricActivePlayers", "metricActiveProjectiles", "autoFocus",
    "metricClockCrossed", "metricClockMaxCrossed", "metricLabelPlans", "metricAnchorFlips",
    "selectedPlayerStatus", "currentEventStatus", "mapViewport", "selectedZoneBadge",
    "playerPathLink", "copyCs2Command", "cs2CommandStatus",
  ];
  const elements = Object.fromEntries(
    elementIds.map((id) => [id, document.getElementById(id)]),
  );

  const state = {
    index: config.initial_index,
    playing: false,
    buffering: false,
    starting: false,
    playRequest: 0,
    frameScheduled: false,
    mode: config.mode,
    speed: 1,
    bufferTargetIndex: null,
    chunkLimit: config.chunk_limit,
    samples: new Map(),
    ranges: [],
    pendingStarts: new Set(),
    generation: 0,
    projectiles: new Map(),
    projectileSamples: new Map(),
    projectileSeries: new Map(),
    projectileTrailPlans: new Map(),
    effects: new Map(),
    evidenceVersion: 0,
    lastDynamicEvidenceKey: "",
    diagnostics: initialChunk.diagnostics || {},
    renderDurations: [],
    domDurations: [],
    svgDurations: [],
    sidebarDurations: [],
    eventListDurations: [],
    updatedNodeCounts: [],
    renderedFrames: 0,
    maxRenderDuration: 0,
    recreatedNodes: 0,
    activePlayers: 0,
    activeProjectiles: 0,
    labelPlanBuilds: 0,
    labelAnchorChanges: 0,
    instantFps: 0,
    apiRequestTimes: [],
    droppedFrames: 0,
    bufferingCount: 0,
    crossedSamples: 0,
    maxCrossedSamplesPerFrame: 0,
    rejectedMarkers: 0,
    lastFrame: 0,
    lastUiUpdate: 0,
    profileSequence: 0,
    zoom: 1,
    panX: 0,
    panY: 0,
    dragging: false,
    dragStart: null,
    lastOverlayUpdate: 0,
    lastAutoFocusTick: null,
  };

  function setText(element, value) {
    if (!element) return;
    const next = String(value);
    if (element.textContent === next) return;
    if (element.childNodes.length === 1 && element.firstChild.nodeType === Node.TEXT_NODE) {
      element.firstChild.nodeValue = next;
    } else {
      element.textContent = next;
    }
  }

  function setAttribute(element, name, value) {
    const next = String(value);
    if (element && element.getAttribute(name) !== next) element.setAttribute(name, next);
  }

  function setHidden(element, hidden) {
    if (element && element.hidden !== hidden) element.hidden = hidden;
  }

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw new Error("Браузер не разрешил доступ к буферу обмена.");
  }

  async function copyCs2Commands() {
    const button = elements.copyCs2Command;
    const tick = config.ticks[state.index];
    if (!Number.isInteger(tick)) return;
    button.disabled = true;
    setText(button, "Подготавливаем демку…");
    elements.cs2CommandStatus.classList.remove("error");
    setText(elements.cs2CommandStatus, "Проверяем исходный файл и папку CS2.");
    try {
      const response = await fetch(
        `/api/matches/${config.match_id}/cs2-demo-command?tick=${tick}`,
        { method: "POST", headers: { Accept: "application/json" } },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `Ошибка подготовки (${response.status})`);
      await copyText(payload.clipboard_text);
      setText(
        elements.cs2CommandStatus,
        "Скопировано: вставьте первую строку в консоль CS2, дождитесь загрузки, затем вторую.",
      );
    } catch (error) {
      elements.cs2CommandStatus.classList.add("error");
      setText(elements.cs2CommandStatus, error.message);
    } finally {
      button.disabled = false;
      setText(button, "Скопировать команды CS2");
    }
  }

  function indexProjectileSamples(rows) {
    const touched = new Set();
    rows.forEach((item) => {
      if (state.projectileSamples.has(item.snapshot.snapshot_id)) return;
      state.projectileSamples.set(item.snapshot.snapshot_id, item);
      const id = item.projectile.projectile_id;
      const series = state.projectileSeries.get(id) || [];
      series.push(item);
      state.projectileSeries.set(id, series);
      touched.add(id);
    });
    touched.forEach((id) => {
      state.projectileSeries.get(id).sort((a, b) => a.snapshot.tick - b.snapshot.tick);
      state.projectileTrailPlans.set(id, buildTrailPlan(state.projectileSeries.get(id)));
    });
    if (touched.size) {
      state.evidenceVersion += 1;
      state.lastDynamicEvidenceKey = "";
    }
  }

  function addChunk(chunk, retentionIndex = state.index) {
    if (chunk.spatial_run_id !== config.spatial_run_id
        || chunk.temporal_run_id !== config.temporal_run_id) {
      throw new Error("Расчёт воспроизведения изменился. Обновите страницу после замены расчёта.");
    }
    chunk.samples.forEach((sample) => state.samples.set(sample.sample_index, sample));
    (chunk.projectiles || []).forEach((item) => state.projectiles.set(item.projectile_id, item));
    indexProjectileSamples(chunk.projectile_samples || []);
    (chunk.utility_effects || []).forEach((item) => state.effects.set(item.effect.effect_id, item));
    state.diagnostics = chunk.diagnostics || state.diagnostics;
    addRange(
      chunk.navigation.from_index,
      chunk.navigation.from_index + chunk.navigation.returned_samples - 1,
    );
    evictDistantEvidence(retentionIndex);
    updateMetrics();
    const targetIndex = state.bufferTargetIndex ?? state.index + 1;
    if (state.playing && state.buffering && state.samples.has(targetIndex)) {
      state.buffering = false;
      state.bufferTargetIndex = null;
      tickClock.play(performance.now());
      setPlaybackStatus("playing");
      scheduleFrame();
    }
    if (state.playing) prefetch(state.index);
  }

  function addRange(start, end) {
    state.ranges = window.StratWebBufferRanges.addRange(state.ranges, start, end);
  }

  function evictDistantEvidence(retentionIndex = state.index) {
    const maximumDistance = state.chunkLimit * 6;
    state.samples.forEach((_, index) => {
      if (!window.StratWebBufferRanges.withinRetention(
        index,
        retentionIndex,
        maximumDistance,
      )) {
        state.samples.delete(index);
      }
    });
    state.ranges = [];
    [...state.samples.keys()].sort((a, b) => a - b).forEach((index) => addRange(index, index));
    const bufferedTicks = [...state.samples.values()].map((item) => item.tick);
    if (!bufferedTicks.length) return;
    const minimumTick = Math.min(...bufferedTicks) - 64;
    const maximumTick = Math.max(...bufferedTicks) + 64;
    let projectileEvidenceEvicted = false;
    state.projectileSamples.forEach((item, id) => {
      if (item.snapshot.tick < minimumTick || item.snapshot.tick > maximumTick) {
        state.projectileSamples.delete(id);
        projectileEvidenceEvicted = true;
      }
    });
    state.projectileSeries.forEach((series, id) => {
      const retained = series.filter(
        (item) => item.snapshot.tick >= minimumTick && item.snapshot.tick <= maximumTick,
      );
      if (retained.length) {
        state.projectileSeries.set(id, retained);
        state.projectileTrailPlans.set(id, buildTrailPlan(retained));
      } else {
        state.projectileSeries.delete(id);
        state.projectileTrailPlans.delete(id);
      }
    });
    if (projectileEvidenceEvicted) {
      state.evidenceVersion += 1;
      state.lastDynamicEvidenceKey = "";
    }
    state.effects.forEach((item, id) => {
      const endTick = item.effect.end_tick ?? item.effect.start_tick;
      if (endTick < minimumTick || item.effect.start_tick > maximumTick) state.effects.delete(id);
    });
  }

  function filterQuery() {
    const query = new URLSearchParams({
      from_index: "0",
      limit: String(state.chunkLimit),
      run_id: config.spatial_run_id,
    });
    if (elements.teamFilter.value) query.set("team", elements.teamFilter.value);
    if (elements.playerFilter.value) query.set("player", elements.playerFilter.value);
    if (elements.aliveFilter.checked) query.set("alive_only", "true");
    if (elements.bombFilter.checked) query.set("bomb_carrier_only", "true");
    return query;
  }

  function chunkUrl(fromIndex) {
    const query = filterQuery();
    query.set("from_index", String(fromIndex));
    return `/api/spatial/${config.match_id}/rounds/${config.round_number}/playback?${query}`;
  }

  async function fetchChunk(
    fromIndex,
    {
      prefetch = false,
      cancelPrevious = false,
      retentionIndex = state.index,
    } = {},
  ) {
    const generation = state.generation;
    const pendingKey = `${generation}:${fromIndex}`;
    if (state.pendingStarts.has(pendingKey)) return null;
    state.pendingStarts.add(pendingKey);
    const client = prefetch ? prefetchApi : api;
    if (!prefetch) setLoading(true);
    try {
      const chunk = await client.json(chunkUrl(fromIndex), { cancelPrevious });
      if (generation !== state.generation) return null;
      addChunk(chunk, retentionIndex);
      state.apiRequestTimes.push(performance.now());
      hideError();
      return chunk;
    } catch (error) {
      if (error.name !== "AbortError" && generation === state.generation) {
        showError(error.message);
        if (state.buffering) setPlaybackStatus("buffering-error");
      }
      return null;
    } finally {
      state.pendingStarts.delete(pendingKey);
      if (!prefetch && generation === state.generation) setLoading(false);
    }
  }

  function fetchStartForIndex(index) {
    return Math.max(
      0,
      Math.min(index - Math.floor(state.chunkLimit / 4), config.total_samples - 1),
    );
  }

  async function ensureSample(index, cancelPrevious = false) {
    if (index < 0 || index >= config.total_samples) return null;
    if (state.samples.has(index)) return state.samples.get(index);
    await fetchChunk(
      fetchStartForIndex(index),
      { cancelPrevious, retentionIndex: index },
    );
    return state.samples.get(index) || null;
  }

  function requestSample(index) {
    if (index < 0 || index >= config.total_samples || state.samples.has(index)) return;
    void fetchChunk(
      fetchStartForIndex(index),
      { prefetch: true, retentionIndex: index },
    );
  }

  function invalidatePendingRequests() {
    state.generation += 1;
    api.cancel();
    prefetchApi.cancel();
    setLoading(false);
    return state.generation;
  }

  function prefetch(index) {
    const nextStart = window.StratWebBufferRanges.nextPrefetchStartByTime(
      state.ranges,
      index,
      config.total_samples,
      config.ticks,
      tickClock.tickAt(performance.now()),
      config.playback_clock.tick_duration_ms,
      state.speed,
      PREFETCH_WALL_RESERVE_MS,
    );
    if (nextStart != null) void fetchChunk(nextStart, { prefetch: true });
  }

  function bufferedWallTime(index) {
    const range = state.ranges.find((item) => item[0] <= index && index <= item[1]);
    if (!range) return 0;
    return Math.max(0, config.ticks[range[1]] - config.ticks[index])
      * config.playback_clock.tick_duration_ms / state.speed;
  }

  async function ensureStartBuffer(index, request) {
    while (bufferedWallTime(index) < START_PLAYBACK_RESERVE_MS) {
      const range = state.ranges.find((item) => item[0] <= index && index <= item[1]);
      if (!range || range[1] + 1 >= config.total_samples) break;
      const chunk = await fetchChunk(
        range[1] + 1,
        { retentionIndex: index },
      );
      if (request !== state.playRequest || !chunk) return false;
    }
    return state.samples.has(index + 1) || index >= config.total_samples - 1;
  }

  function latestSampleIndex(series, tick) {
    let low = 0;
    let high = series.length - 1;
    let result = -1;
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      if (series[middle].snapshot.tick <= tick) {
        result = middle;
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    return result;
  }

  function buildTrailPlan(series) {
    const plan = [];
    let segment = [];
    const flush = () => {
      if (segment.length > 1) {
        plan.push({
          startIndex: series.indexOf(segment[0]),
          endIndex: series.indexOf(segment.at(-1)),
          startTick: segment[0].snapshot.tick,
          points: segment.map((item) => item.projection),
        });
      }
      segment = [];
    };
    series.forEach((item) => {
      if (item.render_status !== "available") {
        flush();
        return;
      }
      const previous = segment[segment.length - 1];
      const discontinuity = (previous && item.snapshot.tick - previous.snapshot.tick > 16)
        || item.snapshot.warnings.includes("trajectory_to_terminal_event_not_interpolated");
      if (discontinuity) flush();
      segment.push(item);
    });
    flush();
    return plan;
  }

  function trailSegments(projectile, finalIndex) {
    const plan = state.projectileTrailPlans.get(projectile.projectile_id) || [];
    return plan.flatMap((segment) => {
      if (segment.startIndex > finalIndex) return [];
      const pointCount = Math.min(segment.endIndex, finalIndex) - segment.startIndex + 1;
      if (pointCount < 2) return [];
      return [{
        trail_id: `${projectile.projectile_id}:${segment.startTick}`,
        projectile_id: projectile.projectile_id,
        projectile_type: projectile.projectile_type,
        points: segment.points.slice(0, pointCount),
      }];
    });
  }

  function dynamicEvidence(
    sample,
    visualTick = sample.tick,
    timestamp = performance.now(),
  ) {
    const tick = Math.floor(visualTick);
    const projectileSamples = [];
    const trails = [];
    state.projectileSeries.forEach((series, projectileId) => {
      const projectile = state.projectiles.get(projectileId);
      if (!projectile || tick < projectile.first_position_tick || tick > projectile.terminal_tick) {
        return;
      }
      const index = latestSampleIndex(series, tick);
      if (index < 0) return;
      projectileSamples.push(series[index]);
      trails.push(...trailSegments(projectile, index));
    });
    const effects = [...state.effects.values()].filter((item) => {
      const effect = item.effect;
      return effect.start_tick <= tick && (effect.end_tick == null || effect.end_tick >= tick);
    });
    const events = transientEvents.visible(sample.events || [], timestamp);
    const key = [
      state.evidenceVersion,
      sample.sample_index,
      ...projectileSamples.map((item) => item.snapshot.snapshot_id),
      ...effects.map((item) => item.effect.effect_id),
      ...events.map((event) => event.marker_id),
    ].join("|");
    return {
      key,
      sample: {
        ...sample,
        projectile_samples: projectileSamples,
        utility_effects: effects,
        projectile_trails: trails,
        events,
      },
    };
  }

  function evidenceForSample(
    sample,
    visualTick = sample.tick,
    timestamp = performance.now(),
  ) {
    return dynamicEvidence(sample, visualTick, timestamp).sample;
  }

  function collectCrossedEvents(fromExclusive, toInclusive, timestamp) {
    const crossedEvents = [];
    for (let index = fromExclusive + 1; index <= toInclusive; index += 1) {
      const sample = state.samples.get(index);
      if (sample?.events?.length) crossedEvents.push(...sample.events);
    }
    transientEvents.add(crossedEvents, timestamp);
  }

  function updatePlaybackUi(sample, bounded, historyMode = "replace", force = false) {
    const now = performance.now();
    if (!force && now - state.lastUiUpdate < UI_UPDATE_INTERVAL) return;
    state.lastUiUpdate = now;
    elements.scrubber.value = String(bounded);
    setText(elements.sampleIndex, `${bounded + 1} / ${config.total_samples}`);
    renderer.setSelectedPlayer(elements.playerFilter.value || null);
    if (!state.playing && historyMode) updateUrl(sample.tick, historyMode);
    if (elements.diagnosticsDrawer.hidden) return;
    setText(elements.tickStatus, `tick ${sample.tick} · exact stored sample`);
    if (!state.playing) setText(elements.frameStatus, "Точный сохранённый снимок");
    setAttribute(
      elements.temporalLink,
      "href",
      `/ui/temporal/${config.match_id}/rounds/${config.round_number}/snapshots/${sample.tick}?run_id=${config.temporal_run_id}`,
    );
    const evidenceQuery = filterQuery();
    evidenceQuery.delete("from_index");
    evidenceQuery.delete("limit");
    setAttribute(
      elements.jsonLink,
      "href",
      `/api/spatial/${config.match_id}/rounds/${config.round_number}/ticks/${sample.tick}?${evidenceQuery}`,
    );
    updateRealtimeStatus(sample);
    updateMetrics();
  }

  function commitExact(index, historyMode = "replace", timestamp = performance.now()) {
    const bounded = Math.max(0, Math.min(config.total_samples - 1, index));
    const stored = state.samples.get(bounded);
    if (!stored) return false;
    state.index = bounded;
    const evidence = dynamicEvidence(stored, stored.tick, timestamp);
    const sample = evidence.sample;
    state.lastDynamicEvidenceKey = evidence.key;
    recordRenderProfile(renderer.renderExact(sample));
    setHidden(elements.emptyState, sample.players.length > 0);
    applyAutoFocus(sample);
    updatePlaybackUi(sample, bounded, historyMode, !state.playing);
    if (!state.playing) tickClock.seekIndex(bounded, performance.now());
    if (!state.playing && bounded >= config.total_samples - 1) {
      setPlaybackStatus("end");
    }
    prefetch(bounded);
    return true;
  }

  async function selectExact(index, { historyMode = "replace", cancelPrevious = false } = {}) {
    const operationGeneration = state.generation;
    const bounded = Math.max(0, Math.min(config.total_samples - 1, index));
    const sample = await ensureSample(bounded, cancelPrevious);
    if (operationGeneration !== state.generation) return false;
    return sample ? commitExact(bounded, historyMode) : false;
  }

  function updateUrl(tick, historyMode) {
    const url = window.StratWebUrlState.write(window.location.href, {
      tick,
      mode: state.mode,
      team: elements.teamFilter.value,
      player: elements.playerFilter.value,
      alive: elements.aliveFilter.checked,
      bomb: elements.bombFilter.checked,
    });
    const method = historyMode === "push" ? "pushState" : "replaceState";
    window.history[method]({ tick, mode: state.mode }, "", url);
  }

  async function play() {
    if (state.playing || state.starting) return;
    if (config.total_samples < 2) {
      setPlaybackStatus("unavailable");
      return;
    }
    state.starting = true;
    const request = ++state.playRequest;
    try {
      if (state.index >= config.total_samples - 1) {
        setPlaybackStatus("buffering");
        const restarted = await selectExact(
          0,
          { historyMode: "replace", cancelPrevious: true },
        );
        if (request !== state.playRequest) return;
        if (!restarted) {
          setPlaybackStatus("unavailable");
          return;
        }
      }
      setPlaybackStatus("buffering");
      const bufferReady = await ensureStartBuffer(state.index, request);
      if (request !== state.playRequest) return;
      if (!bufferReady) {
        setPlaybackStatus("unavailable");
        return;
      }
      state.playing = true;
      state.lastFrame = 0;
      const now = performance.now();
      tickClock.seekIndex(state.index, now);
      tickClock.setSpeed(state.speed, now);
      tickClock.play(now);
      if (!state.samples.has(state.index + 1)) {
        enterBuffering(state.index + 1, now);
        requestSample(state.index + 1);
        return;
      }
      setPlaybackStatus("playing");
      prefetch(state.index);
      scheduleFrame();
    } finally {
      state.starting = false;
    }
  }

  function pause({ status = "paused", historyMode = "replace" } = {}) {
    const now = performance.now();
    tickClock.pause(now);
    state.playRequest += 1;
    state.starting = false;
    state.playing = false;
    state.buffering = false;
    state.bufferTargetIndex = null;
    transientEvents.clear();
    setPlaybackStatus(status);
    const sample = state.samples.get(state.index);
    if (sample) {
      tickClock.seekIndex(state.index, now);
      const evidence = evidenceForSample(sample);
      recordRenderProfile(renderer.renderExact(evidence, { forceLabels: true }));
      updatePlaybackUi(evidence, state.index, historyMode, true);
    }
  }

  function enterBuffering(targetIndex, timestamp = performance.now()) {
    if (!state.buffering) state.bufferingCount += 1;
    tickClock.pause(timestamp);
    state.buffering = true;
    state.bufferTargetIndex = targetIndex;
    setPlaybackStatus("buffering");
    updateMetrics();
  }

  function scheduleFrame() {
    if (!state.playing || state.buffering || state.frameScheduled) return;
    state.frameScheduled = true;
    requestAnimationFrame(frame);
  }

  function frame(timestamp) {
    state.frameScheduled = false;
    if (!state.playing || state.buffering) return;
    const frameDelta = state.lastFrame ? timestamp - state.lastFrame : 0;
    if (frameDelta > 34) state.droppedFrames += 1;
    state.instantFps = frameDelta > 0 ? 1000 / frameDelta : 0;
    state.lastFrame = timestamp;
    const bracket = tickClock.bracket(timestamp);
    const missingIndex = !state.samples.has(bracket.leftIndex)
      ? bracket.leftIndex
      : bracket.rightIndex != null && !state.samples.has(bracket.rightIndex)
        ? bracket.rightIndex
        : null;
    if (missingIndex != null) {
      enterBuffering(missingIndex, timestamp);
      requestSample(missingIndex);
      return;
    }
    const crossed = Math.max(0, bracket.leftIndex - state.index);
    if (crossed > 0) {
      state.crossedSamples += crossed;
      state.maxCrossedSamplesPerFrame = Math.max(state.maxCrossedSamplesPerFrame, crossed);
      collectCrossedEvents(state.index, bracket.leftIndex, timestamp);
      state.index = bracket.leftIndex;
    }
    const currentStored = state.samples.get(bracket.leftIndex);
    const followingStored = bracket.rightIndex == null
      ? null
      : state.samples.get(bracket.rightIndex);
    if (!currentStored) {
      pause({ status: "unavailable" });
      return;
    }
    if (bracket.ended) {
      if (state.index !== bracket.leftIndex) commitExact(bracket.leftIndex, "replace");
      pause({ status: "end" });
      return;
    }
    if (!followingStored) {
      enterBuffering(bracket.rightIndex, timestamp);
      requestSample(bracket.rightIndex);
      return;
    }
    const frameEvidence = dynamicEvidence(currentStored, bracket.playheadTick, timestamp);
    renderer.beginFrame();
    if (crossed > 0) {
      renderer.commitPlaybackSample(frameEvidence.sample);
      setHidden(elements.emptyState, frameEvidence.sample.players.length > 0);
      applyAutoFocus(frameEvidence.sample);
      updatePlaybackUi(frameEvidence.sample, bracket.leftIndex, "replace");
    }
    if (frameEvidence.key !== state.lastDynamicEvidenceKey) {
      renderer.updateDynamicEvidence(frameEvidence.sample);
      state.lastDynamicEvidenceKey = frameEvidence.key;
    }
    renderer.drawFrame(currentStored, followingStored, bracket.alpha, state.mode);
    recordRenderProfile(renderer.endFrame());
    if (!elements.diagnosticsDrawer.hidden && timestamp - state.lastOverlayUpdate >= 250) {
      updateDeveloperOverlay(currentStored, followingStored, bracket.alpha);
      state.lastOverlayUpdate = timestamp;
    }
    prefetch(bracket.leftIndex);
    scheduleFrame();
  }

  async function exactAction(index, historyMode = "push") {
    invalidatePendingRequests();
    pause();
    await selectExact(index, { historyMode, cancelPrevious: true });
  }

  function setPlaybackSpeed(value) {
    const next = Number(value);
    tickClock.setSpeed(next, performance.now());
    state.speed = next;
    prefetch(state.index);
  }

  function setPlaybackStatus(status) {
    const labels = {
      playing: "❚❚ Пауза",
      paused: "▶ Пуск",
      buffering: "Загрузка…",
      "buffering-error": "Повторить загрузку",
      end: "Сначала",
      unavailable: "Нет следующего достоверного снимка",
    };
    setText(elements.playPause, labels[status] || labels.paused);
    setAttribute(elements.playPause, "aria-label", status);
    elements.playPause.dataset.status = status;
    if (status === "playing") {
      setText(elements.frameStatus, "Относительное время демки · визуальная интерполяция");
    }
    if (status === "buffering") setText(elements.frameStatus, "Загрузка · время воспроизведения остановлено");
    if (status === "end") setText(elements.frameStatus, "Конец раунда · точный финальный снимок");
  }

  function eventIndex(direction) {
    const currentTick = config.ticks[state.index];
    const eventTicks = [...new Set(config.event_ticks)].sort((a, b) => a - b);
    const tick = direction < 0
      ? [...eventTicks].reverse().find((item) => item < currentTick)
      : eventTicks.find((item) => item > currentTick);
    return tick == null ? state.index : config.ticks.indexOf(tick);
  }

  async function resetFilters({
    targetIndex = state.index,
    historyMode = "push",
  } = {}) {
    pause({ historyMode: null });
    const operationGeneration = invalidatePendingRequests();
    state.index = Math.max(0, Math.min(config.total_samples - 1, targetIndex));
    state.samples.clear();
    state.ranges = [];
    state.projectiles.clear();
    state.projectileSamples.clear();
    state.projectileSeries.clear();
    state.projectileTrailPlans.clear();
    state.effects.clear();
    transientEvents.clear();
    state.evidenceVersion += 1;
    state.lastDynamicEvidenceKey = "";
    const chunk = await fetchChunk(
      fetchStartForIndex(state.index),
      { cancelPrevious: true, retentionIndex: state.index },
    );
    if (operationGeneration !== state.generation || !chunk) return false;
    return commitExact(state.index, historyMode);
  }

  function recordRenderProfile(detail) {
    if (!detail) return;
    state.renderedFrames += 1;
    state.maxRenderDuration = Math.max(state.maxRenderDuration, detail.duration);
    state.rejectedMarkers = detail.rejected;
    state.recreatedNodes += detail.recreatedNodes || 0;
    state.activePlayers = detail.activePlayerCount || 0;
    state.activeProjectiles = detail.activeProjectileCount || 0;
    state.labelPlanBuilds = detail.labelPlanBuilds || 0;
    state.labelAnchorChanges = detail.labelAnchorChanges || 0;
    state.profileSequence += 1;
    if (state.profileSequence % 6 !== 0) return;
    const append = (collection, value) => {
      collection.push(value || 0);
      if (collection.length > 120) collection.shift();
    };
    append(state.renderDurations, detail.duration);
    append(state.domDurations, detail.domUpdateDuration);
    append(state.svgDurations, detail.svgUpdateDuration);
    append(state.sidebarDurations, detail.sidebarUpdateDuration);
    append(state.eventListDurations, detail.eventListUpdateDuration);
    append(state.updatedNodeCounts, detail.updatedNodes);
  }

  function updateMetrics() {
    if (elements.diagnosticsDrawer.hidden) return;
    setText(elements.bufferStatus, `${state.samples.size} / ${config.total_samples} buffered`);
    setText(elements.metricNodes, renderer.nodeCount());
    setText(elements.metricFetches, api.fetchCount + prefetchApi.fetchCount);
    const average = state.renderDurations.length
      ? state.renderDurations.reduce((sum, value) => sum + value, 0) / state.renderDurations.length
      : 0;
    const averageOf = (values) => values.length
      ? values.reduce((sum, value) => sum + value, 0) / values.length
      : 0;
    const averageNodes = averageOf(state.updatedNodeCounts);
    setText(elements.metricRender, average ? `${average.toFixed(2)} ms` : "—");
    setText(elements.metricDom, state.domDurations.length
      ? `${averageOf(state.domDurations).toFixed(2)} ms` : "—");
    setText(elements.metricSvg, state.svgDurations.length
      ? `${averageOf(state.svgDurations).toFixed(2)} ms` : "—");
    setText(elements.metricSidebar, state.sidebarDurations.length
      ? `${averageOf(state.sidebarDurations).toFixed(2)} ms` : "—");
    setText(elements.metricEventList, state.eventListDurations.length
      ? `${averageOf(state.eventListDurations).toFixed(2)} ms` : "—");
    setText(elements.metricUpdatedNodes, averageNodes.toFixed(1));
    setText(elements.metricRecreatedNodes, state.recreatedNodes);
    setText(elements.metricActivePlayers, state.activePlayers);
    setText(elements.metricActiveProjectiles, state.activeProjectiles);
    setText(elements.metricClockCrossed, state.crossedSamples);
    setText(elements.metricClockMaxCrossed, state.maxCrossedSamplesPerFrame);
    setText(elements.metricLabelPlans, state.labelPlanBuilds);
    setText(elements.metricAnchorFlips, state.labelAnchorChanges);
    setText(elements.metricDropped, state.droppedFrames);
    setText(elements.metricBuffering, state.bufferingCount);
    setText(elements.metricRejected, state.rejectedMarkers);
    setText(elements.metricRepeated, state.diagnostics.repeated_player_samples || 0);
    setText(elements.metricJumps, state.diagnostics.suspicious_player_jumps || 0);
    setText(elements.metricProjectileSamples, state.projectileSamples.size);
    setText(elements.metricUtilityEffects, state.effects.size);
    const now = performance.now();
    state.apiRequestTimes = state.apiRequestTimes.filter((item) => now - item <= 60000);
    setText(elements.developerBuffered, state.samples.size);
    setText(elements.developerPending, state.pendingStarts.size || "нет");
    setText(elements.developerRendered, state.renderedFrames);
    setText(
      elements.developerMaxRender,
      state.maxRenderDuration ? `${state.maxRenderDuration.toFixed(2)} ms` : "—",
    );
    setText(elements.developerApiMinute, state.apiRequestTimes.length);
  }

  function updateDeveloperOverlay(current, following, alpha) {
    const followingPlayers = new Map(
      following.players.map((item) => [item.snapshot.participant_id, item]),
    );
    let stale = 0;
    let unavailable = 0;
    current.players.forEach((player) => {
      const next = followingPlayers.get(player.snapshot.participant_id);
      const motion = window.StratWebMotion.classify(player, next || null);
      stale += Number(motion.repeated || motion.classification === "unavailable");
      unavailable += Number(player.render_status !== "available");
    });
    setText(elements.developerCurrentTick, current.tick);
    setText(elements.developerNextTick, following.tick);
    setText(elements.developerProgress, `${Math.round(alpha * 100)}%`);
    setText(elements.developerTickGap, following.tick - current.tick);
    setText(elements.developerFps, state.instantFps ? state.instantFps.toFixed(1) : "—");
    setText(elements.developerStale, stale);
    setText(elements.developerUnavailable, unavailable);
    updateMetrics();
  }

  function setLoading(active) { setHidden(elements.loadingState, !active); }
  function showError(message) { setText(elements.errorMessage, message); setHidden(elements.errorState, false); }
  function hideError() { setHidden(elements.errorState, true); }
  function updateRealtimeStatus(sample) {
    let selected = elements.playerFilter.selectedOptions[0]?.textContent || "Все игроки";
    const selectedId = elements.playerFilter.value || null;
    const selectedPlayer = selectedId
      ? (sample.players || []).find((item) => item.snapshot.participant_id === selectedId)
      : null;
    if (selectedPlayer?.zone_assignment?.status === "resolved") {
      selected += ` · ${selectedPlayer.zone_assignment.zone_name}`;
    } else if (selectedPlayer?.zone_assignment?.status === "unknown") {
      selected += " · зона неизвестна";
    } else if (selectedPlayer?.zone_assignment?.status === "unavailable") {
      selected += " · зона недоступна";
    }
    setText(elements.selectedPlayerStatus, selected);
    const zoneLabel = selectedPlayer?.zone_assignment?.status === "resolved"
      ? selectedPlayer.zone_assignment.zone_name
      : selectedPlayer?.zone_assignment?.status === "unknown"
        ? "Зона неизвестна"
        : selectedPlayer?.zone_assignment?.status === "unavailable"
          ? "Зона недоступна"
          : null;
    setText(elements.selectedZoneBadge, zoneLabel || "");
    setHidden(elements.selectedZoneBadge, !selectedId || !zoneLabel);
    if (selectedId) {
      setAttribute(
        elements.playerPathLink,
        "href",
        `/ui/spatial/${config.match_id}/rounds/${config.round_number}/players/${selectedId}/path?run_id=${config.spatial_run_id}`,
      );
    }
    setHidden(elements.playerPathLink, !selectedId);
    const labels = (sample.events || []).slice(0, 3).map((event) => {
      const kind = event.kind.replaceAll("_", " ");
      return event.player_name ? `${kind}: ${event.player_name}` : kind;
    });
    setText(elements.currentEventStatus, labels.length ? labels.join(" · ") : "Нет текущего события");
    renderer.setSelectedPlayer(elements.playerFilter.value || null);
  }

  function applyAutoFocus(sample) {
    if (!elements.autoFocus?.checked) return;
    if (state.playing) {
      const focusKinds = new Set(["death", "plant", "defuse", "explosion", "opening_duel"]);
      if (!(sample.events || []).some((event) => focusKinds.has(event.kind))) return;
      if (state.lastAutoFocusTick != null && sample.tick - state.lastAutoFocusTick < 32) return;
    }
    const point = renderer.focusPoint(sample);
    if (!point) return;
    const size = renderer.mapSize();
    const targetZoom = Math.max(1.2, Math.min(1.45, state.zoom));
    const targetX = (point.x / size.mapWidth) * size.displayWidth;
    const targetY = (point.y / size.mapHeight) * size.displayHeight;
    state.zoom = targetZoom;
    state.panX = size.displayWidth / 2 - targetX * targetZoom;
    state.panY = size.displayHeight / 2 - targetY * targetZoom;
    elements.mapCanvas.classList.add("auto-focus-active");
    state.lastAutoFocusTick = sample.tick;
    applyView();
  }

  function disableAutoFocus() {
    if (elements.autoFocus) elements.autoFocus.checked = false;
    elements.mapCanvas.classList.remove("auto-focus-active");
  }

  function editableTarget(target) {
    return target instanceof HTMLInputElement || target instanceof HTMLSelectElement
      || target instanceof HTMLTextAreaElement || target.isContentEditable;
  }
  function applyView() {
    const transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
    if (elements.mapCanvas.style.transform !== transform) {
      elements.mapCanvas.style.transform = transform;
    }
    renderer.setZoom(state.zoom);
  }
  function zoom(delta, { manual = true } = {}) {
    if (manual) disableAutoFocus();
    state.zoom = Math.max(1, Math.min(5, state.zoom * delta));
    applyView();
  }
  function resetView() {
    disableAutoFocus();
    state.zoom = 1;
    state.panX = 0;
    state.panY = 0;
    applyView();
  }

  function fitViewport(rect = null) {
    const width = rect?.width ?? elements.mapStage.clientWidth;
    const height = rect?.height ?? elements.mapStage.clientHeight;
    const size = Math.max(1, Math.floor(Math.min(width, height)));
    elements.mapViewport.style.width = `${size}px`;
    elements.mapViewport.style.height = `${size}px`;
    renderer.setViewportSize(size, size);
  }

  addChunk(initialChunk);
  tickClock.seekIndex(state.index, performance.now());
  elements.roundSelect.value = String(config.round_number);
  elements.scrubber.max = String(Math.max(0, config.total_samples - 1));
  elements.playbackMode.value = state.mode;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    state.mode = "exact";
    elements.playbackMode.value = "exact";
  }
  fitViewport();
  new ResizeObserver((entries) => {
    const entry = entries[0];
    if (entry) fitViewport(entry.contentRect);
  }).observe(elements.mapStage);
  void selectExact(state.index);
  setPlaybackStatus(
    config.total_samples < 2
      ? "unavailable"
      : state.index >= config.total_samples - 1 ? "end" : "paused",
  );

  document.getElementById("previous").onclick = () => void exactAction(state.index - 1);
  document.getElementById("next").onclick = () => void exactAction(state.index + 1);
  document.getElementById("beginning").onclick = () => void exactAction(0);
  document.getElementById("ending").onclick = () => void exactAction(config.total_samples - 1);
  document.getElementById("previousEvent").onclick = () => void exactAction(eventIndex(-1));
  document.getElementById("nextEvent").onclick = () => void exactAction(eventIndex(1));
  elements.playPause.onclick = () => state.playing ? pause() : void play();
  elements.scrubber.addEventListener("input", () => {
    setText(
      elements.sampleIndex,
      `${Number(elements.scrubber.value) + 1} / ${config.total_samples}`,
    );
  });
  elements.scrubber.addEventListener("change", () => void exactAction(Number(elements.scrubber.value)));
  elements.playbackMode.onchange = () => {
    state.mode = elements.playbackMode.value;
    pause();
    const sample = state.samples.get(state.index);
    if (sample) updateUrl(sample.tick, "push");
  };
  elements.playbackSpeed.onchange = () => setPlaybackSpeed(elements.playbackSpeed.value);
  elements.labelMode.onchange = () => {
    const sample = state.samples.get(state.index);
    if (sample) renderer.setLabelMode(elements.labelMode.value, evidenceForSample(sample));
  };
  [elements.teamFilter, elements.playerFilter, elements.aliveFilter, elements.bombFilter]
    .forEach((element) => element.addEventListener("change", () => void resetFilters()));
  document.querySelectorAll("[id^='utility-']").forEach((element) => {
    element.addEventListener("change", () => {
      const sample = state.samples.get(state.index);
      if (sample) recordRenderProfile(renderer.renderExact(evidenceForSample(sample)));
    });
  });
  elements.roundSelect.onchange = () => {
    const query = filterQuery();
    query.delete("from_index");
    query.delete("limit");
    query.set("mode", state.mode);
    window.location.href = `/ui/spatial/${config.match_id}/rounds/${elements.roundSelect.value}?${query}`;
  };
  elements.eventJump.onchange = () => {
    const index = config.ticks.indexOf(Number(elements.eventJump.value));
    if (index >= 0) void exactAction(index);
  };
  document.getElementById("retry").onclick = () => state.buffering
    ? requestSample(state.bufferTargetIndex ?? state.index + 1) : void resetFilters();
  document.getElementById("diagnosticsToggle").onclick = () => {
    elements.diagnosticsDrawer.hidden = false;
    const sample = state.samples.get(state.index);
    if (sample) updatePlaybackUi(evidenceForSample(sample), state.index, "replace", true);
    updateMetrics();
  };
  document.getElementById("closeDiagnostics").onclick = () => { elements.diagnosticsDrawer.hidden = true; };
  document.getElementById("fullscreen").onclick = () => document.getElementById("viewerShell").requestFullscreen();
  elements.copyCs2Command.onclick = () => void copyCs2Commands();
  document.getElementById("zoomIn").onclick = () => zoom(1.25);
  document.getElementById("zoomOut").onclick = () => zoom(0.8);
  document.getElementById("resetView").onclick = resetView;
  document.getElementById("fitMap").onclick = () => {
    fitViewport();
    resetView();
  };
  elements.mapStage.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom(event.deltaY < 0 ? 1.12 : 0.89);
  }, { passive: false });
  elements.mapStage.addEventListener("pointerdown", (event) => {
    disableAutoFocus();
    state.dragging = true;
    state.dragStart = [event.clientX - state.panX, event.clientY - state.panY];
    elements.mapStage.setPointerCapture(event.pointerId);
  });
  elements.mapStage.addEventListener("pointermove", (event) => {
    if (!state.dragging) return;
    state.panX = event.clientX - state.dragStart[0];
    state.panY = event.clientY - state.dragStart[1];
    applyView();
  });
  elements.mapStage.addEventListener("pointerup", () => { state.dragging = false; });
  elements.autoFocus.addEventListener("change", () => {
    elements.mapCanvas.classList.toggle("auto-focus-active", elements.autoFocus.checked);
    const sample = state.samples.get(state.index);
    if (sample && elements.autoFocus.checked) applyAutoFocus(evidenceForSample(sample));
  });
  window.addEventListener("stratweb:player", (event) => {
    elements.playerFilter.value = event.detail;
    void resetFilters();
  });
  window.addEventListener("pageshow", () => { elements.roundSelect.value = String(config.round_number); });
  window.addEventListener("popstate", async () => {
    const restored = window.StratWebUrlState.read(window.location.href);
    const index = config.ticks.indexOf(restored.tick);
    const filtersChanged = elements.teamFilter.value !== restored.team
      || elements.playerFilter.value !== restored.player
      || elements.aliveFilter.checked !== restored.alive
      || elements.bombFilter.checked !== restored.bomb;
    state.mode = restored.mode;
    elements.playbackMode.value = state.mode;
    elements.teamFilter.value = restored.team;
    elements.playerFilter.value = restored.player;
    elements.aliveFilter.checked = restored.alive;
    elements.bombFilter.checked = restored.bomb;
    if (index < 0) return;
    if (filtersChanged) {
      await resetFilters({ targetIndex: index, historyMode: null });
      return;
    }
    invalidatePendingRequests();
    pause({ historyMode: null });
    await selectExact(index, { historyMode: null, cancelPrevious: true });
  });
  window.addEventListener("keydown", (event) => {
    if (editableTarget(event.target)) return;
    if ([" ", "ArrowLeft", "ArrowRight", "Home", "End", "1", "2", "3", "4", "Escape"].includes(event.key)) event.preventDefault();
    if (event.key === " ") state.playing ? pause() : void play();
    else if (event.key === "ArrowLeft") void exactAction(event.shiftKey ? eventIndex(-1) : state.index - 1);
    else if (event.key === "ArrowRight") void exactAction(event.shiftKey ? eventIndex(1) : state.index + 1);
    else if (event.key === "Home") void exactAction(0);
    else if (event.key === "End") void exactAction(config.total_samples - 1);
    else if (["1", "2", "3", "4"].includes(event.key)) {
      const speeds = { "1": 0.5, "2": 1, "3": 2, "4": 4 };
      setPlaybackSpeed(speeds[event.key]);
      elements.playbackSpeed.value = String(state.speed);
    } else if (event.key === "Escape") {
      elements.diagnosticsDrawer.hidden = true;
      if (document.fullscreenElement) void document.exitFullscreen();
    }
  });
})();
