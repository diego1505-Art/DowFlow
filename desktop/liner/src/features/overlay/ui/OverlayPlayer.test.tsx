import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

vi.mock("@/features/covers/ui/CoverImage", () => ({ default: () => null }));

import { OverlayPlayer } from "./OverlayPlayer";

const playingState = {
  status: "playing",
  track: { id: "a", title: "Song", artist: "Artist", durationMs: 200_000 },
  positionMs: 30_000,
  durationMs: 200_000,
  volume: 1,
  isLiked: false,
};

describe("OverlayPlayer animation loop", () => {
  let container: HTMLDivElement;
  let root: Root;
  let rafCalls: number;
  let visibility: ((visible: boolean) => void) | null;
  let pushState: ((state: unknown) => void) | null;
  let initialState: Record<string, unknown>;

  async function mount() {
    window.linerElectron = {
      platform: "win32",
      getOverlayInitialState: () => Promise.resolve(initialState),
      onOverlayState: (cb: (state: unknown) => void) => {
        pushState = cb;
        return () => {};
      },
      onOverlayVisibility: (cb: (visible: boolean) => void) => {
        visibility = cb;
        return () => {};
      },
      overlayReady: () => {},
      sendOverlayAction: () => {},
    } as never;
    await act(async () => {
      root.render(<OverlayPlayer />);
    });
    await act(async () => {
      await Promise.resolve();
    });
  }

  async function advance(ms: number) {
    await act(async () => {
      vi.advanceTimersByTime(ms);
    });
  }

  function progressPercent() {
    const bar = Array.from(
      container.querySelectorAll<HTMLElement>("[style]"),
    ).find((el) => el.style.width.endsWith("%"));
    return bar ? parseFloat(bar.style.width) : NaN;
  }

  beforeEach(() => {
    vi.useFakeTimers();
    rafCalls = 0;
    visibility = null;
    pushState = null;
    initialState = { ...playingState };
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      rafCalls += 1;
      return setTimeout(() => cb(performance.now()), 16) as unknown as number;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => clearTimeout(id));
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    delete window.linerElectron;
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("does not animate while the overlay window is hidden", async () => {
    await mount();
    await advance(2_000);
    rafCalls = 0;
    await advance(10_000);
    const hidden = rafCalls;

    await act(async () => visibility?.(true));
    await act(async () => {
      await Promise.resolve();
    });
    rafCalls = 0;
    await advance(1_000);
    const shown = rafCalls;

    await act(async () => visibility?.(false));
    await advance(2_000);
    rafCalls = 0;
    await advance(10_000);
    const hiddenAgain = rafCalls;
    process.stdout.write(
      `[perf] overlay rAF calls: 10s hidden ${hidden}, 1s shown ${shown}, 10s hidden again ${hiddenAgain}\n`,
    );

    expect(hidden).toBe(0);
    expect(shown).toBeGreaterThan(10);
    expect(hiddenAgain).toBe(0);
    expect(pushState).not.toBeNull();
  });

  it("starts from the position extrapolated since the state was sampled", async () => {
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    initialState = {
      ...playingState,
      positionMs: 30_000,
      positionAt: Date.now() - 20_000,
    };
    await mount();
    await act(async () => visibility?.(true));
    await act(async () => {
      await Promise.resolve();
    });
    await advance(100);
    expect(progressPercent()).toBeGreaterThan(24.9);
    expect(progressPercent()).toBeLessThan(25.5);
  });
});
