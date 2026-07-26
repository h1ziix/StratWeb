"use strict";

(() => {
  function validateTicks(ticks) {
    if (!Array.isArray(ticks) || ticks.length === 0) {
      throw new Error("Playback clock requires at least one authoritative tick");
    }
    ticks.forEach((tick, index) => {
      if (!Number.isFinite(tick) || (index > 0 && tick <= ticks[index - 1])) {
        throw new Error("Playback ticks must be finite and strictly increasing");
      }
    });
  }

  function bracketForTick(ticks, tick) {
    if (tick <= ticks[0]) {
      return {
        leftIndex: 0,
        rightIndex: ticks.length > 1 ? 1 : null,
        alpha: 0,
        playheadTick: ticks[0],
        ended: ticks.length === 1,
      };
    }
    const finalIndex = ticks.length - 1;
    if (tick >= ticks[finalIndex]) {
      return {
        leftIndex: finalIndex,
        rightIndex: null,
        alpha: 0,
        playheadTick: ticks[finalIndex],
        ended: true,
      };
    }
    let low = 0;
    let high = finalIndex;
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      if (ticks[middle] <= tick) low = middle + 1;
      else high = middle - 1;
    }
    const leftIndex = Math.max(0, high);
    const rightIndex = leftIndex + 1;
    const span = ticks[rightIndex] - ticks[leftIndex];
    return {
      leftIndex,
      rightIndex,
      alpha: Math.max(0, Math.min(1, (tick - ticks[leftIndex]) / span)),
      playheadTick: tick,
      ended: false,
    };
  }

  class DemoTickClock {
    constructor(ticks, { tickDurationMs = 15.625, speed = 1 } = {}) {
      validateTicks(ticks);
      if (!Number.isFinite(tickDurationMs) || tickDurationMs <= 0) {
        throw new Error("tickDurationMs must be positive and finite");
      }
      this.ticks = [...ticks];
      this.tickDurationMs = tickDurationMs;
      this.speed = 1;
      this.anchorTick = ticks[0];
      this.anchorWallTime = 0;
      this.running = false;
      this.setSpeed(speed, 0);
    }

    tickAt(wallTime) {
      if (!this.running) return this.anchorTick;
      const elapsed = Math.max(0, wallTime - this.anchorWallTime);
      return this.anchorTick + elapsed * this.speed / this.tickDurationMs;
    }

    seekIndex(index, wallTime) {
      const bounded = Math.max(0, Math.min(this.ticks.length - 1, index));
      this.anchorTick = this.ticks[bounded];
      this.anchorWallTime = wallTime;
      return this.anchorTick;
    }

    seekTick(tick, wallTime) {
      this.anchorTick = Math.max(this.ticks[0], Math.min(this.ticks.at(-1), tick));
      this.anchorWallTime = wallTime;
      return this.anchorTick;
    }

    play(wallTime) {
      if (this.running) return;
      this.anchorWallTime = wallTime;
      this.running = true;
    }

    pause(wallTime) {
      this.anchorTick = this.tickAt(wallTime);
      this.anchorWallTime = wallTime;
      this.running = false;
      return this.anchorTick;
    }

    setSpeed(speed, wallTime) {
      if (!Number.isFinite(speed) || speed <= 0) {
        throw new Error("Playback speed must be positive and finite");
      }
      const currentTick = this.tickAt(wallTime);
      this.anchorTick = currentTick;
      this.anchorWallTime = wallTime;
      this.speed = speed;
    }

    bracket(wallTime) {
      return bracketForTick(this.ticks, this.tickAt(wallTime));
    }
  }

  window.StratWebDemoTickClock = { DemoTickClock, bracketForTick, validateTicks };
})();
