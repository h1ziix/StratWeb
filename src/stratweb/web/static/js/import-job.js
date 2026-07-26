"use strict";

(() => {
  const config = JSON.parse(document.getElementById("jobConfig").textContent);
  const api = new window.StratWebApi();
  const result = document.getElementById("jobResult");

  function renderResult(job) {
    if (job.stage === "complete" && job.match_id) {
      const link = document.createElement("a");
      link.className = "button";
      link.href = `/ui/matches/${job.match_id}`;
      link.textContent = "Open match";
      result.replaceChildren(link);
      return;
    }
    if (job.stage === "failed" && job.recoverable) {
      const form = document.createElement("form");
      form.method = "post";
      form.action = `/api/import-jobs/${job.job_id}/retry`;
      const button = document.createElement("button");
      button.type = "submit";
      button.textContent = "Retry import";
      form.append(button);
      result.replaceChildren(form);
      return;
    }
    result.replaceChildren();
  }

  function renderJob(job) {
    const stage = document.getElementById("jobStage");
    stage.textContent = job.stage;
    stage.className = `status ${
      job.stage === "failed" ? "unavailable" : job.stage === "complete" ? "available" : "partial"
    }`;
    document.getElementById("jobMessage").textContent = job.message;
    document.getElementById("jobError").textContent = job.error_code || "—";
    document.getElementById("jobProgress").textContent = job.progress_percent;
    document.getElementById("jobProgressBar").style.width = `${job.progress_percent}%`;
    document.getElementById("jobAttempt").textContent = job.attempt_count;
    const updated = document.getElementById("jobUpdated");
    updated.dateTime = job.updated_at;
    updated.textContent = job.updated_at;
    document.getElementById("jobContact").textContent = "just now";
    renderResult(job);
  }

  async function poll() {
    try {
      const job = await api.json(`/api/import-jobs/${config.job_id}`);
      renderJob(job);
      if (job.stage === "complete" || job.stage === "failed") return;
      window.setTimeout(poll, 800);
    } catch (_error) {
      document.getElementById("jobContact").textContent = "disconnected";
      document.getElementById("jobMessage").textContent =
        "The server is temporarily unavailable. Waiting and trying again…";
      window.setTimeout(poll, 2000);
    }
  }

  window.setTimeout(poll, 400);
})();
