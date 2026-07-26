"use strict";

(() => {
  function addRange(ranges, start, end) {
    if (end < start) return [...ranges];
    const ordered = [...ranges, [start, end]].sort((a, b) => a[0] - b[0]);
    const merged = [];
    ordered.forEach((range) => {
      const previous = merged[merged.length - 1];
      if (!previous || range[0] > previous[1] + 1) merged.push([...range]);
      else previous[1] = Math.max(previous[1], range[1]);
    });
    return merged;
  }

  function nextPrefetchStart(ranges, index, total, reserveRatio = 0.35) {
    const current = ranges.find((range) => range[0] <= index && index <= range[1]);
    if (!current) return null;
    const rangeLength = current[1] - current[0] + 1;
    const reserve = Math.max(8, Math.ceil(rangeLength * reserveRatio));
    if (current[1] - index > reserve) return null;
    const next = current[1] + 1;
    return next < total ? next : null;
  }

  function withinRetention(index, anchor, maximumDistance) {
    return Math.abs(index - anchor) <= maximumDistance;
  }

  function nextPrefetchStartByTime(
    ranges,
    index,
    total,
    ticks,
    playheadTick,
    tickDurationMs,
    speed,
    reserveWallMs = 2500,
  ) {
    const current = ranges.find((range) => range[0] <= index && index <= range[1]);
    if (!current || current[1] + 1 >= total) return null;
    const bufferedEndTick = ticks[current[1]];
    const remainingWallMs = Math.max(0, bufferedEndTick - playheadTick)
      * tickDurationMs / speed;
    return remainingWallMs <= reserveWallMs ? current[1] + 1 : null;
  }

  window.StratWebBufferRanges = {
    addRange,
    nextPrefetchStart,
    nextPrefetchStartByTime,
    withinRetention,
  };
})();
