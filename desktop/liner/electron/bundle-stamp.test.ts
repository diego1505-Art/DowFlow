import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createBundleErrorStamp,
  formatBundleStamp,
  type BundleUpdateState,
} from "./bundle-stamp";

const info = { version: "0.1.36", isOta: true, sha256: "a1b2c3d4e5f6" };

function setup(update: BundleUpdateState = { kind: "latest" }) {
  const emitted: string[] = [];
  const peekUpdate = vi.fn(async () => update);
  const stamp = createBundleErrorStamp(
    { getVersionInfo: () => info, peekUpdate },
    { emit: (line) => emitted.push(line) },
  );
  return { emitted, peekUpdate, stamp };
}

describe("formatBundleStamp", () => {
  it("shows the bundle version, build and update state", () => {
    expect(formatBundleStamp(info, { kind: "latest" })).toBe(
      "0.1.36 ota a1b2c3d · update available: no",
    );
    expect(
      formatBundleStamp(info, { kind: "available", version: "0.1.37" }),
    ).toBe("0.1.36 ota a1b2c3d · update available: yes (0.1.37)");
    expect(
      formatBundleStamp(
        { version: "0.1.35", isOta: false, sha256: null },
        { kind: "inactive" },
      ),
    ).toBe("0.1.35 · update available: n/a (dev)");
    expect(formatBundleStamp(info, { kind: "unknown" })).toContain("unknown");
    expect(formatBundleStamp(info, { kind: "needs-app-update" })).toContain(
      "newer app",
    );
  });
});

describe("createBundleErrorStamp", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("logs one line after a burst of errors goes quiet", async () => {
    const { emitted, stamp } = setup({ kind: "available", version: "0.1.37" });
    stamp.onRendererError();
    await vi.advanceTimersByTimeAsync(400);
    stamp.onRendererError();
    stamp.onRendererError();
    expect(emitted).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(emitted).toEqual([
      "0.1.36 ota a1b2c3d · update available: yes (0.1.37)",
    ]);
  });

  it("does not repeat the line more than once per interval", async () => {
    const { emitted, stamp } = setup();
    stamp.onRendererError();
    await vi.advanceTimersByTimeAsync(1000);
    stamp.onRendererError();
    await vi.advanceTimersByTimeAsync(3000);
    expect(emitted).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(emitted).toHaveLength(2);
  });

  it("reuses the update check result instead of asking the server every time", async () => {
    const { peekUpdate, stamp } = setup();
    for (let i = 0; i < 3; i += 1) {
      stamp.onRendererError();
      await vi.advanceTimersByTimeAsync(9000);
    }
    expect(peekUpdate).toHaveBeenCalledTimes(1);
  });

  it("reports an unknown state when the update check throws", async () => {
    const emitted: string[] = [];
    const stamp = createBundleErrorStamp(
      {
        getVersionInfo: () => info,
        peekUpdate: async () => Promise.reject(new Error("offline")),
      },
      { emit: (line) => emitted.push(line) },
    );
    stamp.onRendererError();
    await vi.advanceTimersByTimeAsync(1000);
    expect(emitted[0]).toContain("unknown");
  });

  it("stops after dispose", async () => {
    const { emitted, stamp } = setup();
    stamp.onRendererError();
    stamp.dispose();
    await vi.advanceTimersByTimeAsync(5000);
    expect(emitted).toHaveLength(0);
  });
});
