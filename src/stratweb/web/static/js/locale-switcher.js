(() => {
  "use strict";

  const switcher = document.querySelector("[data-locale-switch]");
  if (!(switcher instanceof HTMLSelectElement)) return;

  switcher.addEventListener("change", () => {
    const next = new URL(window.location.href);
    next.searchParams.set("lang", switcher.value);
    next.searchParams.delete("page");
    window.location.assign(next.toString());
  });
})();
