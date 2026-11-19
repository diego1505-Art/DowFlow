const RUNTIME = `
let effect = null;
let canvas = null;
let info = null;
let state = { positionMs: 0, playing: false, energy: 0 };
let running = false;
let last = 0;
let elapsed = 0;

const fail = (error) => {
  running = false;
  self.postMessage({ type: "error", message: String(error && error.message ? error.message : error) });
};

let pending = 0;

const tick = (now) => {
  if (!running) return;
  pending += last ? (now - last) / 1000 : 0;
  last = now;
  const fps = Math.min(60, Math.max(1, Number(effect.fps) || 60));
  if (pending > 0 && pending < 1 / fps - 0.004) {
    self.requestAnimationFrame(tick);
    return;
  }
  const dt = Math.min(pending, 0.1);
  pending = 0;
  elapsed += dt;
  try {
    effect.frame({ ...state, time: elapsed, dt });
  } catch (error) {
    fail(error);
    return;
  }
  self.requestAnimationFrame(tick);
};

const start = () => {
  if (running || !effect) return;
  running = true;
  last = 0;
  pending = 0;
  self.requestAnimationFrame(tick);
};

self.ambient = (setup) => {
  self.ambientSetup = setup;
};

self.onmessage = (event) => {
  const message = event.data;
  try {
    if (message.type === "init") {
      canvas = message.canvas;
      info = message.info;
      effect = self.ambientSetup(canvas, info) || {};
      effect.frame = effect.frame || (() => {});
      self.postMessage({ type: "options", pixelated: Boolean(effect.pixelated), scale: Number(effect.scale) || 0, blur: typeof effect.blur === "number" ? effect.blur : undefined });
      start();
    } else if (message.type === "resize" && canvas) {
      canvas.width = message.width;
      canvas.height = message.height;
      if (effect && effect.resize) effect.resize(message.width, message.height);
    } else if (message.type === "state") {
      state = { ...state, ...message.state };
    } else if (message.type === "pause") {
      running = false;
    } else if (message.type === "resume") {
      start();
    }
  } catch (error) {
    fail(error);
  }
};
`;

export function buildAmbientWorkerSource(script: string): string {
  return `${RUNTIME}\n;${script}\n;if (typeof self.ambientSetup !== "function") { self.postMessage({ type: "error", message: "ambient() was not called" }); }`;
}
