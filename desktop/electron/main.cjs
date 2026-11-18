const { app, BrowserWindow, dialog, ipcMain, session } = require("electron");
const { spawn } = require("node:child_process");
const { createServer } = require("node:net");
const { randomBytes } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { PoTokenService } = require("./youtube/potoken-service.cjs");

const APP_NAME = "DowFlow";
const WINDOWS_APP_ID = "DowFlow.DowFlow";
app.setName(APP_NAME);
if (process.platform === "win32") app.setAppUserModelId(WINDOWS_APP_ID);

const PROJECT_ROOT = path.resolve(__dirname, "../..");
const STARTUP_TIMEOUT_MS = 20_000;
const HEALTH_INTERVAL_MS = 250;
const MUSIC_CORS_HEADERS = new Set([
  "access-control-allow-origin",
  "access-control-allow-headers",
  "access-control-allow-methods",
  "access-control-allow-credentials",
  "access-control-expose-headers",
  "access-control-max-age",
]);
const MUSIC_CORS_FILTER = {
  urls: [
    "https://*.youtube.com/*",
    "https://*.googlevideo.com/*",
    "https://*.ytimg.com/*",
    "https://*.ggpht.com/*",
    "https://*.googleusercontent.com/*",
  ],
};

let backendProcess = null;
let mainWindow = null;
let backendOrigin = null;
let desktopToken = null;
let backendSpawnError = null;
let quitting = false;
let poTokenService = null;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function findAvailablePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close(() => reject(new Error("Could not reserve a local port.")));
        return;
      }
      const { port } = address;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

function backendLaunchSpec() {
  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, "backend", "DowFlow.exe");
    if (!fs.existsSync(executable)) {
      throw new Error(
        "The packaged DowFlow backend is missing. Build and bundle the Python backend before packaging Electron.",
      );
    }
    return { command: executable, args: ["--server"], cwd: path.dirname(executable) };
  }

  const python =
    process.env.DOWFLOW_PYTHON ||
    (process.platform === "win32" ? "python" : "python3");
  return {
    command: python,
    args: [path.join(PROJECT_ROOT, "app.py")],
    cwd: PROJECT_ROOT,
  };
}

function startBackend(port, token) {
  const spec = backendLaunchSpec();
  const child = spawn(spec.command, spec.args, {
    cwd: spec.cwd,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      DOWFLOW_HOST: "127.0.0.1",
      DOWFLOW_PORT: String(port),
      DOWFLOW_DESKTOP_TOKEN: token,
      PYTHONUNBUFFERED: "1",
    },
  });

  child.stdout?.on("data", (chunk) => {
    process.stdout.write(`[DowFlow] ${chunk}`);
  });
  child.stderr?.on("data", (chunk) => {
    process.stderr.write(`[DowFlow] ${chunk}`);
  });
  child.once("error", (error) => {
    backendSpawnError = error;
  });
  child.once("exit", (code, signal) => {
    if (!quitting && mainWindow && !mainWindow.isDestroyed()) {
      dialog.showErrorBox(
        "DowFlow backend stopped",
        `The local Flask service exited unexpectedly (code ${code ?? "?"}, signal ${signal ?? "?"}). Check the DowFlow logs.`,
      );
      app.quit();
    }
  });
  return child;
}

function installLocalAuthHeader(origin, token) {
  const filter = { urls: [`${origin}/*`] };
  session.defaultSession.webRequest.onBeforeSendHeaders(
    filter,
    (details, callback) => {
      callback({
        requestHeaders: {
          ...details.requestHeaders,
          "X-DowFlow-Desktop": token,
        },
      });
    },
  );
}

