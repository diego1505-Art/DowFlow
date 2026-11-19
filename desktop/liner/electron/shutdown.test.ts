import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createShutdown } from "./shutdown";

describe("createShutdown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("runs every cleanup step once, even when an earlier one throws", () => {
    const a = vi.fn(() => {
      throw new Error("boom");
    });
    const b = vi.fn();
    const s = createShutdown({
      cleanup: [a, b],
      quit: vi.fn(),
      forceExit: vi.fn(),
      watchdogMs: 1000,
    });
    s.begin();
    s.begin();
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    expect(s.isQuitting()).toBe(true);
  });

  it("quits after cleaning up, and still quits if cleanup throws", () => {
    const order: string[] = [];
    const s = createShutdown({
      cleanup: [
        () => {
          order.push("cleanup");
          throw new Error("x");
        },
      ],
      quit: () => order.push("quit"),
      forceExit: vi.fn(),
      watchdogMs: 1000,
    });
    s.quit();
    expect(order).toEqual(["cleanup", "quit"]);
  });

  it("forces the exit when the graceful quit hangs", () => {
    const forceExit = vi.fn();
    const s = createShutdown({
      cleanup: [],
      quit: vi.fn(),
      forceExit,
      watchdogMs: 4000,
    });
    s.quit();
    vi.advanceTimersByTime(3999);
    expect(forceExit).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(forceExit).toHaveBeenCalledTimes(1);
  });

  it("forces the exit immediately when quit itself throws", () => {
    const forceExit = vi.fn();
    const s = createShutdown({
      cleanup: [],
      quit: () => {
        throw new Error("nope");
      },
      forceExit,
      watchdogMs: 4000,
    });
    s.quit();
    expect(forceExit).toHaveBeenCalledTimes(1);
  });

  it("is not quitting until asked", () => {
    const s = createShutdown({
      cleanup: [],
      quit: vi.fn(),
      forceExit: vi.fn(),
      watchdogMs: 10,
    });
    expect(s.isQuitting()).toBe(false);
  });
});
