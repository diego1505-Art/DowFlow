document.querySelectorAll("[data-export-tools]").forEach((tools) => {
  const button = tools.querySelector("[data-export-scope]");
  const status = tools.querySelector("[data-export-status]");
  const progress = tools.querySelector("[data-export-progress]");
  const progressTrack = tools.querySelector("[data-export-track]");
  const progressFill = tools.querySelector("[data-export-fill]");
  const progressPercent = tools.querySelector("[data-export-percent]");
  const progressStage = tools.querySelector("[data-export-stage]");
  const progressEta = tools.querySelector("[data-export-eta]");
  if (!button || !status) return;

  const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  let latestEta = null;
  let latestEtaAt = 0;

  const formatEta = (seconds) => {
    if (seconds === null || !Number.isFinite(seconds)) return "Estimating remaining time…";
    if (seconds <= 0) return "Almost done…";
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    if (minutes >= 60) return `~${Math.floor(minutes / 60)}h ${minutes % 60}m remaining`;
    if (minutes > 0) return `~${minutes}m ${remainder}s remaining`;
    return `~${remainder}s remaining`;
  };

  const renderProgress = (job) => {
    if (!progress) return;
    progress.hidden = false;
    const percent = Math.max(0, Math.min(100, Number(job.progress) || 0));
    if (progressPercent) progressPercent.textContent = `${percent}%`;
    if (progressFill) progressFill.style.width = `${percent}%`;
    if (progressTrack) progressTrack.setAttribute("aria-valuenow", String(percent));
    if (progressStage) progressStage.textContent = job.stage || "Building executable";

    if (job.status === "success") {
      latestEta = null;
      if (progressEta) progressEta.textContent = "Completed";
      return;
    }
    if (job.status === "failed") {
      latestEta = null;
      if (progressEta) progressEta.textContent = "Failed";
      return;
    }

    if (job.eta_seconds === null || job.eta_seconds === undefined) {
      latestEta = null;
    } else {
      latestEta = Number(job.eta_seconds);
      latestEtaAt = Number(job.eta_updated_at) || Date.now() / 1000;
    }
    const elapsedSinceUpdate = Math.max(0, Date.now() / 1000 - latestEtaAt);
    const remaining = latestEta === null ? null : Math.max(0, Math.ceil(latestEta - elapsedSinceUpdate));
    if (progressEta) progressEta.textContent = formatEta(remaining);
  };

  const refreshEta = () => {
    if (progress?.hidden || !progressEta || latestEta === null) return;
    const elapsedSinceUpdate = Math.max(0, Date.now() / 1000 - latestEtaAt);
    progressEta.textContent = formatEta(Math.max(0, Math.ceil(latestEta - elapsedSinceUpdate)));
  };

  window.setInterval(refreshEta, 1000);

  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "Choose an EXE name in the save dialog...";
    if (progress) progress.hidden = true;
    try {
      const response = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: button.dataset.exportScope }),
      });
      const payload = await response.json();
      if (payload.cancelled) {
        status.textContent = "Export cancelled.";
        return;
      }
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "Unable to start export.");
      }

      status.textContent = "Building " + payload.name + ".exe...";
      while (true) {
        await delay(1200);
        const resultResponse = await fetch(`/api/export/${encodeURIComponent(payload.job_id)}`);
        const result = await resultResponse.json();
        if (!resultResponse.ok || !result.success) {
          throw new Error(result.error || "Unable to read export status.");
        }
        if (result.job.status === "success") {
          renderProgress(result.job);
          status.textContent = "Created: " + result.job.path;
          break;
        }
        if (result.job.status === "failed") {
          renderProgress(result.job);
          throw new Error(result.job.error || "PyInstaller failed.");
        }
        status.textContent = "Building " + payload.name + ".exe...";
        renderProgress(result.job);
      }
    } catch (error) {
      status.textContent = error.message || "Export failed.";
    } finally {
      button.disabled = false;
    }
  });
});
