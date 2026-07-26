"use strict";

(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const MIN_SIDE = 14;

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

  window.StratWebZoneMath = { normalizeRect, pixelToWorld, worldToPixel };

  if (typeof document === "undefined") {
    return;
  }

  function init() {
    const dataNode = document.getElementById("zoneEditorData");
    const stage = document.querySelector(".zone-stage");
    const svg = stage ? stage.querySelector("svg") : null;
    const editToggle = document.getElementById("zoneEditMode");
    const saveButton = document.getElementById("zoneSaveButton");
    const statusNode = document.getElementById("zoneSaveStatus");
    if (!dataNode || !svg || !editToggle || !saveButton || !statusNode) {
      return;
    }
    const data = JSON.parse(dataNode.textContent);
    if (!data.editor || data.editor.scale == null) {
      return;
    }
    const viewWidth = data.editor.image_width || 1024;
    const viewHeight = data.editor.image_height || 1024;
    const zones = data.zones
      .filter((zone) => zone.bbox)
      .map((zone) => ({
        zone_id: zone.zone_id,
        zone_name: zone.zone_name,
        kind: zone.kind,
        rect: normalizeRect(zone.bbox.px_x1, zone.bbox.px_y1, zone.bbox.px_x2, zone.bbox.px_y2),
      }));

    const layer = document.createElementNS(SVG_NS, "g");
    layer.setAttribute("id", "zoneEditorLayer");
    layer.style.display = "none";
    svg.appendChild(layer);

    let selectedId = null;
    let drag = null;
    let dirty = false;

    function setStatus(text) {
      statusNode.textContent = text;
    }

    function svgPoint(event) {
      const bounds = svg.getBoundingClientRect();
      return {
        x: ((event.clientX - bounds.left) / bounds.width) * viewWidth,
        y: ((event.clientY - bounds.top) / bounds.height) * viewHeight,
      };
    }

    function render() {
      while (layer.firstChild) {
        layer.removeChild(layer.firstChild);
      }
      for (const zone of zones) {
        const rect = document.createElementNS(SVG_NS, "rect");
        rect.setAttribute("class", "zone-edit-rect" + (zone.zone_id === selectedId ? " selected" : ""));
        rect.setAttribute("x", zone.rect.x1);
        rect.setAttribute("y", zone.rect.y1);
        rect.setAttribute("width", zone.rect.x2 - zone.rect.x1);
        rect.setAttribute("height", zone.rect.y2 - zone.rect.y1);
        rect.dataset.zoneId = zone.zone_id;
        rect.dataset.role = "body";
        layer.appendChild(rect);
        const name = document.createElementNS(SVG_NS, "text");
        name.setAttribute("class", "zone-edit-name");
        name.setAttribute("x", (zone.rect.x1 + zone.rect.x2) / 2);
        name.setAttribute("y", zone.rect.y1 + 18);
        name.textContent = zone.zone_name;
        layer.appendChild(name);
        const handle = document.createElementNS(SVG_NS, "rect");
        handle.setAttribute("class", "zone-edit-handle");
        handle.setAttribute("x", zone.rect.x2 - 7);
        handle.setAttribute("y", zone.rect.y2 - 7);
        handle.setAttribute("width", 14);
        handle.setAttribute("height", 14);
        handle.dataset.zoneId = zone.zone_id;
        handle.dataset.role = "handle";
        layer.appendChild(handle);
      }
    }

    function zoneById(zoneId) {
      return zones.find((zone) => zone.zone_id === zoneId) || null;
    }

    svg.addEventListener("pointerdown", (event) => {
      if (!editToggle.checked) {
        return;
      }
      const target = event.target;
      const zoneId = target && target.dataset ? target.dataset.zoneId : null;
      if (!zoneId) {
        return;
      }
      const zone = zoneById(zoneId);
      if (!zone) {
        return;
      }
      event.preventDefault();
      selectedId = zoneId;
      drag = {
        zone,
        role: target.dataset.role,
        start: svgPoint(event),
        rect: { ...zone.rect },
      };
      svg.setPointerCapture(event.pointerId);
      render();
    });

    svg.addEventListener("pointermove", (event) => {
      if (!drag) {
        return;
      }
      event.preventDefault();
      const point = svgPoint(event);
      const deltaX = point.x - drag.start.x;
      const deltaY = point.y - drag.start.y;
      const rect = drag.rect;
      if (drag.role === "handle") {
        drag.zone.rect = normalizeRect(
          rect.x1,
          rect.y1,
          Math.min(viewWidth, Math.max(rect.x1 + MIN_SIDE, rect.x2 + deltaX)),
          Math.min(viewHeight, Math.max(rect.y1 + MIN_SIDE, rect.y2 + deltaY))
        );
      } else {
        const width = rect.x2 - rect.x1;
        const height = rect.y2 - rect.y1;
        const x1 = Math.min(Math.max(rect.x1 + deltaX, 0), viewWidth - width);
        const y1 = Math.min(Math.max(rect.y1 + deltaY, 0), viewHeight - height);
        drag.zone.rect = { x1, y1, x2: x1 + width, y2: y1 + height };
      }
      dirty = true;
      setStatus("Есть несохранённые изменения");
      render();
    });

    function endDrag(event) {
      if (drag) {
        drag = null;
        if (event.pointerId != null && svg.hasPointerCapture(event.pointerId)) {
          svg.releasePointerCapture(event.pointerId);
        }
      }
    }
    svg.addEventListener("pointerup", endDrag);
    svg.addEventListener("pointercancel", endDrag);

    editToggle.addEventListener("change", () => {
      layer.style.display = editToggle.checked ? "" : "none";
      if (editToggle.checked) {
        render();
      }
    });

    saveButton.addEventListener("click", async () => {
      const payload = {
        map_name: data.map_name,
        revision_id: data.revision_id,
        zones: zones.map((zone) => {
          const topLeft = pixelToWorld(data.editor, zone.rect.x1, zone.rect.y1);
          const bottomRight = pixelToWorld(data.editor, zone.rect.x2, zone.rect.y2);
          return {
            zone_id: zone.zone_id,
            x1: topLeft.x,
            y1: topLeft.y,
            x2: bottomRight.x,
            y2: bottomRight.y,
          };
        }),
      };
      setStatus("Сохраняю…");
      try {
        const response = await fetch(`/api/dev/zones/${data.map_name}/proposal`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.detail || `HTTP ${response.status}`);
        }
        const result = await response.json();
        dirty = false;
        setStatus(`Сохранено: ${result.zone_count} зон → ${result.file}`);
      } catch (error) {
        setStatus(`Ошибка сохранения: ${error.message}`);
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
