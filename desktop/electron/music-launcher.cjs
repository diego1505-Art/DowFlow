const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const COMMON_ENV = new Set([
  "ALL_PROXY",
  "HTTP_PROXY",
  "HTTPS_PROXY",
  "NO_PROXY",
  "LANG",
  "LC_ALL",
]);
const WINDOWS_ENV = new Set([
  "PATH",
  "SYSTEMROOT",
  "WINDIR",
  "COMSPEC",
  "PATHEXT",
  "TEMP",
  "TMP",
  "USERPROFILE",
  "APPDATA",
  "LOCALAPPDATA",
  "HOMEDRIVE",
  "HOMEPATH",
]);
const POSIX_ENV = new Set([
  "PATH",
  "HOME",
  "TMPDIR",
  "XDG_CONFIG_HOME",
  "XDG_CACHE_HOME",
  "XDG_DATA_HOME",
  "DISPLAY",
  "WAYLAND_DISPLAY",
  "DBUS_SESSION_BUS_ADDRESS",
]);

function childEnvironment(source, platform) {
  const allowed = platform === "win32" ? WINDOWS_ENV : POSIX_ENV;
  const result = {};
  for (const [key, value] of Object.entries(source || {})) {
    const normalized = key.toUpperCase();
    if (allowed.has(normalized) || COMMON_ENV.has(normalized)) {
      result[key] = value;
    }
  }
  return result;
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function createMusicLauncher({
  app,
  projectRoot,
  resourcesPath,
  electronPath = process.execPath,
  platform = process.platform,
  spawnProcess = spawn,
  existsSync = fs.existsSync,
  env = process.env,
} = {}) {
  const children = new Set();
  const filteredEnv = childEnvironment(env, platform);

  function launchSpec() {
    if (!app) throw new Error("Electron application context is unavailable.");

    if (app.isPackaged) {
      if (platform !== "win32") {
        throw new Error("The bundled DowFlow Music launcher is currently available for Windows builds only.");
      }
      if (!resourcesPath) throw new Error("Electron resources path is unavailable.");
      const executable = path.join(resourcesPath, "liner", "dowflow-music.exe");
      if (!existsSync(executable)) {
        throw new Error("The bundled DowFlow Music application is missing. Rebuild the Windows package.");
      }
      return { command: executable, args: [], cwd: path.dirname(executable) };
    }

    if (!projectRoot) throw new Error("DowFlow project path is unavailable.");
    const appRoot = path.join(projectRoot, "desktop", "liner");
    const requiredFiles = [
      path.join(appRoot, "dist-electron", "main.js"),
      path.join(appRoot, "dist", "index.html"),
      path.join(appRoot, "node_modules"),
    ];
    if (!requiredFiles.every(existsSync)) {
      throw new Error(
        "DowFlow Music is not prepared. Run `pnpm --dir desktop/liner install --frozen-lockfile` and `pnpm --dir desktop/liner check` first.",
      );
    }
    return { command: electronPath, args: [appRoot], cwd: appRoot };
  }

  function open() {
    let spec;
    try {
      spec = launchSpec();
    } catch (error) {
      return Promise.resolve({ success: false, fallback: true, error: errorMessage(error) });
    }

    return new Promise((resolve) => {
      let child;
      let settled = false;
      const settle = (result) => {
        if (settled) return;
        settled = true;
        resolve(result);
      };
      try {
        child = spawnProcess(spec.command, spec.args, {
          cwd: spec.cwd,
          windowsHide: true,
          stdio: "ignore",
          env: filteredEnv,
        });
      } catch (error) {
        settle({ success: false, fallback: true, error: errorMessage(error) });
        return;
      }

      if (!child || typeof child.once !== "function") {
        settle({ success: false, fallback: true, error: "Could not start DowFlow Music." });
        return;
      }
      children.add(child);
      const removeChild = () => children.delete(child);
      child.once("spawn", () => settle({ success: true }));
      child.once("error", (error) => {
        removeChild();
        settle({ success: false, fallback: true, error: errorMessage(error) });
      });
      child.once("exit", removeChild);
    });
  }

  function closeAll() {
    for (const child of children) {
      if (child.exitCode !== null || child.killed || !child.pid) continue;
      if (platform === "win32") {
        try {
          const killer = spawnProcess(
            "taskkill.exe",
            ["/PID", String(child.pid), "/T", "/F"],
            { windowsHide: true, stdio: "ignore", env: filteredEnv },
          );
          killer?.once?.("error", () => {
            try {
              child.kill();
            } catch {
              // The operating system may already be closing the process.
            }
          });
        } catch {
          try {
            child.kill();
          } catch {
            // The operating system may already be closing the process.
          }
        }
      } else {
        try {
          child.kill();
        } catch {
          // The operating system may already be closing the process.
        }
      }
    }
    children.clear();
  }

  return Object.freeze({ open, closeAll });
}

module.exports = { createMusicLauncher };
