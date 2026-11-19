const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const path = require("node:path");
const { test } = require("node:test");
const { createMusicLauncher } = require("./music-launcher.cjs");

function fakeChild(pid = 1234) {
  const child = new EventEmitter();
  child.pid = pid;
  child.exitCode = null;
  child.killed = false;
  child.killCalled = false;
  child.kill = () => {
    child.killCalled = true;
    child.killed = true;
    child.exitCode = 0;
    child.emit("exit", 0, null);
    return true;
  };
  return child;
}

function makeSpawner() {
  const calls = [];
  const children = [];
  const spawnProcess = (command, args, options) => {
    calls.push({ command, args, options });
    const child = fakeChild(2000 + children.length);
    children.push(child);
    queueMicrotask(() => child.emit("spawn"));
    return child;
  };
  return { calls, children, spawnProcess };
}

const projectRoot = path.resolve("/workspace/DowFlow");
const linerRoot = path.join(projectRoot, "desktop", "liner");
const developmentFiles = new Set([
  path.join(linerRoot, "dist-electron", "main.js"),
  path.join(linerRoot, "dist", "index.html"),
  path.join(linerRoot, "node_modules"),
]);

test("development opens the imported Liner app with a minimal environment", async () => {
  const { calls, children, spawnProcess } = makeSpawner();
  const launcher = createMusicLauncher({
    app: { isPackaged: false },
    projectRoot,
    electronPath: "/electron/dowflow",
    platform: "linux",
    existsSync: (candidate) => developmentFiles.has(candidate),
    env: {
      PATH: "/usr/bin",
      HOME: "/home/test",
      DOWFLOW_DESKTOP_TOKEN: "must-not-be-forwarded",
      GITHUB_TOKEN: "must-not-be-forwarded",
    },
    spawnProcess,
  });

  assert.deepEqual(await launcher.open(), { success: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, "/electron/dowflow");
  assert.deepEqual(calls[0].args, [linerRoot]);
  assert.equal(calls[0].options.cwd, linerRoot);
  assert.deepEqual(calls[0].options.env, { PATH: "/usr/bin", HOME: "/home/test" });

  launcher.closeAll();
  assert.equal(children[0].killCalled, true);
});

test("packaged Windows launch uses the bundled DowFlow Music executable", async () => {
  const resourcesPath = path.resolve("/package/resources");
  const executable = path.join(resourcesPath, "liner", "dowflow-music.exe");
  const { calls, spawnProcess } = makeSpawner();
  const launcher = createMusicLauncher({
    app: { isPackaged: true },
    projectRoot,
    resourcesPath,
    platform: "win32",
    existsSync: (candidate) => candidate === executable,
    env: { Path: "C:\\Windows\\System32", DOWFLOW_DESKTOP_TOKEN: "hidden" },
    spawnProcess,
  });

  assert.deepEqual(await launcher.open(), { success: true });
  assert.equal(calls[0].command, executable);
  assert.deepEqual(calls[0].args, []);
  assert.equal(calls[0].options.cwd, path.dirname(executable));
  assert.equal(calls[0].options.env.Path, "C:\\Windows\\System32");
  assert.equal(calls[0].options.env.DOWFLOW_DESKTOP_TOKEN, undefined);
});

test("an unprepared development checkout returns a safe fallback without spawning", async () => {
  const { calls, spawnProcess } = makeSpawner();
  const launcher = createMusicLauncher({
    app: { isPackaged: false },
    projectRoot,
    platform: "linux",
    existsSync: () => false,
    spawnProcess,
  });

  const result = await launcher.open();
  assert.equal(result.success, false);
  assert.equal(result.fallback, true);
  assert.match(result.error, /not prepared/i);
  assert.equal(calls.length, 0);
});

test("a missing packaged Windows app returns a fallback instead of spawning", async () => {
  const { calls, spawnProcess } = makeSpawner();
  const launcher = createMusicLauncher({
    app: { isPackaged: true },
    projectRoot,
    resourcesPath: path.resolve("/package/resources"),
    platform: "win32",
    existsSync: () => false,
    spawnProcess,
  });

  const result = await launcher.open();
  assert.equal(result.success, false);
  assert.equal(result.fallback, true);
  assert.match(result.error, /application is missing/i);
  assert.equal(calls.length, 0);
});
