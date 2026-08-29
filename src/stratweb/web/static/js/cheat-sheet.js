(() => {
  "use strict";

  const sheet = document.querySelector("[data-cheat-sheet]");
  const copyButton = document.getElementById("copyCheatSheet");
  const printButton = document.getElementById("printCheatSheet");
  const status = document.getElementById("cheatSheetStatus");
  if (!sheet) return;

  const planText = () => {
    const lines = [sheet.dataset.cheatHeader || "StratWeb — план на матч"];
    sheet.querySelectorAll("[data-cheat-copy-section]").forEach((section) => {
      const heading = section.querySelector("h2")?.textContent?.trim();
      const items = Array.from(section.querySelectorAll("[data-cheat-copy-item]"))
        .map((item) => item.dataset.cheatCopyText?.trim())
        .filter(Boolean);
      if (!heading || !items.length) return;
      lines.push("", heading.toUpperCase(), ...items.map((item) => `• ${item}`));
    });
    lines.push("", "Исторические данные StratWeb; используйте выводы с учётом размера выборки.");
    return lines.join("\n");
  };

  const copyFallback = (value) => {
    const input = document.createElement("textarea");
    input.value = value;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.append(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    return copied;
  };

  copyButton?.addEventListener("click", async () => {
    try {
      const value = planText();
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
      else if (!copyFallback(value)) throw new Error("copy unavailable");
      status.textContent = "План скопирован — можно отправлять в Discord или чат команды.";
      status.className = "saved";
    } catch {
      status.textContent = "Не удалось скопировать. Выделите текст шпаргалки вручную.";
      status.className = "error";
    }
  });
  printButton?.addEventListener("click", () => window.print());
})();
