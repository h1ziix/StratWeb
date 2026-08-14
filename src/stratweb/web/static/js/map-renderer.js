"use strict";

(() => {
  const NS = "http://www.w3.org/2000/svg";
  const PLAYER_SLOTS = 12;
  const PROJECTILE_SLOTS = 24;
  const EFFECT_SLOTS = 32;
  const EVENT_SLOTS = 32;
  const EVENT_CARD_SLOTS = 8;
  const COMBAT_EVENTS = new Set(["shot", "damage", "death"]);
  const POLICY = {
    normalGapMaxTicks: 16,
    largeGapMaxTicks: 64,
    maxPlanarDistance: 1024,
    maxVerticalDistance: 512,
  };

  const safeProjection = (item) => Boolean(
    item && item.render_status === "available" && item.projection?.inside_image === true,
  );

  const byPlayer = (sample) => new Map(
    sample.players.map((player) => [player.snapshot.participant_id, player]),
  );

  const projectileIcon = (type) => ({
    smoke: "#icon-smoke",
    flashbang: "#icon-flash",
    he_grenade: "#icon-he",
    molotov: "#icon-fire",
    incendiary: "#icon-fire",
    fire: "#icon-fire",
    flash: "#icon-flash",
    he: "#icon-he",
    decoy: "#icon-decoy",
  }[type] || "#icon-utility");

  const eventIcon = (kind) => ({
    shot: "#icon-shot",
    damage: "#icon-damage",
    grenade: "#icon-utility",
    death: "#icon-death",
    plant: "#icon-bomb",
    defuse: "#icon-defuse",
    explosion: "#icon-explosion",
    trade: "#icon-trade",
    opening_duel: "#icon-opening",
  }[kind] || "#icon-event");

  const eventLabel = (kind) => ({
    shot: "Выстрел",
    damage: "Урон",
    grenade: "Граната",
    death: "Смерть",
    plant: "Установка бомбы",
    defuse: "Разминирование",
    explosion: "Взрыв",
    trade: "Размен",
    opening_duel: "Первая дуэль",
  }[kind] || kind);

  function classifyMotion(previous, following) {
    if (!previous || !following) {
      return { classification: "unavailable", eligible: false, reason: "participant_absent" };
    }
    const a = previous.snapshot;
    const b = following.snapshot;
    const tickGap = b.tick - a.tick;
    if (a.participant_id !== b.participant_id || a.round_id !== b.round_id || tickGap <= 0) {
      return { classification: "discontinuity", eligible: false, reason: "identity_or_tick" };
    }
    if (a.alive !== true || b.alive !== true) {
      return { classification: "discontinuity", eligible: false, tickGap, reason: "life_state" };
    }
    if (!safeProjection(previous) || !safeProjection(following)
        || a.availability.position !== "available" || b.availability.position !== "available"
        || ["unreliable", "unavailable"].includes(a.position_authority)
        || ["unreliable", "unavailable"].includes(b.position_authority)) {
      return { classification: "unavailable", eligible: false, tickGap, reason: "position" };
    }
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dz = (b.z ?? 0) - (a.z ?? 0);
    const planarDistance = Math.hypot(dx, dy);
    const repeated = planarDistance === 0 && dz === 0;
    const levelTransition = previous.projection.level !== following.projection.level;
    const suspicious = planarDistance > POLICY.maxPlanarDistance
      || Math.abs(dz) > POLICY.maxVerticalDistance;
    let classification = "normal";
    if (suspicious || levelTransition || tickGap > POLICY.largeGapMaxTicks) {
      classification = "discontinuity";
    } else if (tickGap > POLICY.normalGapMaxTicks) {
      classification = "large";
    }
    return {
      classification,
      eligible: ["normal", "large"].includes(classification),
      tickGap,
      planarDistance,
      derivedSpeedWorldUnitsPerTick: planarDistance / tickGap,
      repeated,
      levelTransition,
      suspicious,
      reason: suspicious ? "suspicious_spatial_jump" : levelTransition ? "level_transition" : null,
    };
  }

  function sampleSemantics(previous, following, alpha, mode, classifiedMotion = null) {
    if (!previous) return "absent";
    if (previous.snapshot.alive === false) return "dead";
    if (!safeProjection(previous)) return "unavailable";
    if (mode !== "smooth" || alpha <= 0) return "exact";
    const motion = classifiedMotion || classifyMotion(previous, following);
    if (!following) return "absent";
    if (following.snapshot.alive === false) return alpha >= 1 ? "dead" : "exact";
    if (motion.classification === "unavailable" || motion.repeated) return "held";
    return motion.eligible ? "interpolated" : "exact";
  }

  function interpolateYaw(start, end, alpha) {
    const delta = ((end - start + 540) % 360) - 180;
    return (start + delta * Math.max(0, Math.min(1, alpha)) + 360) % 360;
  }

  function svgIcon(icon) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "marker-svg");
    svg.setAttribute("viewBox", "-16 -16 32 32");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(NS, "use");
    use.setAttribute("href", icon);
    svg.append(use);
    return { svg, use };
  }

  function marker(className, icon, tag = "div") {
    const node = document.createElement(tag);
    node.className = className;
    const glyph = svgIcon(icon);
    node.append(glyph.svg);
    return { node, use: glyph.use };
  }

  function playerMarker() {
    const node = document.createElement("button");
    node.className = "player-marker";
    node.type = "button";
    node.tabIndex = -1;

    const direction = document.createElement("span");
    direction.className = "player-direction";
    direction.setAttribute("aria-hidden", "true");

    const disc = document.createElement("span");
    disc.className = "player-disc";
    disc.setAttribute("aria-hidden", "true");
    const sideText = document.createElement("span");
    sideText.className = "player-side-text";
    sideText.append(document.createTextNode("?"));
    disc.append(sideText);

    node.append(direction, disc);
    return {
      node,
      direction,
      disc,
      sideText,
    };
  }

  class MapRenderer {
    constructor(mapCanvas, eventCards, labelRoster = []) {
      this.mapCanvas = mapCanvas;
      this.eventCards = eventCards;
      this.playersLayer = document.getElementById("playersLayer");
      this.projectilesLayer = document.getElementById("projectilesLayer");
      this.effectsLayer = document.getElementById("utilityEffectsLayer");
      this.eventsLayer = document.getElementById("eventsLayer");
      this.bombLayer = document.getElementById("bombLayer");
      this.labelsLayer = document.getElementById("labelsLayer");
      this.selectionLayer = document.getElementById("selectionLayer");
      this.trailsCanvas = document.getElementById("projectileTrailsLayer");
      this.mapWidth = Number(mapCanvas.dataset.mapWidth) || 1024;
      this.mapHeight = Number(mapCanvas.dataset.mapHeight) || 1024;
      this.displayWidth = this.mapWidth;
      this.displayHeight = this.mapHeight;
      this.scaleX = 1;
      this.scaleY = 1;
      this.zoom = 1;
      this.labelMode = "medium";
      this.levelMode = "automatic";
      this.selectedPlayerId = null;
      this.currentSample = null;
      this.currentTrails = [];
      const rosterPlayers = labelRoster
        .filter((player) => player && player.participant_id)
        .map((player) => ({
          player_name: player.player_name || player.participant_id,
          snapshot: {
            participant_id: player.participant_id,
            physical_team_id: player.physical_team_id || null,
            side: "unknown",
          },
        }));
      this.labelAnchorPlan = window.StratWebLabels.planAnchors(rosterPlayers);
      this.labelPlanBuilds = this.labelAnchorPlan.size ? 1 : 0;
      this.labelAnchorChanges = 0;
      this.motionSignature = "";
      this.motionPlan = [];
      this.frameProfile = null;
      this.playerSlots = this.createPlayerSlots();
      this.projectileSlots = this.createMarkerSlots(
        PROJECTILE_SLOTS,
        "projectile-marker",
        "#icon-utility",
        this.projectilesLayer,
      );
      this.effectSlots = this.createEffectSlots();
      this.eventSlots = this.createMarkerSlots(
        EVENT_SLOTS,
        "event-marker",
        "#icon-event",
        this.eventsLayer,
        "a",
      );
      this.eventCardSlots = this.createEventCards();
      this.bombSlot = marker("bomb-marker", "#icon-bomb");
      this.bombLayer.append(this.bombSlot.node);
      this.selectionSlot = { node: document.createElement("div") };
      this.selectionSlot.node.className = "selection-marker";
      this.selectionSlot.node.setAttribute("aria-hidden", "true");
      this.selectionLayer.append(this.selectionSlot.node);
      this.eventSignature = "";
      this.projectileSignature = "";
      this.effectSignature = "";
      this.trailSignature = "";
      this.labelSignature = "";
      this.activeProjectileCount = 0;
      this.poolOverflowKeys = new Set();
      this.recreatedNodes = this.nodeCount();
      const levelFilter = document.getElementById("levelFilter");
      if (levelFilter) {
        levelFilter.addEventListener("change", () => this.setLevelMode(levelFilter.value));
      }
    }

    createPlayerSlots() {
      return Array.from({ length: PLAYER_SLOTS }, () => {
        const markerNode = playerMarker();
        const label = document.createElement("span");
        label.className = "player-label-node";
        label.setAttribute("aria-hidden", "true");
        label.setAttribute("dir", "auto");
        label.append(document.createTextNode(""));
        this.playersLayer.append(markerNode.node);
        this.labelsLayer.append(label);
        const slot = {
          ...markerNode,
          label,
          key: null,
          playerName: "",
          zoneName: null,
          labelOffset: { x: 14, y: 4 },
        };
        markerNode.node.addEventListener("click", () => {
          if (slot.key) {
            window.dispatchEvent(new CustomEvent("stratweb:player", { detail: slot.key }));
          }
        });
        return slot;
      });
    }

    createMarkerSlots(size, className, icon, layer, tag = "div") {
      return Array.from({ length: size }, () => {
        const slot = { ...marker(className, icon, tag), key: null };
        if (tag === "a") slot.node.tabIndex = -1;
        layer.append(slot.node);
        return slot;
      });
    }

    createEffectSlots() {
      return Array.from({ length: EFFECT_SLOTS }, () => {
        const slot = { ...marker("effect-marker", "#icon-utility"), key: null };
        const ring = document.createElement("span");
        ring.className = "effect-ring";
        slot.node.append(ring);
        this.effectsLayer.append(slot.node);
        return slot;
      });
    }

    createEventCards() {
      return Array.from({ length: EVENT_CARD_SLOTS }, () => {
        const link = document.createElement("a");
        link.className = "event-chip";
        link.hidden = true;
        const icon = document.createElement("span");
        icon.className = "event-chip-icon";
        const text = document.createElement("span");
        icon.append(document.createTextNode(""));
        text.append(document.createTextNode(""));
        link.append(icon, text);
        this.eventCards.append(link);
        return { link, icon, text };
      });
    }

    beginFrame() {
      this.frameProfile = {
        startedAt: performance.now(),
        updatedNodes: new Set(),
        activePlayerCount: 0,
        activeProjectileCount: this.activeProjectileCount,
        rejectedEntities: 0,
      };
    }

    endFrame() {
      if (!this.frameProfile) return null;
      const profile = this.frameProfile;
      const duration = performance.now() - profile.startedAt;
      const detail = {
        duration,
        domUpdateDuration: duration,
        svgUpdateDuration: 0,
        sidebarUpdateDuration: 0,
        eventListUpdateDuration: 0,
        activePlayerCount: profile.activePlayerCount,
        activeProjectileCount: profile.activeProjectileCount,
        labelPlanBuilds: this.labelPlanBuilds,
        labelAnchorChanges: this.labelAnchorChanges,
        updatedNodes: profile.updatedNodes.size,
        recreatedNodes: 0,
        rejected: profile.rejectedEntities + this.poolOverflowKeys.size,
      };
      this.frameProfile = null;
      return detail;
    }

    touch(node) {
      if (this.frameProfile) this.frameProfile.updatedNodes.add(node);
    }

    setText(node, value) {
      const next = String(value);
      if (node.textContent === next) return;
      if (node.childNodes.length === 1 && node.firstChild.nodeType === Node.TEXT_NODE) {
        node.firstChild.nodeValue = next;
      } else {
        node.textContent = next;
      }
      this.touch(node);
    }

    setAttribute(node, name, value) {
      const next = String(value);
      if (node.getAttribute(name) === next) return;
      node.setAttribute(name, next);
      this.touch(node);
    }

    setTitle(node, value) {
      const next = String(value);
      if (node.title === next) return;
      node.title = next;
      this.touch(node);
    }

    setHidden(node, hidden) {
      if (node.hidden === hidden) return;
      node.hidden = hidden;
      this.touch(node);
    }

    setData(node, name, value) {
      const next = String(value);
      if (node.dataset[name] === next) return;
      node.dataset[name] = next;
      this.touch(node);
    }

    setStyle(node, name, value) {
      if (node.style[name] === value) return;
      node.style[name] = value;
      this.touch(node);
    }

    setVisible(node, visible, opacity = "1") {
      this.setStyle(node, "visibility", visible ? "visible" : "hidden");
      this.setStyle(node, "opacity", visible ? opacity : "0");
    }

    setTransform(node, x, y) {
      this.setStyle(node, "transform", `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0)`);
    }

    screenPosition(projection) {
      return {
        x: projection.pixel_x * this.scaleX,
        y: projection.pixel_y * this.scaleY,
      };
    }

    levelVisible(projection) {
      if (!projection || projection.inside_image !== true) return false;
      if (["automatic", "both"].includes(this.levelMode)) return true;
      return [this.levelMode, "unknown", "default"].includes(projection.level);
    }

    utilityVisible(type) {
      const all = document.getElementById("utility-all");
      if (all && !all.checked) return false;
      const filterType = ({ he: "he_grenade", flash: "flashbang" })[type] || type;
      const control = document.getElementById(`utility-${filterType}`);
      return !control || control.checked;
    }

    utilityFilterSignature() {
      return [...document.querySelectorAll("[id^='utility-']")]
        .map((control) => `${control.id}:${control.checked}`)
        .join("|");
    }

    acquirePlayerSlot(id) {
      let slot = this.playerSlots.find((item) => item.key === id);
      if (slot) return slot;
      slot = this.playerSlots.find((item) => item.key === null);
      if (!slot) return null;
      slot.key = id;
      this.setData(slot.node, "playerId", id);
      return slot;
    }

    setViewportSize(width, height) {
      const nextWidth = Math.max(1, width);
      const nextHeight = Math.max(1, height);
      if (nextWidth === this.displayWidth && nextHeight === this.displayHeight) return;
      this.displayWidth = nextWidth;
      this.displayHeight = nextHeight;
      this.scaleX = nextWidth / this.mapWidth;
      this.scaleY = nextHeight / this.mapHeight;
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      this.trailsCanvas.width = Math.round(nextWidth * dpr);
      this.trailsCanvas.height = Math.round(nextHeight * dpr);
      this.trailsCanvas.style.width = `${nextWidth}px`;
      this.trailsCanvas.style.height = `${nextHeight}px`;
      this.trailSignature = "";
      this.labelSignature = "";
      if (this.currentSample) this.renderExact(this.currentSample, { forceLabels: true });
    }

    setLevelMode(mode) {
      this.levelMode = mode;
      this.eventSignature = "";
      this.projectileSignature = "";
      this.effectSignature = "";
      this.trailSignature = "";
      this.mapCanvas.dataset.levelMode = mode;
      const badge = document.getElementById("levelBadge");
      const levelLabels = { upper: "Верхний этаж", lower: "Нижний этаж", both: "Оба этажа" };
      if (badge) this.setText(badge, mode === "automatic" ? "Автовыбор этажа" : (levelLabels[mode] || mode));
      if (this.currentSample) this.renderExact(this.currentSample);
    }

    setZoom(zoom) {
      const next = Math.max(1, Number(zoom) || 1);
      if (this.zoom === next) return;
      this.zoom = next;
      this.labelSignature = "";
      if (this.currentSample) this.updateLabels(this.currentSample, true);
    }

    setLabelMode(mode, sample) {
      this.labelMode = mode;
      this.labelSignature = "";
      if (sample) this.updateLabels(sample, true);
    }

    setSelectedPlayer(playerId) {
      const next = playerId || null;
      if (this.selectedPlayerId === next) return;
      this.selectedPlayerId = next;
      this.playerSlots.forEach((slot) => {
        if (slot.key) this.setAttribute(slot.node, "aria-pressed", slot.key === next);
      });
      if (this.currentSample) {
        this.updateSelection(this.currentSample);
      }
    }

    renderExact(sample, { forceLabels = false } = {}) {
      this.beginFrame();
      this.currentSample = sample;
      this.updatePlayerState(sample);
      this.updateLabels(sample, forceLabels);
      this.updateProjectiles(sample.projectile_samples || [], sample.projectile_trails || []);
      this.updateEffects(sample.utility_effects || []);
      this.updateEvents(sample.events || []);
      this.updateBomb(sample);
      this.drawFrame(sample, null, 0, "exact");
      return this.endFrame();
    }

    updateDynamicEvidence(sample) {
      this.updateProjectiles(sample.projectile_samples || [], sample.projectile_trails || []);
      this.updateEffects(sample.utility_effects || []);
      this.updateEvents(sample.events || []);
    }

    updatePlayerState(sample) {
      this.motionSignature = "";
      const active = new Set();
      sample.players.forEach((player) => {
        const id = player.snapshot.participant_id;
        const slot = this.acquirePlayerSlot(id);
        if (!slot) return;
        active.add(id);
        const dead = player.snapshot.alive === false;
        const side = player.snapshot.side || "unknown";
        const zone = player.zone_assignment?.status === "resolved"
          ? player.zone_assignment.zone_name
          : player.zone_assignment?.status === "unknown"
            ? "зона неизвестна"
            : player.zone_assignment?.status === "unavailable"
              ? "зона недоступна"
              : null;
        this.setData(slot.node, "side", side);
        this.setData(slot.label, "side", side);
        this.setData(slot.node, "state", dead ? "dead" : "alive");
        this.setText(
          slot.sideText,
          dead ? "\u00d7" : side === "CT" ? "CT" : side === "T" ? "T" : "?",
        );
        if (slot.playerName !== player.player_name || slot.zoneName !== zone) {
          slot.playerName = player.player_name;
          slot.zoneName = zone;
          this.setTitle(
            slot.node,
            `${player.player_name} · подтверждённая позиция${zone ? ` · ${zone}` : ""}`,
          );
        }
        this.setAttribute(
          slot.node,
          "aria-label",
          [
            player.player_name,
            player.snapshot.side || "сторона неизвестна",
            dead ? "погиб" : "жив",
            player.snapshot.has_bomb ? "несёт C4" : "",
            zone || "",
          ].filter(Boolean).join(", "),
        );
        this.setAttribute(slot.node, "aria-pressed", id === this.selectedPlayerId);
      });
      this.playerSlots.forEach((slot) => {
        if (slot.key && !active.has(slot.key)) {
          this.setVisible(slot.node, false);
          this.setVisible(slot.label, false);
        }
      });
    }

    updateLabels(sample, force = false) {
      const previousPlanSize = this.labelAnchorPlan.size;
      this.labelAnchorPlan = window.StratWebLabels.planAnchors(
        sample.players,
        this.labelAnchorPlan,
      );
      if (this.labelAnchorPlan.size !== previousPlanSize) this.labelPlanBuilds += 1;
      const signature = [
        this.labelMode,
        this.zoom,
        ...sample.players.map((player) => [
          player.snapshot.participant_id,
          player.player_name,
        ].join(":")),
      ].join("|");
      if (!force && signature === this.labelSignature) return;
      this.labelSignature = signature;
      const scaledPlayers = sample.players.map((player) => ({
        ...player,
        projection: player.projection ? {
          ...player.projection,
          pixel_x: player.projection.pixel_x * this.scaleX,
          pixel_y: player.projection.pixel_y * this.scaleY,
        } : null,
      }));
      const layout = window.StratWebLabels.layout(scaledPlayers, {
        mode: this.labelMode,
        zoom: this.zoom,
        anchors: this.labelAnchorPlan,
      });
      sample.players.forEach((player) => {
        const slot = this.acquirePlayerSlot(player.snapshot.participant_id);
        if (!slot) return;
        const item = layout.get(player.snapshot.participant_id)
          || {
            label: "", x: 0, y: 0, anchorId: "E",
          };
        const previousAnchor = slot.label.dataset.anchor;
        if (previousAnchor && previousAnchor !== item.anchorId) {
          this.labelAnchorChanges += 1;
        }
        this.setData(slot.label, "anchor", item.anchorId);
        slot.labelOffset = { x: item.x, y: item.y };
        this.setText(slot.label, item.label);
        this.setVisible(slot.label, Boolean(item.label), ".94");
      });
    }

    prepareMotionPlan(previousSample, followingSample, mode) {
      const signature = [
        previousSample.sample_index ?? previousSample.tick,
        followingSample?.sample_index ?? followingSample?.tick ?? "none",
        mode,
      ].join(":");
      if (signature === this.motionSignature) return;
      this.motionSignature = signature;
      const previous = byPlayer(previousSample);
      const following = followingSample ? byPlayer(followingSample) : new Map();
      this.motionPlan = this.playerSlots
        .filter((slot) => slot.key)
        .map((slot) => {
          const a = previous.get(slot.key);
          const b = following.get(slot.key);
          return {
            slot,
            a,
            b,
            motion: mode === "smooth" ? classifyMotion(a, b) : { eligible: false },
          };
        });
    }

    drawFrame(previousSample, followingSample, alpha, mode) {
      this.prepareMotionPlan(previousSample, followingSample, mode);
      let activePlayers = 0;
      let rejected = 0;
      let selectedEntry = null;
      this.motionPlan.forEach((entry) => {
        const {
          slot,
          a,
          b,
          motion,
        } = entry;
        if (!a) {
          this.setVisible(slot.node, false);
          this.setVisible(slot.label, false);
          return;
        }
        const semantics = sampleSemantics(a, b, alpha, mode, motion);
        let x = a.projection?.pixel_x;
        let y = a.projection?.pixel_y;
        let yaw = a.snapshot.yaw;
        if (mode === "smooth" && motion.eligible && b) {
          x += (b.projection.pixel_x - x) * alpha;
          y += (b.projection.pixel_y - y) * alpha;
          if (a.snapshot.yaw != null && b.snapshot.yaw != null) {
            yaw = interpolateYaw(a.snapshot.yaw, b.snapshot.yaw, alpha);
          }
        }
        if (x == null || y == null || !safeProjection(a) || !this.levelVisible(a.projection)) {
          this.setVisible(slot.node, false);
          this.setVisible(slot.label, false);
          rejected += Number(a.render_status === "rejected");
          return;
        }
        const position = this.screenPosition({ pixel_x: x, pixel_y: y });
        this.setTransform(slot.node, position.x, position.y);
        this.setVisible(slot.node, true, semantics === "dead" ? ".34" : "1");
        if (yaw != null && a.snapshot.availability.view_angles === "available"
            && semantics !== "dead") {
          this.setStyle(slot.direction, "visibility", "visible");
          this.setStyle(slot.direction, "transform", `rotate(${-yaw.toFixed(2)}deg)`);
        } else {
          this.setStyle(slot.direction, "visibility", "hidden");
        }
        const labelVisible = Boolean(slot.label.textContent) && semantics !== "unavailable";
        this.setTransform(
          slot.label,
          position.x + slot.labelOffset.x,
          position.y + slot.labelOffset.y,
        );
        this.setVisible(slot.label, labelVisible, semantics === "dead" ? ".35" : ".94");
        activePlayers += Number(semantics !== "dead");
        if (slot.key === this.selectedPlayerId) {
          selectedEntry = { a, b, motion };
        }
      });
      this.updateSelectionFromEntry(selectedEntry, alpha);
      if (this.frameProfile) {
        this.frameProfile.activePlayerCount = activePlayers;
        this.frameProfile.rejectedEntities = rejected;
      }
    }

    updateSelection(sample) {
      this.motionSignature = "";
      this.prepareMotionPlan(sample, null, "exact");
      const selectedEntry = this.motionPlan.find(
        (entry) => entry.slot.key === this.selectedPlayerId,
      );
      this.updateSelectionFromEntry(selectedEntry || null, 0);
    }

    updateSelectionFromEntry(entry, alpha) {
      if (!this.selectedPlayerId || !entry) {
        this.setVisible(this.selectionSlot.node, false);
        return;
      }
      const { a, b, motion } = entry;
      if (!a || !safeProjection(a) || !this.levelVisible(a.projection)) {
        this.setVisible(this.selectionSlot.node, false);
        return;
      }
      let x = a.projection.pixel_x;
      let y = a.projection.pixel_y;
      if (motion.eligible && b) {
        x += (b.projection.pixel_x - x) * alpha;
        y += (b.projection.pixel_y - y) * alpha;
      }
      const position = this.screenPosition({ pixel_x: x, pixel_y: y });
      this.setTransform(this.selectionSlot.node, position.x, position.y);
      this.setVisible(this.selectionSlot.node, true, ".92");
    }

    assignSlots(slots, rows, keyForRow, updateSlot) {
      const active = new Set(rows.map(keyForRow));
      slots.forEach((slot) => {
        if (slot.key !== null && !active.has(slot.key)) {
          slot.key = null;
          this.setVisible(slot.node, false);
        }
      });
      rows.forEach((row) => {
        const key = keyForRow(row);
        let slot = slots.find((item) => item.key === key);
        if (!slot) {
          slot = slots.find((item) => item.key === null);
          if (!slot) {
            this.poolOverflowKeys.add(key);
            return;
          }
          slot.key = key;
          this.poolOverflowKeys.delete(key);
        }
        updateSlot(slot, row);
      });
    }

    updateProjectiles(projectileSamples, trails) {
      const signature = [
        this.levelMode,
        this.utilityFilterSignature(),
        ...projectileSamples.map((item) => [
          item.projectile.projectile_id,
          item.snapshot.snapshot_id,
          item.snapshot.lifecycle,
          item.render_status,
        ].join(":")),
      ].join("|");
      if (signature !== this.projectileSignature) {
        this.projectileSignature = signature;
        this.assignSlots(
          this.projectileSlots,
          projectileSamples,
          (item) => item.projectile.projectile_id,
          (slot, item) => {
            const type = item.projectile.projectile_type;
            const visible = safeProjection(item)
              && this.levelVisible(item.projection)
              && this.utilityVisible(type);
            this.setData(slot.node, "kind", type);
            this.setAttribute(slot.use, "href", projectileIcon(type));
            this.setTitle(slot.node, `${type} · ${item.snapshot.lifecycle}`);
            if (visible) {
              const position = this.screenPosition(item.projection);
              this.setTransform(slot.node, position.x, position.y);
            }
            this.setVisible(slot.node, visible);
          },
        );
        this.activeProjectileCount = projectileSamples.length;
        if (this.frameProfile) {
          this.frameProfile.activeProjectileCount = projectileSamples.length;
        }
      }
      this.drawTrails(trails);
    }

    drawTrails(trails) {
      const signature = [
        this.levelMode,
        this.utilityFilterSignature(),
        this.displayWidth,
        this.displayHeight,
        ...trails.map((trail) => [
          trail.trail_id,
          trail.points.length,
          trail.points.at(-1)?.pixel_x,
          trail.points.at(-1)?.pixel_y,
        ].join(":")),
      ].join("|");
      if (signature === this.trailSignature) return;
      this.trailSignature = signature;
      this.currentTrails = trails;
      const context = this.trailsCanvas.getContext("2d");
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, this.displayWidth, this.displayHeight);
      const colors = {
        smoke: "#aeb8c5",
        flashbang: "#fff1a3",
        he_grenade: "#ff7770",
        molotov: "#ff9a52",
        incendiary: "#ff9a52",
        decoy: "#b58cff",
      };
      trails.forEach((trail) => {
        if (!this.utilityVisible(trail.projectile_type) || trail.points.length < 2) return;
        context.beginPath();
        trail.points.forEach((point, index) => {
          const position = this.screenPosition(point);
          if (index === 0) context.moveTo(position.x, position.y);
          else context.lineTo(position.x, position.y);
        });
        context.globalAlpha = .62;
        context.strokeStyle = colors[trail.projectile_type] || "#dce5ef";
        context.lineWidth = 1.25;
        context.lineJoin = "round";
        context.lineCap = "round";
        context.stroke();
      });
      context.globalAlpha = 1;
      this.touch(this.trailsCanvas);
    }

    updateEffects(effects) {
      const signature = [
        this.levelMode,
        this.utilityFilterSignature(),
        ...effects.map((item) => [
          item.effect.effect_id,
          item.render_status,
          item.projection?.pixel_x,
          item.projection?.pixel_y,
        ].join(":")),
      ].join("|");
      if (signature === this.effectSignature) return;
      this.effectSignature = signature;
      this.assignSlots(
        this.effectSlots,
        effects,
        (item) => item.effect.effect_id,
        (slot, item) => {
          const type = item.effect.effect_type;
          const visible = safeProjection(item)
            && this.levelVisible(item.projection)
            && this.utilityVisible(type);
          this.setData(slot.node, "kind", type);
          this.setAttribute(slot.use, "href", projectileIcon(type));
          this.setTitle(slot.node, `${type} effect · radius unavailable`);
          if (visible) {
            const position = this.screenPosition(item.projection);
            this.setTransform(slot.node, position.x, position.y);
          }
          this.setVisible(slot.node, visible, ".9");
        },
      );
    }

    updateEvents(events) {
      const signature = [
        this.levelMode,
        ...events.map((event) => [
          event.marker_id,
          event.kind,
          event.render_status,
          event.projection?.pixel_x,
          event.projection?.pixel_y,
        ].join(":")),
      ].join("|");
      if (signature === this.eventSignature) return;
      this.eventSignature = signature;
      this.assignSlots(
        this.eventSlots,
        events.slice(0, EVENT_SLOTS),
        (event) => event.marker_id,
        (slot, event) => {
          const visible = safeProjection(event) && this.levelVisible(event.projection);
          this.setData(slot.node, "kind", event.kind);
          this.setAttribute(slot.use, "href", eventIcon(event.kind));
          this.setAttribute(slot.node, "href", event.temporal_url);
          this.setTitle(slot.node, `${eventLabel(event.kind)} · тик ${event.tick}`);
          if (visible) {
            const position = this.screenPosition(event.projection);
            this.setTransform(slot.node, position.x, position.y);
          }
          this.setVisible(slot.node, visible);
        },
      );
      this.eventCardSlots.forEach((slot, index) => {
        const event = events[index];
        this.setHidden(slot.link, !event);
        if (!event) return;
        this.setAttribute(slot.link, "href", event.temporal_url);
        this.setText(slot.icon, event.kind === "death" ? "×" : "•");
        this.setText(
          slot.text,
          `${eventLabel(event.kind)} · ${event.player_name || "позиция недоступна"}`,
        );
      });
    }

    updateBomb(sample) {
      const visible = sample.bomb_render_status === "available"
        && this.levelVisible(sample.bomb_projection);
      if (visible) {
        const position = this.screenPosition(sample.bomb_projection);
        this.setTransform(this.bombSlot.node, position.x, position.y);
      }
      this.setVisible(this.bombSlot.node, visible);
    }

    focusPoint(sample) {
      const points = (sample.events || [])
        .filter((event) => COMBAT_EVENTS.has(event.kind) && safeProjection(event))
        .map((event) => event.projection);
      if (!points.length) return null;
      return {
        x: points.reduce((sum, point) => sum + point.pixel_x, 0) / points.length,
        y: points.reduce((sum, point) => sum + point.pixel_y, 0) / points.length,
      };
    }

    mapSize() {
      return {
        mapWidth: this.mapWidth,
        mapHeight: this.mapHeight,
        displayWidth: this.displayWidth,
        displayHeight: this.displayHeight,
      };
    }

    nodeCount() {
      return this.mapCanvas.querySelectorAll("*").length + this.eventCards.querySelectorAll("*").length;
    }
  }

  window.StratWebMotion = {
    POLICY,
    classify: classifyMotion,
    semantics: sampleSemantics,
    interpolateYaw,
  };
  window.StratWebMapRenderer = MapRenderer;
})();