function installMusicCors(origin) {
  session.defaultSession.webRequest.onHeadersReceived(
    MUSIC_CORS_FILTER,
    (details, callback) => {
      let requestOrigin = "";
      try {
        requestOrigin = new URL(details.initiator || details.referrer).origin;
      } catch {
        // Requests without a known renderer origin keep the upstream headers.
      }
      if (requestOrigin !== origin) {
        callback({ responseHeaders: details.responseHeaders });
        return;
      }

      const responseHeaders = {};
      for (const [name, values] of Object.entries(details.responseHeaders || {})) {
        if (!MUSIC_CORS_HEADERS.has(name.toLowerCase())) responseHeaders[name] = values;
      }
      responseHeaders["access-control-allow-origin"] = [origin];
      responseHeaders["access-control-allow-headers"] = ["*, authorization"];
      responseHeaders["access-control-allow-methods"] = ["GET, HEAD, POST, OPTIONS"];
      responseHeaders["access-control-expose-headers"] = ["*"];
      responseHeaders["access-control-max-age"] = ["600"];

      if (details.method === "OPTIONS") {
        callback({ responseHeaders, statusLine: "HTTP/1.1 200 OK" });
      } else {
        callback({ responseHeaders });
      }
    },
  );
}

async function waitForBackend(origin, token, child) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS;
  let lastError = "No health-check response yet.";

  while (Date.now() < deadline) {
    if (backendSpawnError) throw backendSpawnError;
    if (child.exitCode !== null) {
      throw new Error(`Flask exited before becoming ready (code ${child.exitCode}).`);
    }

    try {
      const response = await fetch(`${origin}/api/status`, {
        headers: { "X-DowFlow-Desktop": token },
        signal: AbortSignal.timeout(1_000),
      });
      if (response.ok) {
        const status = await response.json();
        if (status.ready === true && status.service === "DowFlow") return;
        lastError = "The health-check response did not identify a ready DowFlow service.";
      } else {
        lastError = `The health check returned HTTP ${response.status}.`;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await delay(HEALTH_INTERVAL_MS);
  }

  throw new Error(`DowFlow did not start within ${STARTUP_TIMEOUT_MS / 1000} seconds. ${lastError}`);
}

function isTrustedBackendUrl(candidate) {
  try {
    return new URL(candidate).origin === backendOrigin;
  } catch {
    return false;
  }
}

async function createMainWindow() {
  const iconPath = path.join(PROJECT_ROOT, "static", "dowflow.ico");
  const options = {
    title: APP_NAME,
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  };
  if (process.platform === "win32" && fs.existsSync(iconPath)) {
    options.icon = iconPath;
  }

  mainWindow = new BrowserWindow(options);
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isTrustedBackendUrl(url)) event.preventDefault();
  });
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  await mainWindow.loadURL(`${backendOrigin}/`);
  console.log(`[DowFlow Electron] UI loaded from ${backendOrigin}`);
}

ipcMain.handle("dowflow:runtime-info", () => ({
  shell: "electron",
  platform: process.platform,
  version: app.getVersion(),
}));

ipcMain.handle("dowflow:youtube:mint-po-token", (event, identifier) => {
  if (!mainWindow || event.sender !== mainWindow.webContents) {
    throw new Error("Untrusted DowFlow renderer");
  }
  if (!poTokenService) throw new Error("YouTube PoToken service is unavailable");
  return poTokenService.mint(identifier);
});

async function startDesktop() {
  const port = await findAvailablePort();
  backendOrigin = `http://127.0.0.1:${port}`;
  desktopToken = randomBytes(32).toString("hex");
  installLocalAuthHeader(backendOrigin, desktopToken);
  installMusicCors(backendOrigin);
  backendProcess = startBackend(port, desktopToken);
  await waitForBackend(backendOrigin, desktopToken, backendProcess);
  console.log(`[DowFlow Electron] Flask is ready at ${backendOrigin}`);
  poTokenService = new PoTokenService(path.join(__dirname, "build", "potoken-preload.cjs"));
  await createMainWindow();
}

app.whenReady().then(startDesktop).catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  dialog.showErrorBox("Could not start DowFlow", message);
  app.quit();
});

app.on("before-quit", () => {
  quitting = true;
  poTokenService?.destroy();
  if (backendProcess && backendProcess.exitCode === null) {
    backendProcess.kill();
  }
});

app.on("window-all-closed", () => {
  app.quit();
});
