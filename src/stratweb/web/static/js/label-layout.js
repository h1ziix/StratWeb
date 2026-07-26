"use strict";

(() => {
  const ANCHOR_IDS = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"];

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

  function groupKey(player) {
    return player.snapshot.physical_team_id || player.snapshot.side || "unknown";
  }

  function planAnchors(players, existing = new Map()) {
    const result = new Map(existing);
    const groups = new Map();
    players.forEach((player) => {
      const id = player.snapshot.participant_id;
      if (result.has(id)) return;
      const key = groupKey(player);
      const group = groups.get(key) || [];
      group.push(player);
      groups.set(key, group);
    });
    [...groups.entries()]
      .sort(([a], [b]) => String(a).localeCompare(String(b)))
      .forEach(([key, group]) => {
        const used = new Set(
          players
            .filter((player) => groupKey(player) === key)
            .map((player) => result.get(player.snapshot.participant_id))
            .filter(Boolean),
        );
        const phase = stableHash(key) % ANCHOR_IDS.length;
        group
          .sort((a, b) => a.snapshot.participant_id.localeCompare(
            b.snapshot.participant_id,
          ))
          .forEach((player, ordinal) => {
            let index = (phase + ordinal * 3) % ANCHOR_IDS.length;
            for (let attempt = 0; attempt < ANCHOR_IDS.length; attempt += 1) {
              const candidate = ANCHOR_IDS[index];
              if (!used.has(candidate)) {
                result.set(player.snapshot.participant_id, candidate);
                used.add(candidate);
                return;
              }
              index = (index + 1) % ANCHOR_IDS.length;
            }
            result.set(
              player.snapshot.participant_id,
              ANCHOR_IDS[stableHash(player.snapshot.participant_id) % ANCHOR_IDS.length],
            );
          });
      });
    return result;
  }

  function offsetForAnchor(anchorId, width, zoom) {
    const horizontal = 14 / zoom;
    const diagonal = 11 / zoom;
    const vertical = 20 / zoom;
    const lower = 19 / zoom;
    return {
      E: [horizontal, 4 / zoom],
      NE: [diagonal, -13 / zoom],
      N: [-(width / 2), -vertical],
      NW: [-width - diagonal, -13 / zoom],
      W: [-width - horizontal, 4 / zoom],
      SW: [-width - diagonal, lower],
      S: [-(width / 2), 23 / zoom],
      SE: [diagonal, lower],
    }[anchorId] || [horizontal, 4 / zoom];
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
      const anchorId = anchors.get(id) || "E";
      const width = Math.max(22, label.length * 7) / zoom;
      const [x, y] = offsetForAnchor(anchorId, width, zoom);
      result.set(id, {
        label,
        x,
        y,
        anchorId,
        leader: ["N", "S", "SW", "SE"].includes(anchorId),
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
