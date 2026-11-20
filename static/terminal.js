/* DowFlow in-app terminal: streams /api/logs/stream on every page. */
(function () {
    "use strict";

    var MAX_LINES = 1500;
    var STORAGE_KEY = "dowflow.terminal.open";
    var script = document.currentScript;
    var scriptUrl = script && script.src ? script.src : "/static/terminal.js";

    function make(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function injectStyles() {
        if (document.getElementById("df-terminal-styles")) return;
        var link = document.createElement("link");
        link.id = "df-terminal-styles";
        link.rel = "stylesheet";
        try {
            link.href = new URL("terminal.css", scriptUrl).href;
        } catch (error) {
            link.href = "/static/terminal.css";
        }
        document.head.appendChild(link);
    }

    function readPreference() {
        try {
            return window.localStorage.getItem(STORAGE_KEY);
        } catch (error) {
            return null;
        }
    }

    function writePreference(value) {
        try {
            window.localStorage.setItem(STORAGE_KEY, value);
        } catch (error) {
            /* storage disabled: the panel still works for this page */
        }
    }

    function build() {
        var toggle = make("button", "df-terminal-toggle", "Terminal");
        toggle.type = "button";
        toggle.setAttribute("aria-controls", "df-terminal");
        toggle.setAttribute("aria-expanded", "false");

        var panel = make("section", "df-terminal");
        panel.id = "df-terminal";
        panel.hidden = true;

        var dot = make("span", "df-terminal-dot");
        var title = make("strong", "df-terminal-title", "DowFlow terminal");
        var status = make("span", "df-terminal-status", "connecting…");
        status.setAttribute("role", "status");

        var follow = make("button", "df-terminal-button", "Follow");
        follow.type = "button";
        follow.dataset.action = "follow";
        follow.setAttribute("aria-pressed", "true");

        var clear = make("button", "df-terminal-button", "Clear");
        clear.type = "button";
        clear.dataset.action = "clear";

        var hide = make("button", "df-terminal-button", "Hide");
        hide.type = "button";
        hide.dataset.action = "hide";

        var actions = make("div", "df-terminal-actions");
        actions.append(follow, clear, hide);

        var header = make("header", "df-terminal-header");
        header.append(dot, title, status, actions);

        var body = make("div", "df-terminal-body");
        body.id = "df-terminal-body";
        body.tabIndex = 0;
        body.setAttribute("role", "log");
        body.setAttribute("aria-live", "polite");
        body.setAttribute("aria-label", "DowFlow logs");

        panel.append(header, body);
        document.body.append(toggle, panel);
        return {
            toggle: toggle,
            panel: panel,
            body: body,
            status: status,
            dot: dot,
            follow: follow
        };
    }

    injectStyles();
    var ui = build();

    var stream = null;
    var followEnabled = true;
    var retryTimer = null;
    var retryDelay = 1000;

    function setStatus(text, state) {
        ui.status.textContent = text;
        ui.dot.dataset.state = state || "connecting";
    }

    function appendLine(payload) {
        var level = String(payload.level || "INFO").toLowerCase();
        var message = payload.message || "";
        var line = make("div", "df-line");
        line.dataset.level = level;
        if (message.indexOf("[download]") !== -1) {
            line.classList.add("df-line-download");
        }
        line.append(
            make("span", "df-time", payload.time || ""),
            make("span", "df-level", payload.level || ""),
            make("span", "df-source", payload.source || ""),
            make("span", "df-message", message)
        );
        ui.body.appendChild(line);
        while (ui.body.childElementCount > MAX_LINES) {
            ui.body.firstElementChild.remove();
        }
        if (followEnabled) {
            ui.body.scrollTop = ui.body.scrollHeight;
        }
    }

    function connect() {
        if (stream || typeof window.EventSource === "undefined") {
            if (typeof window.EventSource === "undefined") {
                setStatus("streaming unsupported", "error");
            }
            return;
        }
        setStatus("connecting…", "connecting");
        stream = new window.EventSource("/api/logs/stream?tail=300");
        stream.onopen = function () {
            retryDelay = 1000;
            setStatus("live", "live");
        };
        stream.onmessage = function (event) {
            try {
                appendLine(JSON.parse(event.data));
            } catch (error) {
                /* ignore malformed frames */
            }
        };
        stream.onerror = function () {
            setStatus("reconnecting…", "error");
            if (stream) {
                stream.close();
                stream = null;
            }
            window.clearTimeout(retryTimer);
            retryTimer = window.setTimeout(connect, retryDelay);
            retryDelay = Math.min(15000, retryDelay * 2);
        };
    }

    function disconnect() {
        window.clearTimeout(retryTimer);
        if (stream) {
            stream.close();
            stream = null;
        }
    }

    function openPanel() {
        ui.panel.hidden = false;
        ui.toggle.classList.add("is-hidden");
        ui.toggle.setAttribute("aria-expanded", "true");
        writePreference("1");
        connect();
        ui.body.scrollTop = ui.body.scrollHeight;
    }

    function closePanel() {
        ui.panel.hidden = true;
        ui.toggle.classList.remove("is-hidden");
        ui.toggle.setAttribute("aria-expanded", "false");
        writePreference("0");
        disconnect();
    }

    ui.toggle.addEventListener("click", openPanel);

    ui.panel.addEventListener("click", function (event) {
        var button = event.target.closest("[data-action]");
        if (!button) return;
        var action = button.dataset.action;
        if (action === "hide") {
            closePanel();
        } else if (action === "clear") {
            ui.body.replaceChildren();
        } else if (action === "follow") {
            followEnabled = !followEnabled;
            button.setAttribute("aria-pressed", followEnabled ? "true" : "false");
            if (followEnabled) ui.body.scrollTop = ui.body.scrollHeight;
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.ctrlKey && !event.shiftKey && (event.key === "`" || event.key === "²")) {
            event.preventDefault();
            if (ui.panel.hidden) openPanel();
            else closePanel();
        }
    });

    if (readPreference() !== "0") {
        openPanel();
    }
})();
