"use strict";

(() => {
  const definition = JSON.parse(document.getElementById("mapDefinition").textContent);
  const form = document.getElementById("calibrationForm");
  const result = document.getElementById("calibrationResult");
  const points = document.getElementById("candidatePoints");
  const layer = document.getElementById("calibrationPoints");
  const stage = document.getElementById("calibrationStage");
  const levelControl = document.getElementById("calibrationLevel");
  const saved = [];
  const number = (id) => {
    const value = document.getElementById(id).value;
    return value === "" ? null : Number(value);
  };
  const query = () => {
    const x = number("pointX");
    const y = number("pointY");
    if (x === null || y === null) throw new Error("Raw X and Y are required");
    const params = new URLSearchParams({
      map_name: definition.canonical_name,
      revision: definition.map_revision.revision_id,
      x: String(x), y: String(y),
    });
    [["z", "pointZ"], ["origin_x", "originX"], ["origin_y", "originY"],
      ["scale", "candidateScale"], ["level_split_z", "levelSplit"]].forEach(([key, id]) => {
      const value = number(id);
      if (value !== null) params.set(key, String(value));
    });
    return params;
  };
  async function evaluate() {
    const response = await fetch(`/api/dev/maps/transform-candidate?${query()}`);
    if (!response.ok) throw new Error(`Calibration request failed (${response.status})`);
    return response.json();
  }
  function show(payload) {
    const item = payload.result;
    result.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = item.pixel_x == null ? "pixel unavailable" : `pixel ${item.pixel_x.toFixed(2)}, ${item.pixel_y.toFixed(2)}`;
    const status = document.createElement("span");
    status.textContent = `level ${item.level} · ${item.availability}${item.warnings.length ? ` · ${item.warnings.join(", ")}` : ""}`;
    result.append(strong, status);
    if (stage && levelControl?.value === "automatic" && ["upper", "lower"].includes(item.level)) {
      stage.dataset.levelMode = item.level;
    }
  }
  function renderSaved() {
    points.replaceChildren();
    if (layer) layer.replaceChildren();
    saved.forEach((entry, index) => {
      const row = document.createElement("tr");
      [String(index + 1), `${entry.raw.x}, ${entry.raw.y}, ${entry.raw.z}`, entry.result.pixel_x == null ? "—" : `${entry.result.pixel_x.toFixed(2)}, ${entry.result.pixel_y.toFixed(2)}`, entry.result.level, entry.result.warnings.join(", ") || "—"].forEach((value) => {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      });
      points.append(row);
      if (layer && entry.result.pixel_x != null) {
        const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        marker.setAttribute("cx", entry.result.pixel_x); marker.setAttribute("cy", entry.result.pixel_y); marker.setAttribute("r", 10); layer.append(marker);
      }
    });
  }
  form.addEventListener("submit", async (event) => { event.preventDefault(); try { show(await evaluate()); } catch (error) { result.textContent = error.message; } });
  document.getElementById("addPoint").addEventListener("click", async () => {
    try {
      const payload = await evaluate(); show(payload);
      saved.push({ raw: { x: number("pointX"), y: number("pointY"), z: number("pointZ") }, result: payload.result });
      renderSaved();
    } catch (error) { result.textContent = error.message; }
  });
  document.getElementById("calibrationMap").addEventListener("change", (event) => { location.href = `/ui/maps/calibration?map_name=${encodeURIComponent(event.target.value)}`; });
  document.getElementById("calibrationRevision").addEventListener("change", (event) => { location.href = `/ui/maps/calibration?map_name=${encodeURIComponent(definition.canonical_name)}&revision=${encodeURIComponent(event.target.value)}`; });
  levelControl?.addEventListener("change", () => {
    if (levelControl.value === "automatic") {
      evaluate().then((payload) => {
        const level = payload.result.level;
        stage.dataset.levelMode = ["upper", "lower"].includes(level) ? level : "upper";
      }).catch((error) => { result.textContent = error.message; });
      return;
    }
    stage.dataset.levelMode = levelControl.value;
  });
  document.getElementById("exportCandidate").addEventListener("click", () => {
    const payload = { accepted: false, persisted: false, canonical_name: definition.canonical_name, base_revision: definition.map_revision.revision_id, candidate: { world_origin_x: number("originX"), world_origin_y: number("originY"), scale: number("candidateScale"), level_split_z: number("levelSplit") }, points: saved };
    const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `${definition.canonical_name}-calibration-candidate.json`; link.click(); URL.revokeObjectURL(link.href);
  });
})();
