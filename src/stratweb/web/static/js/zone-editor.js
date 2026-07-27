"use strict";

(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const SIMPLIFY_EPSILON = 3.5;
  const MIN_TRACE_STEP = 2.5;
  const VERTEX_RADIUS = 6;
  const DRAG_SLOP = 3.5;
  const MAX_VERTICES = 190;

  function normalizeRect(x1, y1, x2, y2) {
    return {
      x1: Math.min(x1, x2),
      y1: Math.min(y1, y2),
      x2: Math.max(x1, x2),
      y2: Math.max(y1, y2),
    };
  }

  function pixelToWorld(editor, px, py) {
    return {
      x: editor.world_origin_x + px * editor.scale,
      y: editor.world_origin_y - py * editor.scale,
    };
  }

  function worldToPixel(editor, wx, wy) {
    return {
      x: (wx - editor.world_origin_x) / editor.scale,
      y: (editor.world_origin_y - wy) / editor.scale,
    };
  }

  function pointToSegmentDistance(point, a, b) {
    const abX = b[0] - a[0];
    const abY = b[1] - a[1];
    const lengthSquared = abX * abX + abY * abY;
    let t = 0;
    if (lengthSquared > 0) {
      t = ((point[0] - a[0]) * abX + (point[1] - a[1]) * abY) / lengthSquared;
      t = Math.max(0, Math.min(1, t));
    }
    const closestX = a[0] + t * abX;
    const closestY = a[1] + t * abY;
    return Math.hypot(point[0] - closestX, point[1] - closestY);
  }

  function simplifyPath(points, epsilon) {
    if (points.length <= 2) {
      return points.slice();
    }
    const first = points[0];
    const last = points[points.length - 1];
    let maxDistance = -1;
    let maxIndex = 0;
    for (let i = 1; i < points.length - 1; i += 1) {
      const distance = pointToSegmentDistance(points[i], first, last);
      if (distance > maxDistance) {
        maxDistance = distance;
        maxIndex = i;
      }
    }
    if (maxDistance <= epsilon) {
      return [first, last];
    }
    const left = simplifyPath(points.slice(0, maxIndex + 1), epsilon);
    const right = simplifyPath(points.slice(maxIndex), epsilon);
    return left.slice(0, -1).concat(right);
  }

  const TRANSLIT = {
    а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z",
    и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r",
    с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "c", ч: "ch", ш: "sh",
    щ: "sch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
  };

  function slugify(name) {
    let result = "";
    for (const char of String(name).toLowerCase()) {
      if (/[a-z0-9]/.test(char)) {
        result += char;
      } else if (Object.prototype.hasOwnProperty.call(TRANSLIT, char)) {
        result += TRANSLIT[char];
      } else {
        result += "_";
      }
    }
    result = result.replace(/_+/g, "_").replace(/^_+|_+$/g, "");
    if (!result || !/^[a-z0-9]/.test(result)) {
      result = "zone" + (result ? "_" + result : "");
    }
    return result.slice(0, 64);
  }

  function readableDetail(detail) {
    if (detail == null) {
      return "";
    }
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      // FastAPI validation errors: a list of {loc, msg, type} objects.
      return detail
        .map((item) => {
          if (item && typeof item === "object") {
            const where = Array.isArray(item.loc) ? item.loc.join(".") + ": " : "";
            return where + (item.msg || JSON.stringify(item));
          }
          return String(item);
        })
        .join("; ");
    }
    return JSON.stringify(detail);
  }

  window.StratWebZoneMath = {
    normalizeRect,
    pixelToWorld,
    worldToPixel,
    pointToSegmentDistance,
    simplifyPath,
    slugify,
    readableDetail,
  };

  if (typeof document === "undefined") {
    return;
  }

  function init() {
    const dataNode = document.getElementById("zoneEditorData");
    const stageNodes = Array.from(document.querySelectorAll(".zone-stage[data-editor-stage]"));
    const editToggle = document.getElementById("zoneEditMode");
    const drawToggle = document.getElementById("zoneDrawMode");
    const saveButton = document.getElementById("zoneSaveButton");
    const deleteButton = document.getElementById("zoneDeleteButton");
    const statusNode = document.getElementById("zoneSaveStatus");
    const namePanel = document.getElementById("zoneNamePanel");
    const nameInput = document.getElementById("zoneNameInput");
    const kindSelect = document.getElementById("zoneKindSelect");
    const nameConfirm = document.getElementById("zoneNameConfirm");
    const nameCancel = document.getElementById("zoneNameCancel");
    if (
      !dataNode ||
      !stageNodes.length ||
      !editToggle ||
      !drawToggle ||
      !saveButton ||
      !statusNode
    ) {
      return;
    }
    const data = JSON.parse(dataNode.textContent);
    if (!data.editor || data.editor.scale == null) {
      return;
    }
    const viewWidth = data.editor.image_width || 1024;
    const viewHeight = data.editor.image_height || 1024;

    const zones = data.zones
      .filter((zone) => zone.polygons_px && zone.polygons_px.length)
      .map((zone) => ({
        zone_id: zone.zone_id,
        zone_name: zone.zone_name,
        kind: zone.kind,
        origin: zone.origin || "authored",
        level: zone.level || "default",
        min_z: zone.min_z == null ? null : zone.min_z,
        max_z: zone.max_z == null ? null : zone.max_z,
        points: zone.polygons_px[0].map((point) => [point[0], point[1]]),
      }));

    const stages = stageNodes
      .map((node) => {
        const svg = node.querySelector("svg");
        if (!svg) {
          return null;
        }
        const layer = document.createElementNS(SVG_NS, "g");
        layer.setAttribute("class", "zone-editor-layer");
        layer.style.display = "none";
        svg.appendChild(layer);
        return { level: node.dataset.editorStage || "default", svg, layer };
      })
      .filter(Boolean);

    const reservedIds = new Set(data.authored_ids || []);
    let selectedId = null;
    let drag = null;
    let trace = null;
    let pendingPoints = null;
    let pendingLevel = "default";
    let dirty = false;

    function stageShowsZone(stage, zone) {
      if (stage.level === "default") {
        return true;
      }
      if (stage.level === "upper") {
        return zone.level !== "lower";
      }
      return zone.level !== "upper";
    }

    function setStatus(text) {
      statusNode.textContent = text;
    }

    function markDirty() {
      dirty = true;
      setStatus("Есть несохранённые изменения");
    }

    function svgPoint(stage, event) {
      const bounds = stage.svg.getBoundingClientRect();
      return [
        Math.max(
          0,
          Math.min(viewWidth, ((event.clientX - bounds.left) / bounds.width) * viewWidth)
        ),
        Math.max(
          0,
          Math.min(viewHeight, ((event.clientY - bounds.top) / bounds.height) * viewHeight)
        ),
      ];
    }

    function zoneById(zoneId) {
      return zones.find((zone) => zone.zone_id === zoneId) || null;
    }

    function uniqueZoneId(baseSlug) {
      const taken = (candidate) =>
        reservedIds.has(candidate) || zones.some((zone) => zone.zone_id === candidate);
      let candidate = baseSlug;
      let suffix = 2;
      while (taken(candidate)) {
        const suffixText = "_" + suffix;
        candidate = baseSlug.slice(0, 64 - suffixText.length) + suffixText;
        suffix += 1;
      }
      return candidate;
    }

    function render() {
      for (const stage of stages) {
        const layer = stage.layer;
        while (layer.firstChild) {
          layer.removeChild(layer.firstChild);
        }
        for (const zone of zones) {
          if (!stageShowsZone(stage, zone)) {
            continue;
          }
          const polygon = document.createElementNS(SVG_NS, "polygon");
          polygon.setAttribute(
            "class",
            "zone-edit-poly" + (zone.zone_id === selectedId ? " selected" : "")
          );
          polygon.setAttribute("points", zone.points.map((p) => p[0] + "," + p[1]).join(" "));
          polygon.dataset.zoneId = zone.zone_id;
          polygon.dataset.role = "body";
          layer.appendChild(polygon);
          const count = zone.points.length;
          const centroid = zone.points.reduce(
            (acc, p) => [acc[0] + p[0] / count, acc[1] + p[1] / count],
            [0, 0]
          );
          const name = document.createElementNS(SVG_NS, "text");
          name.setAttribute("class", "zone-edit-name");
          name.setAttribute("x", centroid[0]);
          name.setAttribute("y", centroid[1]);
          name.textContent = zone.zone_name;
          layer.appendChild(name);
          if (zone.zone_id === selectedId) {
            zone.points.forEach((point, index) => {
              const vertex = document.createElementNS(SVG_NS, "circle");
              vertex.setAttribute("class", "zone-edit-vertex");
              vertex.setAttribute("cx", point[0]);
              vertex.setAttribute("cy", point[1]);
              vertex.setAttribute("r", VERTEX_RADIUS);
              vertex.dataset.zoneId = zone.zone_id;
              vertex.dataset.role = "vertex";
              vertex.dataset.index = String(index);
              layer.appendChild(vertex);
            });
          }
        }
        if (trace && trace.stage === stage && trace.points.length > 1) {
          const path = document.createElementNS(SVG_NS, "polyline");
          path.setAttribute("class", "zone-edit-trace");
          path.setAttribute("points", trace.points.map((p) => p[0] + "," + p[1]).join(" "));
          layer.appendChild(path);
        }
        if (pendingPoints && (stage.level === "default" || stage.level === pendingLevel)) {
          const preview = document.createElementNS(SVG_NS, "polygon");
          preview.setAttribute("class", "zone-edit-trace");
          preview.setAttribute(
            "points",
            pendingPoints.map((p) => p[0] + "," + p[1]).join(" ")
          );
          layer.appendChild(preview);
        }
      }
    }

    function openNamePanel() {
      if (!namePanel || !nameInput) {
        return;
      }
      namePanel.style.display = "";
      nameInput.value = "";
      render();
      nameInput.focus();
    }

    function closeNamePanel() {
      if (namePanel) {
        namePanel.style.display = "none";
      }
      pendingPoints = null;
      render();
    }

    for (const stage of stages) {
      stage.svg.addEventListener("pointerdown", (event) => {
        if (!editToggle.checked || event.button !== 0) {
          return;
        }
        event.preventDefault();
        const point = svgPoint(stage, event);
        if (drawToggle.checked) {
          trace = { stage, points: [point] };
          stage.svg.setPointerCapture(event.pointerId);
          render();
          return;
        }
        const target = event.target;
        const zoneId = target && target.dataset ? target.dataset.zoneId : null;
        if (!zoneId) {
          selectedId = null;
          render();
          return;
        }
        const zone = zoneById(zoneId);
        if (!zone) {
          return;
        }
        selectedId = zoneId;
        // Geometry stays untouched until the pointer travels past DRAG_SLOP,
        // so a plain click selects a zone without nudging it.
        if (target.dataset.role === "vertex") {
          drag = {
            stage,
            zone,
            role: "vertex",
            index: Number(target.dataset.index),
            start: point,
            active: false,
            origin: zone.points[Number(target.dataset.index)].slice(),
          };
        } else {
          drag = {
            stage,
            zone,
            role: "body",
            start: point,
            active: false,
            points: zone.points.map((p) => p.slice()),
          };
        }
        stage.svg.setPointerCapture(event.pointerId);
        render();
      });

      stage.svg.addEventListener("pointermove", (event) => {
        if (!editToggle.checked) {
          return;
        }
        const point = svgPoint(stage, event);
        if (trace && trace.stage === stage) {
          const previous = trace.points[trace.points.length - 1];
          if (Math.hypot(point[0] - previous[0], point[1] - previous[1]) >= MIN_TRACE_STEP) {
            trace.points.push(point);
            render();
          }
          return;
        }
        if (!drag || drag.stage !== stage) {
          return;
        }
        event.preventDefault();
        if (!drag.active) {
          if (Math.hypot(point[0] - drag.start[0], point[1] - drag.start[1]) < DRAG_SLOP) {
            return;
          }
          drag.active = true;
        }
        const deltaX = point[0] - drag.start[0];
        const deltaY = point[1] - drag.start[1];
        if (drag.role === "vertex") {
          drag.zone.points[drag.index] = [
            Math.max(0, Math.min(viewWidth, drag.origin[0] + deltaX)),
            Math.max(0, Math.min(viewHeight, drag.origin[1] + deltaY)),
          ];
        } else {
          // Clamp the shared translation once against the polygon's bounding
          // box so an edge collision stops the whole shape instead of
          // squashing the vertices that hit the border first.
          const minX = Math.min(...drag.points.map((p) => p[0]));
          const maxX = Math.max(...drag.points.map((p) => p[0]));
          const minY = Math.min(...drag.points.map((p) => p[1]));
          const maxY = Math.max(...drag.points.map((p) => p[1]));
          const clampedX = Math.max(-minX, Math.min(viewWidth - maxX, deltaX));
          const clampedY = Math.max(-minY, Math.min(viewHeight - maxY, deltaY));
          drag.zone.points = drag.points.map((p) => [p[0] + clampedX, p[1] + clampedY]);
        }
        markDirty();
        render();
      });

      const endPointer = (event) => {
        if (trace && trace.stage === stage) {
          // Re-simplify with a growing tolerance until the polygon fits the
          // server-side vertex cap; a huge jittery outline must stay savable.
          let epsilon = SIMPLIFY_EPSILON;
          let simplified = simplifyPath(trace.points, epsilon);
          while (simplified.length > MAX_VERTICES && epsilon < 80) {
            epsilon *= 1.6;
            simplified = simplifyPath(trace.points, epsilon);
          }
          const traceLevel = stage.level;
          trace = null;
          if (simplified.length >= 3) {
            pendingPoints = simplified;
            pendingLevel = traceLevel;
            openNamePanel();
          } else {
            setStatus("Обводка слишком короткая — нарисуй замкнутую область");
          }
        }
        if (drag && drag.stage === stage) {
          drag = null;
        }
        if (event.pointerId != null && stage.svg.hasPointerCapture(event.pointerId)) {
          stage.svg.releasePointerCapture(event.pointerId);
        }
        render();
      };
      stage.svg.addEventListener("pointerup", endPointer);
      stage.svg.addEventListener("pointercancel", endPointer);

      stage.svg.addEventListener("dblclick", (event) => {
        if (!editToggle.checked || drawToggle.checked) {
          return;
        }
        const target = event.target;
        const zoneId = target && target.dataset ? target.dataset.zoneId : null;
        const zone = zoneId ? zoneById(zoneId) : null;
        if (!zone) {
          return;
        }
        event.preventDefault();
        if (target.dataset.role === "vertex") {
          if (zone.points.length > 3) {
            zone.points.splice(Number(target.dataset.index), 1);
            markDirty();
          }
        } else {
          if (zone.points.length >= 200) {
            setStatus("У зоны уже максимум вершин");
            return;
          }
          const point = svgPoint(stage, event);
          let bestIndex = 0;
          let bestDistance = Infinity;
          for (let i = 0; i < zone.points.length; i += 1) {
            const a = zone.points[i];
            const b = zone.points[(i + 1) % zone.points.length];
            const distance = pointToSegmentDistance(point, a, b);
            if (distance < bestDistance) {
              bestDistance = distance;
              bestIndex = i;
            }
          }
          zone.points.splice(bestIndex + 1, 0, point);
          markDirty();
        }
        render();
      });
    }

    if (nameConfirm) {
      nameConfirm.addEventListener("click", () => {
        if (!pendingPoints || !nameInput) {
          return;
        }
        const rawName = nameInput.value.trim();
        if (!rawName) {
          nameInput.focus();
          return;
        }
        const level = pendingLevel === "default" ? "default" : pendingLevel;
        const zone = {
          zone_id: uniqueZoneId(slugify(rawName)),
          zone_name: rawName,
          kind: kindSelect ? kindSelect.value : "area",
          origin: "user",
          level,
          min_z: level === "upper" ? data.editor.upper_min_z : null,
          max_z: level === "lower" ? data.editor.lower_max_z : null,
          points: pendingPoints,
        };
        zones.push(zone);
        selectedId = zone.zone_id;
        pendingPoints = null;
        if (namePanel) {
          namePanel.style.display = "none";
        }
        drawToggle.checked = false;
        markDirty();
        render();
      });
    }
    if (nameCancel) {
      nameCancel.addEventListener("click", closeNamePanel);
    }

    if (deleteButton) {
      deleteButton.addEventListener("click", () => {
        const zone = zoneById(selectedId);
        if (!zone) {
          setStatus("Сначала выбери зону кликом");
          return;
        }
        if (!window.confirm("Удалить зону «" + zone.zone_name + "»?")) {
          return;
        }
        zones.splice(zones.indexOf(zone), 1);
        selectedId = null;
        markDirty();
        render();
      });
    }

    editToggle.addEventListener("change", () => {
      for (const stage of stages) {
        stage.layer.style.display = editToggle.checked ? "" : "none";
      }
      if (!editToggle.checked) {
        drawToggle.checked = false;
        closeNamePanel();
      }
      render();
    });

    drawToggle.addEventListener("change", () => {
      if (drawToggle.checked && !editToggle.checked) {
        editToggle.checked = true;
        for (const stage of stages) {
          stage.layer.style.display = "";
        }
        render();
      }
    });

    saveButton.addEventListener("click", async () => {
      if (!zones.length) {
        setStatus("Нет зон для сохранения — нарисуй хотя бы одну");
        return;
      }
      const payload = {
        map_name: data.map_name,
        revision_id: data.revision_id,
        zones: zones.map((zone) => ({
          zone_id: zone.zone_id,
          zone_name: zone.zone_name,
          kind: zone.kind,
          origin: zone.origin,
          level: zone.level,
          min_z: zone.min_z,
          max_z: zone.max_z,
          polygon: zone.points.map((point) => {
            const world = pixelToWorld(data.editor, point[0], point[1]);
            return [world.x, world.y];
          }),
        })),
      };
      setStatus("Сохраняю…");
      try {
        const response = await fetch("/api/dev/zones/" + data.map_name + "/proposal", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(readableDetail(body.detail) || "HTTP " + response.status);
        }
        const result = await response.json();
        dirty = false;
        setStatus("Сохранено: " + result.zone_count + " зон. Обновляю страницу…");
        window.setTimeout(() => window.location.reload(), 700);
      } catch (error) {
        setStatus("Ошибка сохранения: " + error.message);
      }
    });

    window.addEventListener("beforeunload", (event) => {
      if (dirty) {
        event.preventDefault();
      }
    });

    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
