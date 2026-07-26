"use strict";

window.StratWebApi = class StratWebApi {
  constructor() {
    this.controller = null;
    this.fetchCount = 0;
  }

  cancel() {
    if (this.controller) this.controller.abort();
    this.controller = null;
  }

  async json(url, { cancelPrevious = false } = {}) {
    if (cancelPrevious) this.cancel();
    this.controller = new AbortController();
    this.fetchCount += 1;
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: this.controller.signal,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Request failed (${response.status})`);
    }
    return response.json();
  }
};
