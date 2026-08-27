"use strict";

(() => {
  const config = JSON.parse(document.getElementById("batchConfig").textContent);
  const api = new window.StratWebApi();
  const labels = {
    queued: "В очереди", canonicalizing: "Разбираем демку", importing: "Сохраняем матч",
    economy: "Считаем закуп", analytics: "Считаем игровые факты", temporal: "Строим раунды",
    spatial: "Читаем позиции", zones: "Определяем зоны", features: "Готовим факты",
    complete: "Готово", failed: "Ошибка", cancelled: "Отменено", cancel_requested: "Отменяем",
  };

  function statusClass(stage) {
    if (stage === "complete") return "available";
    if (["failed", "cancelled"].includes(stage)) return "unavailable";
    return "partial";
  }

  function renderItem(entry) {
    const item = entry.item;
    const article = document.createElement("article");
    article.className = "batch-file";
    const identity = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = item.original_name;
    const message = document.createElement("small");
    identity.append(name, message);
    const status = document.createElement("span");
    const progress = document.createElement("span");
    const action = document.createElement("span");
    if (entry.job) {
      message.textContent = labels[entry.job.stage] || entry.job.message;
      status.className = `status ${statusClass(entry.job.stage)}`;
      status.textContent = labels[entry.job.stage] || entry.job.stage;
      progress.textContent = `${entry.job.progress_percent}%`;
      const link = document.createElement("a");
      link.className = "button secondary";
      link.href = entry.job.match_id && entry.job.stage === "complete"
        ? `/ui/matches/${entry.job.match_id}` : `/ui/import-jobs/${entry.job.job_id}`;
      link.textContent = entry.job.stage === "complete" ? "Открыть матч" : "Подробнее";
      action.append(link);
    } else if (item.existing_match_id) {
      message.textContent = "Эта демка уже была в библиотеке";
      status.className = "status partial";
      status.textContent = "Уже загружена";
      progress.textContent = "100%";
      const link = document.createElement("a");
      link.className = "button secondary";
      link.href = `/ui/matches/${item.existing_match_id}`;
      link.textContent = "Открыть матч";
      action.append(link);
    } else if (item.disposition === "duplicate") {
      message.textContent = "Эта демка уже находится в очереди";
      status.className = "status partial";
      status.textContent = "Уже в обработке";
      progress.textContent = "100%";
      if (item.job_id) {
        const link = document.createElement("a");
        link.className = "button secondary";
        link.href = `/ui/import-jobs/${item.job_id}`;
        link.textContent = "Открыть загрузку";
        action.append(link);
      }
    } else {
      message.textContent = item.message;
      status.className = "status unavailable";
      status.textContent = "Не принята";
      progress.textContent = "100%";
    }
    article.append(identity, status, progress, action);
    return article;
  }

  function render(view) {
    document.getElementById("batchProgress").textContent = view.progress_percent;
    document.getElementById("batchProgressBar").style.width = `${view.progress_percent}%`;
    document.getElementById("batchTotal").textContent = view.total_count;
    document.getElementById("batchComplete").textContent = view.complete_count;
    document.getElementById("batchDuplicate").textContent = view.duplicate_count;
    document.getElementById("batchFailed").textContent = view.failed_count + view.rejected_count;
    document.getElementById("batchFileList").replaceChildren(...view.items.map(renderItem));
    const status = document.getElementById("batchStatus");
    status.textContent = view.terminal ? "Обработка завершена" : "Обрабатывается";
    status.className = `status ${view.terminal && !view.failed_count && !view.rejected_count ? "available" : "partial"}`;
    document.getElementById("batchContact").textContent = view.terminal ? "Все файлы проверены" : "Состояние обновляется автоматически";
  }

  async function poll() {
    try {
      const view = await api.json(`/api/import-batches/${config.batch_id}`);
      render(view);
      if (!view.terminal) window.setTimeout(poll, 1000);
    } catch (_error) {
      document.getElementById("batchContact").textContent = "Нет связи с сервером — пробуем снова";
      window.setTimeout(poll, 2500);
    }
  }
  window.setTimeout(poll, 500);
})();
