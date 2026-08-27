"use strict";

(() => {
  const form = document.querySelector("[data-bulk-import-form]");
  if (!form) return;
  const filesInput = form.querySelector("[data-bulk-files]");
  const folderInput = form.querySelector("[data-bulk-folder]");
  const dropZone = form.querySelector("[data-drop-zone]");
  const summary = form.querySelector("[data-file-summary]");

  function selectedFiles() {
    return [...filesInput.files, ...folderInput.files].filter((file) =>
      /\.(dem|zip)$/i.test(file.name)
    );
  }

  function updateSummary() {
    const files = selectedFiles();
    summary.textContent = files.length
      ? `Выбрано файлов: ${files.length}. Они попадут в один тренировочный пул.`
      : "Файлы ещё не выбраны. Каждая демка получит отдельную задачу и не остановит остальные при ошибке.";
  }

  async function filesFromEntry(entry) {
    if (entry.isFile) {
      return [await new Promise((resolve, reject) => entry.file(resolve, reject))];
    }
    if (!entry.isDirectory) return [];
    const reader = entry.createReader();
    const entries = [];
    while (true) {
      const chunk = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
      if (!chunk.length) break;
      entries.push(...chunk);
    }
    return (await Promise.all(entries.map(filesFromEntry))).flat();
  }

  filesInput.addEventListener("change", updateSummary);
  folderInput.addEventListener("change", updateSummary);
  ["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-dragging");
  }));
  ["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-dragging");
  }));
  dropZone.addEventListener("drop", async (event) => {
    const entries = [...event.dataTransfer.items]
      .map((item) => item.webkitGetAsEntry?.())
      .filter(Boolean);
    const dropped = entries.length
      ? (await Promise.all(entries.map(filesFromEntry))).flat()
      : [...event.dataTransfer.files];
    const accepted = dropped.filter((file) => /\.(dem|zip)$/i.test(file.name));
    const transfer = new DataTransfer();
    accepted.forEach((file) => transfer.items.add(file));
    filesInput.files = transfer.files;
    folderInput.value = "";
    updateSummary();
  });
  form.addEventListener("submit", (event) => {
    if (!selectedFiles().length) {
      event.preventDefault();
      summary.textContent = "Сначала выберите хотя бы одну .dem или ZIP.";
      dropZone.focus();
    }
  });
})();
