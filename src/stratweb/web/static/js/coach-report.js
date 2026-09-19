"use strict";

const insightTabs = Array.from(document.querySelectorAll("[data-insight-tab]"));
const insightPanels = Array.from(document.querySelectorAll("[data-insight-panel]"));

const selectInsight = (name) => {
  insightTabs.forEach((tab) => {
    const selected = tab.dataset.insightTab === name;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  insightPanels.forEach((panel) => {
    const selected = panel.dataset.insightPanel === name;
    panel.hidden = !selected;
    panel.classList.toggle("is-active", selected);
  });
};

insightTabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectInsight(tab.dataset.insightTab));
  tab.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const nextIndex = (index + offset + insightTabs.length) % insightTabs.length;
    insightTabs[nextIndex].focus();
    selectInsight(insightTabs[nextIndex].dataset.insightTab);
  });
});
