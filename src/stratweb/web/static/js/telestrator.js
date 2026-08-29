(() => {
  "use strict";

  const configNode = document.getElementById("spatialConfig");
  const layer = document.getElementById("telestratorLayer");
  const panel = document.getElementById("telestratorPanel");
  if (!configNode || !layer || !panel) return;

  const config = JSON.parse(configNode.textContent);
  const items = document.getElementById("telestratorItems");
  const preview = document.getElementById("telestratorPreview");
  const toggle = document.getElementById("telestratorToggle");
  const close = document.getElementById("telestratorClose");
  const color = document.getElementById("telestratorColor");
  const width = document.getElementById("telestratorWidth");
  const textInput = document.getElementById("telestratorText");
  const textLabel = document.getElementById("telestratorTextLabel");
  const undo = document.getElementById("telestratorUndo");
  const clear = document.getElementById("telestratorClear");
  const visibility = document.getElementById("telestratorVisibility");
  const save = document.getElementById("telestratorSave");
  const status = document.getElementById("telestratorStatus");
  const toolButtons = Array.from(panel.querySelectorAll("[data-telestrator-tool]"));
  const endpoint = `/api/matches/${config.match_id}/rounds/${config.round_number}/telestrator`;
  const svgNamespace = "http://www.w3.org/2000/svg";

  const state = {
    annotations: [],
    history: [],
    revision: 0,
    tool: "arrow",
    draft: null,
    pointerId: null,
    loaded: false,
    dirty: false,
    hidden: false,
  };

  const svg = (tag, attributes = {}) => {
    const node = document.createElementNS(svgNamespace, tag);
    Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, String(value)));
    return node;
  };

  const scaledPoint = (point) => ({ x: point.x * 1000, y: point.y * 1000 });

  const appendAnnotation = (parent, annotation, isPreview = false) => {
    const points = annotation.points.map(scaledPoint);
    const common = {
      stroke: annotation.color,
      "stroke-width": annotation.width,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "vector-effect": "non-scaling-stroke",
      opacity: isPreview ? 0.72 : 0.96,
    };
    let node;
    if (annotation.tool === "pencil") {
      const path = points.map((point, index) => `${index ? "L" : "M"}${point.x},${point.y}`).join(" ");
      node = svg("path", { ...common, d: path, fill: "none" });
    } else if (annotation.tool === "zone") {
      const [start, end] = points;
      node = svg("ellipse", {
        ...common,
        cx: (start.x + end.x) / 2,
        cy: (start.y + end.y) / 2,
        rx: Math.max(2, Math.abs(end.x - start.x) / 2),
        ry: Math.max(2, Math.abs(end.y - start.y) / 2),
        fill: annotation.color,
        "fill-opacity": isPreview ? 0.08 : 0.13,
        "stroke-dasharray": "12 8",
      });
    } else if (annotation.tool === "arrow") {
      const [start, end] = points;
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const length = Math.hypot(dx, dy) || 1;
      const ux = dx / length;
      const uy = dy / length;
      const head = Math.min(34, Math.max(17, annotation.width * 4));
      const wing = head * 0.48;
      const baseX = end.x - ux * head;
      const baseY = end.y - uy * head;
      const group = svg("g", { opacity: common.opacity });
      group.append(svg("line", {
        ...common,
        opacity: 1,
        x1: start.x,
        y1: start.y,
        x2: baseX + ux * 2,
        y2: baseY + uy * 2,
      }));
      group.append(svg("polygon", {
        points: `${end.x},${end.y} ${baseX - uy * wing},${baseY + ux * wing} ${baseX + uy * wing},${baseY - ux * wing}`,
        fill: annotation.color,
      }));
      node = group;
    } else {
      const point = points[0];
      node = svg("text", {
        x: point.x,
        y: point.y,
        fill: annotation.color,
        stroke: "#071015",
        "stroke-width": 3,
        "paint-order": "stroke",
        "font-size": Math.max(22, annotation.width * 5),
        "font-family": "Inter, system-ui, sans-serif",
        "font-weight": 800,
      });
      node.textContent = annotation.text;
    }
    node.dataset.annotationId = annotation.annotation_id;
    parent.append(node);
  };

  const render = () => {
    items.replaceChildren();
    preview.replaceChildren();
    if (!state.hidden) state.annotations.forEach((annotation) => appendAnnotation(items, annotation));
    if (state.draft) appendAnnotation(preview, state.draft, true);
    undo.disabled = state.history.length === 0;
    clear.disabled = state.annotations.length === 0;
    save.disabled = !state.loaded || !state.dirty;
  };

  const setStatus = (message, kind = "") => {
    status.textContent = message;
    status.className = `telestrator-status${kind ? ` ${kind}` : ""}`;
  };

  const setDirty = () => {
    state.dirty = true;
    setStatus("Есть несохранённые изменения", "pending");
  };

  const commit = (nextAnnotations) => {
    state.history.push(state.annotations);
    if (state.history.length > 50) state.history.shift();
    state.annotations = nextAnnotations;
    setDirty();
    render();
  };

  const selectTool = (tool) => {
    state.tool = tool;
    toolButtons.forEach((button) => {
      const active = button.dataset.telestratorTool === tool;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    textLabel.hidden = tool !== "text";
  };

  const pointFromEvent = (event) => {
    const rect = layer.getBoundingClientRect();
    const clamp = (value) => Math.max(0, Math.min(1, value));
    return {
      x: Number(clamp((event.clientX - rect.left) / rect.width).toFixed(5)),
      y: Number(clamp((event.clientY - rect.top) / rect.height).toFixed(5)),
    };
  };

  const annotation = (tool, points, annotationText = null) => ({
    annotation_id: globalThis.crypto?.randomUUID?.() ?? `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0").slice(-12)}`,
    tool,
    points,
    color: color.value,
    width: Number(width.value),
    text: annotationText,
  });

  const stopMapGesture = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };

  layer.addEventListener("pointerdown", (event) => {
    if (!state.loaded || event.button !== 0) return;
    stopMapGesture(event);
    const point = pointFromEvent(event);
    if (state.tool === "text") {
      const value = textInput.value.trim();
      if (!value) {
        setStatus("Сначала введите подпись", "error");
        textInput.focus();
        return;
      }
      commit([...state.annotations, annotation("text", [point], value)]);
      return;
    }
    state.pointerId = event.pointerId;
    layer.setPointerCapture(event.pointerId);
    state.draft = annotation(state.tool, state.tool === "pencil" ? [point] : [point, point]);
    render();
  });

  layer.addEventListener("pointermove", (event) => {
    if (!state.draft || event.pointerId !== state.pointerId) return;
    stopMapGesture(event);
    const point = pointFromEvent(event);
    if (state.draft.tool === "pencil") {
      const last = state.draft.points.at(-1);
      if (Math.hypot(point.x - last.x, point.y - last.y) < 0.003) return;
      state.draft.points.push(point);
      if (state.draft.points.length > 512) state.draft.points.shift();
    } else {
      state.draft.points[1] = point;
    }
    render();
  });

  const finishDrawing = (event) => {
    if (!state.draft || event.pointerId !== state.pointerId) return;
    stopMapGesture(event);
    const draft = state.draft;
    state.draft = null;
    state.pointerId = null;
    if (draft.tool !== "pencil" || draft.points.length >= 2) {
      commit([...state.annotations, draft]);
    } else {
      render();
    }
  };
  layer.addEventListener("pointerup", finishDrawing);
  layer.addEventListener("pointercancel", (event) => {
    if (event.pointerId !== state.pointerId) return;
    state.draft = null;
    state.pointerId = null;
    render();
  });
  layer.addEventListener("contextmenu", stopMapGesture);

  const openPanel = () => {
    panel.hidden = false;
    layer.classList.add("is-editing");
    toggle.setAttribute("aria-expanded", "true");
  };
  const closePanel = () => {
    panel.hidden = true;
    layer.classList.remove("is-editing");
    toggle.setAttribute("aria-expanded", "false");
    state.draft = null;
    render();
  };

  toggle.addEventListener("click", () => (panel.hidden ? openPanel() : closePanel()));
  close.addEventListener("click", closePanel);
  toolButtons.forEach((button) => button.addEventListener("click", () => selectTool(button.dataset.telestratorTool)));
  panel.addEventListener("pointerdown", (event) => event.stopPropagation());
  panel.addEventListener("pointermove", (event) => event.stopPropagation());
  panel.addEventListener("pointerup", (event) => event.stopPropagation());
  panel.addEventListener("wheel", (event) => event.stopPropagation());

  undo.addEventListener("click", () => {
    if (!state.history.length) return;
    state.annotations = state.history.pop();
    setDirty();
    render();
  });
  clear.addEventListener("click", () => {
    if (!state.annotations.length) return;
    commit([]);
  });
  visibility.addEventListener("click", () => {
    state.hidden = !state.hidden;
    visibility.textContent = state.hidden ? "Показать" : "Скрыть";
    visibility.setAttribute("aria-pressed", String(state.hidden));
    render();
  });

  save.addEventListener("click", async () => {
    save.disabled = true;
    setStatus("Сохраняем…");
    try {
      const response = await fetch(endpoint, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: state.revision, annotations: state.annotations }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Не удалось сохранить разметку");
      state.revision = payload.revision;
      state.annotations = payload.annotations;
      state.history = [];
      state.dirty = false;
      setStatus(`Сохранено · версия ${state.revision}`, "saved");
    } catch (error) {
      setStatus(error.message || "Не удалось сохранить разметку", "error");
    }
    render();
  });

  const load = async () => {
    try {
      const response = await fetch(endpoint, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Не удалось загрузить разметку");
      state.revision = payload.revision;
      state.annotations = payload.annotations;
      state.loaded = true;
      state.dirty = false;
      setStatus(payload.revision ? `Сохранено · версия ${payload.revision}` : "Разметки пока нет", "saved");
    } catch (error) {
      setStatus(error.message || "Не удалось загрузить разметку", "error");
    }
    render();
  };

  selectTool("arrow");
  render();
  void load();
})();
