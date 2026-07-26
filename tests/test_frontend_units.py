from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
STATIC_JS = Path(__file__).parents[1] / "src" / "stratweb" / "web" / "static" / "js"


def _run_node(source: str, *scripts: Path) -> None:
    assert NODE is not None
    subprocess.run(
        [NODE, "-e", source, *(str(script) for script in scripts)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(NODE is None, reason="Node is optional; browser JS unit runtime unavailable")
def test_label_layout_is_deterministic_and_separates_neighbours() -> None:
    source = r"""
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
const player = (id) => ({
  snapshot: { participant_id: id },
  player_name: `Long player ${id}`,
  projection: { pixel_x: 100, pixel_y: 100 },
});
const players = [player("b"), player("a")];
const first = window.StratWebLabels.layout(players, { mode: "medium", zoom: 2 });
const second = window.StratWebLabels.layout(
  [...players].reverse(),
  { mode: "medium", zoom: 2 },
);
const compact = (layout) => [...layout.entries()];
if (JSON.stringify(compact(first)) !== JSON.stringify(compact(second))) {
  throw new Error("layout is not deterministic");
}
const a = first.get("a");
const b = first.get("b");
if (a.x === b.x && a.y === b.y) throw new Error("neighbouring labels overlap");
if (window.StratWebLabels.shortLabel("alpha-bravo", "short") !== "alpha…") {
  throw new Error("short label is incorrect");
}
if (window.StratWebLabels.shortLabel("alpha-bravo", "medium", 2) !== "alpha-bravo") {
  throw new Error("medium label is incorrect");
}
if (window.StratWebLabels.shortLabel("alpha", "hidden") !== "") {
  throw new Error("hidden mode retained text");
}
if (window.StratWebLabels.resolvedMode("medium", 1) !== "short") {
  throw new Error("zoom did not compact the label");
}
const plan = window.StratWebLabels.planAnchors(players);
const onlyB = window.StratWebLabels.layout(
  [players[0]],
  { mode: "medium", zoom: 2, anchors: plan },
);
if (onlyB.get("b").anchorId !== first.get("b").anchorId) {
  throw new Error("filtering changed a roster-planned anchor");
}
const moved = players.map((item) => ({
  ...item,
  snapshot: { ...item.snapshot, alive: false, has_bomb: true },
  projection: { pixel_x: 600, pixel_y: 50 },
}));
const afterMove = window.StratWebLabels.layout(
  moved,
  { mode: "medium", zoom: 2, anchors: plan },
);
for (const id of ["a", "b"]) {
  if (first.get(id).anchorId !== afterMove.get(id).anchorId) {
    throw new Error("stable anchor changed with gameplay state");
  }
}
"""
    _run_node(source, STATIC_JS / "label-layout.js")


@pytest.mark.skipif(NODE is None, reason="Node is optional; browser JS unit runtime unavailable")
def test_demo_tick_clock_is_density_independent_and_catches_up() -> None:
    source = r"""
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
const { DemoTickClock } = window.StratWebDemoTickClock;
const sparse = new DemoTickClock([0, 16, 32, 64]);
const dense = new DemoTickClock(Array.from({ length: 65 }, (_, index) => index));
sparse.play(0);
dense.play(0);
const sparseEnd = sparse.bracket(1000);
const denseEnd = dense.bracket(1000);
if (!sparseEnd.ended || !denseEnd.ended || sparseEnd.playheadTick !== denseEnd.playheadTick) {
  throw new Error("sample density changed playback duration");
}
const clock = new DemoTickClock(Array.from({ length: 129 }, (_, index) => index));
clock.play(0);
const afterLongFrame = clock.bracket(300);
if (afterLongFrame.leftIndex !== 19 || Math.abs(afterLongFrame.alpha - 0.2) > 0.0001) {
  throw new Error(`long frame did not catch up: ${JSON.stringify(afterLongFrame)}`);
}
const held = clock.pause(300);
if (clock.tickAt(900) !== held) throw new Error("paused clock advanced");
clock.play(900);
clock.setSpeed(4, 950);
const before = clock.tickAt(950);
const after = clock.tickAt(950);
if (before !== after) throw new Error("speed re-anchor jumped");
if (Math.abs(clock.tickAt(1106.25) - (before + 40)) > 0.0001) {
  throw new Error("speed multiplier is incorrect");
}
let rejected = false;
try { new DemoTickClock([1, 1, 2]); } catch { rejected = true; }
if (!rejected) throw new Error("duplicate ticks were accepted");
"""
    _run_node(source, STATIC_JS / "playback-clock.js")


@pytest.mark.skipif(NODE is None, reason="Node is optional; browser JS unit runtime unavailable")
def test_transient_event_buffer_keeps_crossed_events_without_extending_time() -> None:
    source = r"""
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
const { TransientEventBuffer } = window.StratWebEventBuffer;
const buffer = new TransientEventBuffer({ ttlMs: 180, limit: 8 });
const event = (id, tick) => ({ marker_id: id, tick, kind: "shot" });
buffer.add([event("a", 10), event("b", 10), event("c", 11)], 1000);
const visible = buffer.visible([], 1100);
if (visible.map((item) => item.marker_id).join(",") !== "a,b,c") {
  throw new Error("crossed or simultaneous events were lost");
}
if (buffer.visible([], 1180).length !== 0) {
  throw new Error("event TTL was extended or used an inclusive expiry");
}
if (buffer.visible([event("exact", 12)], 2000)[0].marker_id !== "exact") {
  throw new Error("the exact current event was hidden by TTL expiry");
}
"""
    _run_node(source, STATIC_JS / "event-buffer.js")


def test_viewer_renderer_uses_persistent_diffed_nodes() -> None:
    renderer = (STATIC_JS / "map-renderer.js").read_text(encoding="utf-8")
    player = (STATIC_JS / "spatial-player.js").read_text(encoding="utf-8")

    assert "replaceChildren" not in renderer
    assert "innerHTML" not in renderer
    assert "node.getAttribute(name) === next" in renderer
    assert "PLAYER_SLOTS = 12" in renderer
    assert "PROJECTILE_SLOTS = 24" in renderer
    assert "EVENT_SLOTS = 32" in renderer
    assert "createPlayerSlots" in renderer
    assert "translate3d" in renderer
    assert "prepareMotionPlan" in renderer
    assert "projectileSignature" in renderer
    assert "projectileSeries" in player
    assert "latestSampleIndex" in player
    assert "VISUAL_FRAME_INTERVAL" not in player
    assert "if (!state.playing && historyMode) updateUrl" in player
    assert 'window.addEventListener("stratweb:render"' not in player
    assert "utilityFilterSignature" in renderer
    assert "disableAutoFocus" in player
    assert "renderer.beginFrame()" in player
    assert "renderer.endFrame()" in player
    assert "await selectExact(" in player
    assert "state.index >= config.total_samples - 1" in player
    assert "state.starting" in player
    assert "retentionIndex: index" in player
    assert "withinRetention(" in player
    assert "tickClock.bracket(timestamp)" in player
    assert "transitionDuration(" not in player
    assert "labelAnchorPlan" in renderer
    assert "config.label_roster || []" in player
    assert "collectCrossedEvents" in player
    assert "TransientEventBuffer" in player
    assert "prefetchApi.cancel()" in player
    assert "resetFilters({ targetIndex: index, historyMode: null })" in player
    assert "if (operationGeneration !== state.generation) return false" in player
    assert "generation === state.generation" in player
    assert "function invalidatePendingRequests()" in player
    assert "api.cancel();" in player
    assert "setLoading(false);" in player
    assert "Math.round((player.projection" not in renderer


@pytest.mark.skipif(NODE is None, reason="Node is optional; browser JS unit runtime unavailable")
def test_url_state_round_trip_preserves_unrelated_parameters() -> None:
    source = r"""
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
const written = window.StratWebUrlState.write(
  "http://localhost/ui/spatial/m/rounds/1?run_id=pinned&player=stale",
  { tick: 4242, mode: "exact", team: "team-a", player: "", alive: true, bomb: false },
);
if (written.searchParams.get("run_id") !== "pinned") throw new Error("run pin was lost");
if (written.searchParams.has("player")) throw new Error("stale filter was retained");
const restored = window.StratWebUrlState.read(written.toString());
const expected = {
  tick: 4242, mode: "exact", team: "team-a", player: "", alive: true, bomb: false,
};
if (JSON.stringify(restored) !== JSON.stringify(expected)) throw new Error("round trip failed");
"""
    _run_node(source, STATIC_JS / "url-state.js")


@pytest.mark.skipif(NODE is None, reason="Node is optional; browser JS unit runtime unavailable")
def test_buffer_ranges_merge_and_prefetch_once_from_contiguous_edge() -> None:
    source = r"""
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
let ranges = window.StratWebBufferRanges.addRange([], 0, 63);
ranges = window.StratWebBufferRanges.addRange(ranges, 64, 127);
if (JSON.stringify(ranges) !== JSON.stringify([[0, 127]])) throw new Error("merge failed");
if (window.StratWebBufferRanges.nextPrefetchStart([[0, 63]], 39, 460) !== null) {
  throw new Error("prefetch started before threshold");
}
if (window.StratWebBufferRanges.nextPrefetchStart([[0, 63]], 40, 460) !== 64) {
  throw new Error("prefetch did not start at contiguous edge");
}
if (window.StratWebBufferRanges.nextPrefetchStart([[0, 63]], 63, 64) !== null) {
  throw new Error("prefetch crossed round end");
}
if (!window.StratWebBufferRanges.withinRetention(0, 0, 128)) {
  throw new Error("target chunk was not retained");
}
if (window.StratWebBufferRanges.withinRetention(0, 325, 128)) {
  throw new Error("distant chunk was retained against the wrong anchor");
}
const ticks = Array.from({ length: 128 }, (_, index) => index * 16);
if (window.StratWebBufferRanges.nextPrefetchStartByTime(
  [[0, 63]], 0, 128, ticks, 0, 15.625, 1, 2500,
) !== null) {
  throw new Error("time prefetch started with sufficient reserve");
}
if (window.StratWebBufferRanges.nextPrefetchStartByTime(
  [[0, 63]], 40, 128, ticks, ticks[40], 15.625, 4, 2500,
) !== 64) {
  throw new Error("time prefetch ignored playback speed");
}
"""
    _run_node(source, STATIC_JS / "buffer-ranges.js")


@pytest.mark.skipif(NODE is None, reason="Node is optional; browser JS unit runtime unavailable")
def test_motion_policy_rejects_jumps_and_uses_shortest_yaw_path() -> None:
    source = r"""
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
const player = (tick, x, y, yaw = 350) => ({
  render_status: "available",
  projection: { pixel_x: x, pixel_y: y, inside_image: true, level: "default" },
  snapshot: {
    participant_id: "p", round_id: "r", tick, alive: true,
    x, y, z: 0, yaw, position_authority: "parser",
    availability: { position: "available", view_angles: "available" },
  },
});
const normal = window.StratWebMotion.classify(player(10, 0, 0), player(26, 100, 0, 10));
if (!normal.eligible || normal.classification !== "normal") throw new Error("normal rejected");
const jump = window.StratWebMotion.classify(player(10, 0, 0), player(26, 2000, 0));
if (jump.eligible || jump.reason !== "suspicious_spatial_jump") throw new Error("jump accepted");
const yaw = window.StratWebMotion.interpolateYaw(350, 10, 0.5);
if (Math.abs(yaw) > 0.0001) throw new Error(`wrong yaw path: ${yaw}`);
"""
    _run_node(source, STATIC_JS / "map-renderer.js")


@pytest.mark.skipif(NODE is None, reason="Node is optional; browser JS unit runtime unavailable")
def test_zone_editor_math_round_trips_world_and_pixel_space() -> None:
    source = r"""
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
const math = global.window.StratWebZoneMath;
const editor = { world_origin_x: -3230, world_origin_y: 1713, scale: 5 };
const world = math.pixelToWorld(editor, 256, 512);
if (world.x !== -1950 || world.y !== -847) {
  throw new Error("pixelToWorld mismatch: " + JSON.stringify(world));
}
const pixel = math.worldToPixel(editor, world.x, world.y);
if (Math.abs(pixel.x - 256) > 1e-9 || Math.abs(pixel.y - 512) > 1e-9) {
  throw new Error("roundtrip mismatch");
}
const rect = math.normalizeRect(90, 20, 10, 80);
if (rect.x1 !== 10 || rect.y1 !== 20 || rect.x2 !== 90 || rect.y2 !== 80) {
  throw new Error("normalizeRect mismatch");
}
"""
    _run_node(source, STATIC_JS / "zone-editor.js")
