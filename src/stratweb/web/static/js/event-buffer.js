"use strict";

(() => {
  const eventKey = (event) => event.marker_id || event.event_id || null;

  const compareEvents = (left, right) => (
    (Number(left.tick) || 0) - (Number(right.tick) || 0)
    || String(eventKey(left)).localeCompare(String(eventKey(right)))
  );

  class TransientEventBuffer {
    constructor({ ttlMs = 180, limit = 32 } = {}) {
      if (!Number.isFinite(ttlMs) || ttlMs < 0) {
        throw new Error("Event TTL must be finite and non-negative");
      }
      if (!Number.isInteger(limit) || limit < 1) {
        throw new Error("Event buffer limit must be a positive integer");
      }
      this.ttlMs = ttlMs;
      this.limit = limit;
      this.entries = new Map();
    }

    clear() {
      this.entries.clear();
    }

    prune(now) {
      this.entries.forEach((entry, key) => {
        if (entry.expiresAt <= now) this.entries.delete(key);
      });
    }

    add(events, now) {
      if (!Number.isFinite(now)) throw new Error("Event timestamp must be finite");
      events.forEach((event) => {
        const key = eventKey(event);
        if (!key) return;
        this.entries.set(key, { event, expiresAt: now + this.ttlMs });
      });
      this.prune(now);
      const overflow = this.entries.size - this.limit;
      if (overflow <= 0) return;
      [...this.entries.entries()]
        .sort(([, left], [, right]) => compareEvents(left.event, right.event))
        .slice(0, overflow)
        .forEach(([key]) => this.entries.delete(key));
    }

    visible(currentEvents, now) {
      if (!Number.isFinite(now)) throw new Error("Event timestamp must be finite");
      this.prune(now);
      const merged = new Map(
        [...this.entries.entries()].map(([key, entry]) => [key, entry.event]),
      );
      currentEvents.forEach((event) => {
        const key = eventKey(event);
        if (key) merged.set(key, event);
      });
      return [...merged.values()].sort(compareEvents).slice(-this.limit);
    }
  }

  window.StratWebEventBuffer = { TransientEventBuffer, compareEvents, eventKey };
})();
