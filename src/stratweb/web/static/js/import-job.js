"use strict";

(() => {
  const config = JSON.parse(document.getElementById("jobConfig").textContent);
  const api = new window.StratWebApi();
  const result = document.getElementById("jobResult");
  const stageLabels = {
    queued: "в очереди",
    parsing: "разбор демки",
    canonical: "исходные данные",
    analytics: "аналитика",
    temporal: "состояния раунда",
    spatial: "позиции",
    economy: "экономика",
    zones: "зоны",
    features: "факты",
    complete: "готово",
    failed: "ошибка",
  };
  const messageLabels = {
    "Waiting for the local import worker": "Ожидание локальной обработки",
    "Assigning version-pinned map zones": "Определение зон карты",
    "Materializing deterministic per-round facts": "Расчёт фактов по раундам",
    "Match is ready": "Матч готов",
  };

  function renderResult(job) {
    if (job.stage === "complete" && job.match_id) {
      const link = document.createElement("a");
      link.className = "button";
      link.href = `/ui/matches/${job.match_id}`;
      link.textContent = "Открыть матч";
      result.replaceChildren(link);
      return;
    }
    if (job.stage === "failed" && job.recoverable) {
      const form = document.createElement("form");
      form.method = "post";
      form.action = `/api/import-jobs/${job.job_id}/retry`;
      const button = document.createElement("button");
      button.type = "submit";
      button.textContent = "Повторить импорт";
      form.append(button);
      result.replaceChildren(form);
      return;
    }
    result.replaceChildren();
  }

  function renderJob(job) {
    const stage = document.getElementById("jobStage");
    stage.textContent = stageLabels[job.stage] || job.stage;
    stage.className = `status ${
      job.stage === "failed" ? "unavailable" : job.stage === "complete" ? "available" : "partial"
    }`;
    document.getElementById("jobMessage").textContent = messageLabels[job.message] || job.message;
    document.getElementById("jobError").textContent = job.error_code || "—";
    document.getElementById("jobProgress").textContent = job.progress_percent;
    document.getElementById("jobProgressBar").style.width = `${job.progress_percent}%`;
    document.getElementById("jobAttempt").textContent = job.attempt_count;
    const updated = document.getElementById("jobUpdated");
    updated.dateTime = job.updated_at;
    updated.textContent = job.updated_at;
    document.getElementById("jobContact").textContent = "только что";
    renderResult(job);
  }

  async function poll() {
    try {
      const job = await api.json(`/api/import-jobs/${config.job_id}`);
      renderJob(job);
      if (job.stage === "complete" || job.stage === "failed") return;
      window.setTimeout(poll, 800);
    } catch (_error) {
      document.getElementById("jobContact").textContent = "нет связи";
      document.getElementById("jobMessage").textContent =
        "Сервер временно недоступен. Ждём и пробуем снова…";
      window.setTimeout(poll, 2000);
    }
  }

  window.setTimeout(poll, 400);
})();
