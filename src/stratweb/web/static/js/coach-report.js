"use strict";

document.documentElement.classList.add("coach-js");

const coachDeck = document.querySelector("[data-coach-deck]");
const coachStart = document.querySelector("[data-coach-start]");

if (coachDeck && coachStart) {
  coachDeck.hidden = false;
  const steps = Array.from(coachDeck.querySelectorAll("[data-coach-step]"));
  const previous = coachDeck.querySelector("[data-coach-previous]");
  const next = coachDeck.querySelector("[data-coach-next]");
  const current = coachDeck.querySelector("[data-coach-current]");
  const total = coachDeck.querySelector("[data-coach-total]");
  const progress = coachDeck.querySelector("[data-coach-progress]");
  const nextLabel = coachDeck.dataset.nextLabel || "Next";
  const finishLabel = coachDeck.dataset.finishLabel || "Finish";
  let activeIndex = Math.max(0, steps.findIndex((item) => `#${item.id}` === window.location.hash));
  let touchStartX = 0;
  let touchStartY = 0;

  const setButtonLabel = (button, label, arrow) => {
    if (!button) return;
    button.replaceChildren(document.createTextNode(`${label} `));
    const icon = document.createElement("span");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = arrow;
    button.append(icon);
  };

  const showStep = (index, { focus = false } = {}) => {
    activeIndex = Math.min(Math.max(index, 0), steps.length - 1);
    steps.forEach((step, stepIndex) => {
      const isActive = stepIndex === activeIndex;
      step.classList.toggle("is-active", isActive);
      step.setAttribute("aria-hidden", String(!isActive));
    });
    if (current) current.textContent = String(activeIndex + 1);
    if (total) total.textContent = String(steps.length);
    if (progress) progress.style.width = `${((activeIndex + 1) / steps.length) * 100}%`;
    if (previous) previous.disabled = activeIndex === 0;
    setButtonLabel(next, activeIndex === steps.length - 1 ? finishLabel : nextLabel, activeIndex === steps.length - 1 ? "↺" : "→");
    if (coachDeck.classList.contains("is-started")) {
      window.history.replaceState(null, "", `#${steps[activeIndex].id}`);
    }
    if (focus) {
      const heading = steps[activeIndex].querySelector("h2");
      if (heading) {
        heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: true });
      }
    }
  };

  const start = (event) => {
    if (event) event.preventDefault();
    coachDeck.classList.add("is-started");
    showStep(activeIndex);
    coachDeck.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  coachStart.addEventListener("click", start);
  previous?.addEventListener("click", () => showStep(activeIndex - 1, { focus: true }));
  next?.addEventListener("click", () => {
    if (activeIndex === steps.length - 1) {
      activeIndex = 0;
      coachDeck.classList.remove("is-started");
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      coachStart.scrollIntoView({ behavior: "smooth", block: "center" });
      coachStart.focus({ preventScroll: true });
      return;
    }
    showStep(activeIndex + 1, { focus: true });
  });

  coachDeck.addEventListener("touchstart", (event) => {
    touchStartX = event.changedTouches[0].clientX;
    touchStartY = event.changedTouches[0].clientY;
  }, { passive: true });
  coachDeck.addEventListener("touchend", (event) => {
    const deltaX = event.changedTouches[0].clientX - touchStartX;
    const deltaY = event.changedTouches[0].clientY - touchStartY;
    if (Math.abs(deltaX) < 55 || Math.abs(deltaX) < Math.abs(deltaY) * 1.2) return;
    showStep(deltaX < 0 ? activeIndex + 1 : activeIndex - 1);
  }, { passive: true });

  if (window.location.hash.startsWith("#coach-step-")) start();
  else showStep(0);
}
