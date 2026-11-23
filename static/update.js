/*
 * Installed DowFlow editions can install the newest Setup from the GitHub
 * release without leaving the app: the backend downloads it and starts it,
 * Inno Setup replaces the files and restarts DowFlow.
 */
(function () {
  "use strict";

  var CHECK_URL = "/api/update/check";
  var INSTALL_URL = "/api/update/install";
  var DISMISS_KEY = "dowflow.update.dismissed";

  function dismissed(version) {
    try {
      return window.localStorage.getItem(DISMISS_KEY) === version;
    } catch (error) {
      return false;
    }
  }

  function remember(version) {
    try {
      window.localStorage.setItem(DISMISS_KEY, version);
    } catch (error) {
      /* private storage: the notice simply shows again next launch */
    }
  }

  function buildPanel(update) {
    var panel = document.createElement("aside");
    panel.className = "dowflow-update";
    panel.setAttribute("role", "status");

    var title = document.createElement("p");
    title.className = "dowflow-update__title";
    title.textContent = update.version
      ? "Update available · " + update.version
      : "Update available";
    panel.appendChild(title);

    var note = document.createElement("p");
    note.className = "dowflow-update__note";
    note.textContent =
      "DowFlow will download " + (update.name || "the newest Setup") +
      ", close and restart.";
    panel.appendChild(note);

    var actions = document.createElement("div");
    actions.className = "dowflow-update__actions";

    var install = document.createElement("button");
    install.type = "button";
    install.className = "dowflow-update__install";
    install.textContent = "Install";
    actions.appendChild(install);

    var later = document.createElement("button");
    later.type = "button";
    later.className = "dowflow-update__later";
    later.textContent = "Later";
    actions.appendChild(later);
    panel.appendChild(actions);

    later.addEventListener("click", function () {
      remember(update.version || "unknown");
      panel.remove();
    });

    install.addEventListener("click", async function () {
      install.disabled = true;
      later.disabled = true;
      install.textContent = "Downloading the setup…";
      note.textContent = "Keep DowFlow open until the download finishes.";
      try {
        var response = await fetch(INSTALL_URL, { method: "POST" });
        var result = await response.json();
        if (!result || !result.success) {
          throw new Error((result && result.error) || "The update failed.");
        }
        install.textContent = "Installing…";
        note.textContent =
          "DowFlow is closing; the Setup restarts it when it is done.";
        actions.remove();
      } catch (error) {
        install.disabled = false;
        later.disabled = false;
        install.textContent = "Retry";
        note.textContent =
          error instanceof Error ? error.message : "The update failed.";
      }
    });

    return panel;
  }

  async function check() {
    try {
      var response = await fetch(CHECK_URL, { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      var update = await response.json();
      if (!update || !update.available) return;
      if (dismissed(update.version || "unknown")) return;
      document.body.appendChild(buildPanel(update));
    } catch (error) {
      /* offline or GitHub unreachable: stay silent, the app still works */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", check);
  } else {
    check();
  }
})();
