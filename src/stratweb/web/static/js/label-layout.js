"use strict";

(() => {
  const ANCHOR_IDS = ["S"];

  function resolvedMode(mode, zoom = 1) {
    if (mode === "hidden" || mode === "markers") return "hidden";
    if (mode === "short" || mode === "initials") return "short";
    return zoom < 1.35 ? "short" : "medium";
  }

  function shortLabel(name, mode = "medium", zoom = 1) {
    const selected = resolvedMode(mode, zoom);
    if (selected === "hidden") return "";
    const trimmed = name.trim();
    const maximum = selected === "short" ? 6 : 12;
    return trimmed.length > maximum ? `${trimmed.slice(0, maximum - 1)}…` : trimmed;
  }

  function stableHash(value) {
    let hash = 2166136261;
    for (const character of String(value)) {
      hash ^= character.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function planAnchors(players, existing = new Map()) {
    const result = new Map(existing);
    players.forEach((player) => {
      const id = player.snapshot.participant_id;
      result.set(id, "S");
    });
    return result;
  }

  function offsetForAnchor(anchorId, width, zoom) {
    return [-(width / 2), 17 / zoom];
  }

  function layout(players, options = {}) {
    const settings = typeof options === "string" ? { mode: options } : options;
    const mode = settings.mode || "medium";
    const zoom = Math.max(1, Number(settings.zoom) || 1);
    const ordered = [...players].sort(
      (a, b) => a.snapshot.participant_id.localeCompare(b.snapshot.participant_id),
    );
    const anchors = settings.anchors instanceof Map
      ? planAnchors(ordered, settings.anchors)
      : planAnchors(ordered);
    const result = new Map();
    ordered.forEach((player) => {
      const id = player.snapshot.participant_id;
      const label = shortLabel(player.player_name, mode, zoom);
      const anchorId = anchors.get(id) || "S";
      const width = Math.max(22, label.length * 7) / zoom;
      const [x, y] = offsetForAnchor(anchorId, width, zoom);
      result.set(id, {
        label,
        x,
        y,
        anchorId,
        leader: false,
        resolvedMode: resolvedMode(mode, zoom),
      });
    });
    return result;
  }

  window.StratWebLabels = {
    ANCHOR_IDS,
    layout,
    offsetForAnchor,
    planAnchors,
    resolvedMode,
    shortLabel,
    stableHash,
  };
})();
