import vm from "node:vm";
import { describe, expect, it } from "vitest";
import { buildAmbientWorkerSource } from "./ambientWorkerSource";

function fakeCanvas() {
  const calls = { fillRect: 0, clearRect: 0 };
  const ctx = {
    fillStyle: "",
    fillRect: () => calls.fillRect++,
    clearRect: () => calls.clearRect++,
  };
  return { width: 300, height: 200, getContext: () => ctx, calls };
}

function runWorker(script: string) {
  const posted: Record<string, unknown>[] = [];
  const frames: ((now: number) => void)[] = [];
  const self: Record<string, unknown> = {
    postMessage: (message: Record<string, unknown>) => posted.push(message),
    requestAnimationFrame: (callback: (now: number) => void) =>
      frames.push(callback),
  };
  self.self = self;
  vm.runInNewContext(buildAmbientWorkerSource(script), self);
  const send = (data: Record<string, unknown>) =>
    (self.onmessage as (event: { data: unknown }) => void)({ data });
  const step = (count: number) => {
    for (let index = 0; index < count; index++) frames.shift()?.(index * 16);
  };
  return { posted, send, step };
}

describe("ambient worker runtime", () => {
  it("runs the effect, reports its options and keeps drawing frames", () => {
    const worker = runWorker(
      "ambient((canvas) => { let n = 0; return { pixelated: true, scale: 0.3, blur: 6, frame() { canvas.frames = ++n; } }; });",
    );
    const canvas = fakeCanvas() as ReturnType<typeof fakeCanvas> & {
      frames?: number;
    };
    worker.send({ type: "init", canvas, info: { width: 300, height: 200 } });
    worker.step(5);
    expect(worker.posted[0]).toEqual({
      type: "options",
      pixelated: true,
      scale: 0.3,
      blur: 6,
    });
    expect(canvas.frames).toBe(5);
  });

  it("stops and reports when the effect throws or never calls ambient()", () => {
    const broken = runWorker(
      "ambient(() => ({ frame() { throw new Error('boom'); } }));",
    );
    broken.send({ type: "init", canvas: fakeCanvas(), info: {} });
    broken.step(3);
    expect(broken.posted).toContainEqual({ type: "error", message: "boom" });

    const silent = runWorker("const nothing = 1;");
    expect(silent.posted).toContainEqual({
      type: "error",
      message: "ambient() was not called",
    });
  });

  it("pauses and resumes the frame loop", () => {
    const worker = runWorker(
      "ambient((canvas) => ({ frame() { canvas.frames = (canvas.frames || 0) + 1; } }));",
    );
    const canvas = fakeCanvas() as ReturnType<typeof fakeCanvas> & {
      frames?: number;
    };
    worker.send({ type: "init", canvas, info: {} });
    worker.step(2);
    worker.send({ type: "pause" });
    worker.step(3);
    expect(canvas.frames).toBe(2);
  });
});
