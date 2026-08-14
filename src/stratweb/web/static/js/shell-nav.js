"use strict";

(() => {
  function navigationScore(link, path, hash) {
    const exact = link.getAttribute("data-nav-exact");
    const prefix = link.getAttribute("data-nav-prefix");
    const requiredHash = link.getAttribute("data-nav-hash");
    const requiresEmptyHash = link.hasAttribute("data-nav-empty-hash");

    if (requiredHash && requiredHash !== hash) return -1;
    if (requiresEmptyHash && hash) return -1;
    if (exact && exact === path) return 10000 + exact.length + (requiredHash ? 1000 : 0);
    if (prefix && path.startsWith(prefix)) return prefix.length;
    return -1;
  }

  function resolveActiveLink(links, locationLike) {
    const path = locationLike.pathname || "/";
    const hash = locationLike.hash || "";
    let selected = null;
    let selectedScore = -1;
    links.forEach((link) => {
      const score = navigationScore(link, path, hash);
      if (score > selectedScore) {
        selected = link;
        selectedScore = score;
      }
    });
    return selectedScore >= 0 ? selected : null;
  }

  function applyActiveNavigation(documentLike, locationLike) {
    const links = [...documentLike.querySelectorAll("[data-nav-exact], [data-nav-prefix]")];
    links.forEach((link) => link.removeAttribute("aria-current"));
    const selected = resolveActiveLink(links, locationLike);
    if (selected) {
      selected.setAttribute("aria-current", "page");
      const container = selected.parentElement;
      if (
        container
        && container.classList.contains("match-nav")
        && container.scrollWidth > container.clientWidth
      ) {
        const left = selected.offsetLeft - ((container.clientWidth - selected.offsetWidth) / 2);
        container.scrollTo({ left: Math.max(0, left), behavior: "auto" });
      }
    }
    return selected;
  }

  window.StratWebShell = { applyActiveNavigation, navigationScore, resolveActiveLink };
  if (typeof document !== "undefined") {
    const apply = () => applyActiveNavigation(document, window.location);
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", apply, { once: true });
    } else {
      apply();
    }
    window.addEventListener("hashchange", apply);
  }
})();
