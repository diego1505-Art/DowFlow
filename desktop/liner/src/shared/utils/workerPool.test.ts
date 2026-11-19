import { describe, expect, it } from "vitest";
import { runWorkerPool } from "./workerPool";

describe("runWorkerPool", () => {
  it("runs every item without exceeding the concurrency limit", async () => {
    let active = 0;
    let peak = 0;
    const seen: number[] = [];
    await runWorkerPool([1, 2, 3, 4, 5], 2, async (item, index) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 1));
      seen[index] = item;
      active -= 1;
    });
    expect(seen).toEqual([1, 2, 3, 4, 5]);
    expect(peak).toBe(2);
  });

  it("stops taking new items after a task fails", async () => {
    const started: number[] = [];
    const run = runWorkerPool([1, 2, 3, 4], 1, async (item) => {
      started.push(item);
      if (item === 2) throw new Error("boom");
    });
    await expect(run).rejects.toThrow("boom");
    expect(started).toEqual([1, 2]);
  });
});
