import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const engine = vi.hoisted(() => ({
  resize: vi.fn(),
  start: vi.fn(),
  dispose: vi.fn(),
  loadImage: vi.fn(async () => {}),
}));

vi.mock("../engine/kawarpEngine", () => ({
  KawarpEngine: vi.fn(function KawarpEngine() {
    return engine;
  }),
}));
vi.mock("@/features/covers", () => ({
  getCoverElement: () => undefined,
  useCoverElement: () => undefined,
}));

import {
  KAWARP_RENDER_SCALE,
  KAWARP_RESIZE_SETTLE_MS,
  KawarpWrapper,
} from "./KawarpWrapper";

describe("KawarpWrapper", () => {
  let container: HTMLDivElement;
  let root: Root;
  let size = { width: 800, height: 600 };

  beforeEach(() => {
    vi.useFakeTimers();
    size = { width: 800, height: 600 };
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      () =>
        ({
          ...size,
          x: 0,
          y: 0,
          top: 0,
          left: 0,
          right: size.width,
          bottom: size.height,
          toJSON: () => ({}),
        }) as DOMRect,
    );
    Object.defineProperty(window, "devicePixelRatio", {
      value: 1,
      configurable: true,
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    engine.resize.mockClear();
  });

  it("fills the window and renders at half its resolution", () => {
    act(() => root.render(<KawarpWrapper />));
    const canvas = container.querySelector("canvas")!;
    expect([canvas.width, canvas.height]).toEqual([
      800 * KAWARP_RENDER_SCALE,
      600 * KAWARP_RENDER_SCALE,
    ]);
    expect(canvas.className).toContain("inset-0");
    expect(canvas.className).toContain("w-full");
    expect(canvas.className).toContain("h-full");
  });

  it("resizes once after the window settles, never while it is still moving", () => {
    act(() => root.render(<KawarpWrapper />));
    const canvas = container.querySelector("canvas")!;
    engine.resize.mockClear();
    for (const [width, height] of [
      [1100, 700],
      [1500, 900],
      [2600, 1500],
    ]) {
      size = { width, height };
      window.dispatchEvent(new Event("resize"));
      act(() => vi.advanceTimersByTime(30));
    }
    expect(engine.resize).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(KAWARP_RESIZE_SETTLE_MS));
    expect([canvas.width, canvas.height]).toEqual([1300, 750]);
    expect(engine.resize).toHaveBeenCalledTimes(1);
  });

  it("skips the resize when the window ends up at the same size", () => {
    act(() => root.render(<KawarpWrapper />));
    engine.resize.mockClear();
    size = { width: 1200, height: 800 };
    window.dispatchEvent(new Event("resize"));
    size = { width: 800, height: 600 };
    window.dispatchEvent(new Event("resize"));
    act(() => vi.advanceTimersByTime(KAWARP_RESIZE_SETTLE_MS));
    expect(engine.resize).not.toHaveBeenCalled();
  });
});
