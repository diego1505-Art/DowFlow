import { describe, expect, it, vi } from "vitest";
import { createSleepBlocker } from "./sleep-blocker";

describe("createSleepBlocker", () => {
  it("blocks sleep once while playing and releases on pause", () => {
    const blocker = { start: vi.fn(() => 7), stop: vi.fn() };
    const update = createSleepBlocker(blocker);

    update("playing");
    update("buffering");
    update("playing");
    expect(blocker.start).toHaveBeenCalledTimes(1);
    expect(blocker.start).toHaveBeenCalledWith("prevent-display-sleep");

    update("paused");
    update("idle");
    expect(blocker.stop).toHaveBeenCalledTimes(1);
    expect(blocker.stop).toHaveBeenCalledWith(7);
  });

  it("does nothing when never playing", () => {
    const blocker = { start: vi.fn(() => 1), stop: vi.fn() };
    const update = createSleepBlocker(blocker);

    update("idle");
    update("paused");
    expect(blocker.start).not.toHaveBeenCalled();
    expect(blocker.stop).not.toHaveBeenCalled();
  });
});
