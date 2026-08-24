"use strict";

document.querySelectorAll("form[data-submit-feedback]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    const confirmation = form.dataset.confirm;
    if (confirmation && !window.confirm(confirmation)) {
      event.preventDefault();
      return;
    }
    form.setAttribute("aria-busy", "true");
    form.querySelectorAll("button[type='submit']").forEach((button) => {
      button.dataset.idleLabel = button.textContent || "";
      button.disabled = true;
      const loadingLabel = button.dataset.loadingLabel;
      if (loadingLabel) button.textContent = loadingLabel;
    });
  });
});

window.addEventListener("pageshow", () => {
  document.querySelectorAll("form[data-submit-feedback]").forEach((form) => {
    form.removeAttribute("aria-busy");
    form.querySelectorAll("button[type='submit']").forEach((button) => {
      button.disabled = false;
      if (button.dataset.idleLabel) button.textContent = button.dataset.idleLabel;
    });
  });
});
