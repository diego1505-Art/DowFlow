(() => {
  const screen = document.getElementById("dependencyLoading");
  if (!screen) return;

  const stage = document.getElementById("dependencyStage");
  const track = document.getElementById("dependencyTrack");
  const fill = document.getElementById("dependencyFill");
  const percent = document.getElementById("dependencyPercent");
  const error = document.getElementById("dependencyError");
  const retry = document.getElementById("dependencyRetry");
  let polling = false;

  const render = (state) => {
    const value = Math.max(0, Math.min(100, Number(state.percent) || 0));
    stage.textContent = state.stage || "Preparing media tools";
    fill.style.width = `${value}%`;
    percent.textContent = `${value}%`;
    track.setAttribute("aria-valuenow", String(value));

    if (state.status === "ready") {
      screen.hidden = true;
      void fetch("/check-ffmpeg", { cache: "no-store" })
        .then((response) => response.json())
        .then((result) => {
          const dot = document.getElementById("ffmpegDot");
          const label = document.getElementById("ffmpegText");
          if (!dot || !label) return;
          dot.classList.toggle("online", Boolean(result.has_ffmpeg));
          label.textContent = result.has_ffmpeg ? "FFmpeg: OK" : "FFmpeg: not installed";
        })
        .catch(() => {});
      return true;
    }
    if (state.status === "failed") {
      error.textContent = state.error || "Dependency setup failed.";
      error.hidden = false;
      retry.hidden = false;
      retry.disabled = false;
      return true;
    }
    error.hidden = true;
    retry.hidden = true;
    return false;
  };

  const poll = async () => {
    if (polling) return;
    polling = true;
    retry.disabled = true;
    error.hidden = true;
    retry.hidden = true;
    try {
      while (true) {
        const response = await fetch("/api/dependencies/progress", { cache: "no-store" });
        const state = await response.json();
        if (!response.ok) throw new Error(state.error || "Unable to read setup progress.");
        if (render(state)) break;
        await new Promise((resolve) => window.setTimeout(resolve, 450));
      }
    } catch (exception) {
      error.textContent = exception.message || "Unable to read setup progress.";
      error.hidden = false;
      retry.hidden = false;
      retry.disabled = false;
    } finally {
      polling = false;
    }
  };

  retry.addEventListener("click", async () => {
    retry.disabled = true;
    try {
      const response = await fetch("/api/dependencies/retry", { method: "POST" });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || "Unable to retry setup.");
      await poll();
    } catch (exception) {
      error.textContent = exception.message || "Unable to retry setup.";
      error.hidden = false;
      retry.disabled = false;
    }
  });

  void poll();
})();
