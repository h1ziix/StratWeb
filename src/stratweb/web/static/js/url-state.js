"use strict";

(() => {
  function setOrDelete(params, key, value) {
    if (value) params.set(key, value);
    else params.delete(key);
  }

  function write(href, state) {
    const url = new URL(href);
    url.searchParams.set("tick", String(state.tick));
    url.searchParams.set("mode", state.mode === "exact" ? "exact" : "smooth");
    setOrDelete(url.searchParams, "team", state.team);
    setOrDelete(url.searchParams, "player", state.player);
    setOrDelete(url.searchParams, "alive_only", state.alive ? "true" : "");
    setOrDelete(url.searchParams, "bomb_carrier_only", state.bomb ? "true" : "");
    return url;
  }

  function read(href) {
    const params = new URL(href).searchParams;
    return {
      tick: Number(params.get("tick")),
      mode: params.get("mode") === "exact" ? "exact" : "smooth",
      team: params.get("team") || "",
      player: params.get("player") || "",
      alive: params.get("alive_only") === "true",
      bomb: params.get("bomb_carrier_only") === "true",
    };
  }

  window.StratWebUrlState = { read, write };
})();
