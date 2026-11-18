const { BrowserWindow, ipcMain } = require("electron");

const BOTGUARD_PAGE = "https://www.youtube.com/robots.txt";
const START_TIMEOUT_MS = 20_000;
const REQUEST_TIMEOUT_MS = 20_000;
const IDLE_SHUTDOWN_MS = 5 * 60_000;
const MAX_CACHE_ENTRIES = 256;
const IDENTIFIER = /^[\w=-]{1,128}$/;
const INTERPRETER_HOSTS = new Set(["www.google.com", "www.gstatic.com"]);

function remember(map, key, value) {
  map.delete(key);
  map.set(key, value);
  while (map.size > MAX_CACHE_ENTRIES) map.delete(map.keys().next().value);
}

class PoTokenService {
  constructor(preloadPath) {
    this.preloadPath = preloadPath;
    this.window = null;
    this.ready = null;
    this.markReady = null;
    this.nextId = 1;
    this.pending = new Map();
    this.mints = new Map();
    this.startTimer = null;
    this.idleTimer = null;

    ipcMain.on("dowflow-potoken-ready", (event) => {
      if (event.sender === this.window?.webContents) this.markReady?.();
    });
    ipcMain.on("dowflow-potoken-result", (event, result) => {
      this.settle(event, result);
    });
    ipcMain.handle("dowflow-potoken-interpreter", async (event, rawUrl) => {
      if (event.sender !== this.window?.webContents || typeof rawUrl !== "string") {
        throw new Error("Not allowed");
      }
      let target;
      try {
        target = new URL(rawUrl);
      } catch {
        throw new Error("Invalid interpreter URL");
      }
      if (target.protocol !== "https:" || !INTERPRETER_HOSTS.has(target.hostname)) {
        throw new Error("Interpreter host not allowed");
      }
      const response = await fetch(target, { signal: AbortSignal.timeout(START_TIMEOUT_MS) });
      if (!response.ok) throw new Error(`Interpreter request returned ${response.status}`);
      return response.text();
    });
  }

  start() {
    if (this.window && !this.window.isDestroyed() && this.ready) return this.ready;
    const win = new BrowserWindow({
      show: false,
      skipTaskbar: true,
      width: 320,
      height: 240,
      webPreferences: {
        preload: this.preloadPath,
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        backgroundThrottling: false,
      },
    });
    win.webContents.setAudioMuted(true);
    win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    this.window = win;

    let rejectReady;
    this.ready = new Promise((resolve, reject) => {
      rejectReady = reject;
      this.startTimer = setTimeout(() => {
        this.startTimer = null;
        reject(new Error("YouTube PoToken worker did not become ready"));
      }, START_TIMEOUT_MS);
      this.markReady = () => {
        if (this.startTimer) clearTimeout(this.startTimer);
        this.startTimer = null;
        this.markReady = null;
        resolve();
      };
      win.webContents.once("did-fail-load", (_event, _code, description) => {
        if (this.startTimer) clearTimeout(this.startTimer);
        this.startTimer = null;
        reject(new Error(`YouTube PoToken worker failed to load: ${description}`));
      });
    });
    const ready = this.ready;
    ready.catch(() => this.destroy());
    win.on("closed", () => this.reset(win));
    void win.loadURL(BOTGUARD_PAGE).catch((error) => rejectReady(error));
    return ready;
  }

  reset(win) {
    if (this.window !== win) return;
    if (this.startTimer) clearTimeout(this.startTimer);
    this.startTimer = null;
    this.window = null;
    this.ready = null;
    this.markReady = null;
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(new Error("YouTube PoToken worker closed"));
      this.pending.delete(id);
    }
  }

  settle(event, result) {
    if (event.sender !== this.window?.webContents || !result || !Number.isSafeInteger(result.id)) return;
    const entry = this.pending.get(result.id);
    if (!entry) return;
    this.pending.delete(result.id);
    clearTimeout(entry.timer);
    this.scheduleIdleShutdown();
    if (typeof result.error === "string") entry.reject(new Error(result.error || "PoToken worker failed"));
    else entry.resolve(result.value);
  }

  async request(identifier) {
    await this.start();
    const win = this.window;
    if (!win || win.isDestroyed()) throw new Error("YouTube PoToken worker is unavailable");
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        this.scheduleIdleShutdown();
        reject(new Error("YouTube PoToken request timed out"));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      win.webContents.send("dowflow-potoken-request", { id, payload: { identifier } });
    });
  }

  async mint(identifier) {
    if (typeof identifier !== "string" || !IDENTIFIER.test(identifier)) {
      throw new Error("Invalid YouTube video identifier");
    }
    const cached = this.mints.get(identifier);
    if (cached && Date.now() < cached.expiresAt) return cached.value;

    this.cancelIdleShutdown();
    const result = await this.request(identifier);
    if (!result || typeof result.token !== "string" || !result.token) {
      throw new Error("YouTube PoToken minting failed");
    }
    const fallbackExpiry = Date.now() + 6 * 60 * 60 * 1000;
    const expiresAt = Number.isFinite(result.expiresAt) ? result.expiresAt : fallbackExpiry;
    remember(this.mints, identifier, { value: result.token, expiresAt });
    this.scheduleIdleShutdown();
    return result.token;
  }

  cancelIdleShutdown() {
    if (!this.idleTimer) return;
    clearTimeout(this.idleTimer);
    this.idleTimer = null;
  }

  scheduleIdleShutdown() {
    this.cancelIdleShutdown();
    if (!this.window || this.window.isDestroyed()) return;
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null;
      if (this.pending.size > 0) return this.scheduleIdleShutdown();
      this.destroy();
    }, IDLE_SHUTDOWN_MS);
  }

  destroy() {
    this.cancelIdleShutdown();
    const win = this.window;
    if (win && !win.isDestroyed()) win.destroy();
    if (win) this.reset(win);
  }
}

module.exports = { PoTokenService };
