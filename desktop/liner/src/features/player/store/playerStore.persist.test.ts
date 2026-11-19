import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Track } from "@/shared/types";

const SESSION_KEY = "liner_player_session_v2";
const TICK_MS = 250;
const SIMULATED_MS = 10_000;

function makeQueue(size: number): Track[] {
  return Array.from({ length: size }, (_, i) => ({
    id: `track-${i}`,
    title: `Track number ${i} with a reasonably long title`,
    artists: `Artist ${i % 97}, Featured ${i % 13}`,
    coverUrl: `https://cdn.example.com/covers/${i}/600x600.jpg`,
    durationMs: 180_000 + i,
    playCount: i,
    album: { id: `album-${i % 300}`, title: `Album ${i % 300}` },
  }));
}

async function loadStore() {
  vi.resetModules();
  const mod = await import("./playerStore");
  const storage = await import("@/shared/utils/storage");
  return {
    usePlayerStore: mod.usePlayerStore,
    flush: storage.debouncedStorage.flush,
  };
}

function meter() {
  const realStringify = JSON.stringify;
  const totals = { stringifiedBytes: 0, storageWrites: 0, storageBytes: 0 };
  vi.spyOn(JSON, "stringify").mockImplementation(((
    ...args: Parameters<typeof JSON.stringify>
  ) => {
    const out = realStringify(...args);
    totals.stringifiedBytes += out?.length ?? 0;
    return out;
  }) as typeof JSON.stringify);
  const realSetItem = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key: string,
    value: string,
  ) {
    totals.storageWrites += 1;
    totals.storageBytes += value.length;
    return realSetItem.call(this, key, value);
  });
  return totals;
}

describe("player store persistence under playback ticks", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("does not serialize or write the queue on position ticks", async () => {
    const { usePlayerStore } = await loadStore();
    const queue = makeQueue(3000);
    usePlayerStore.setState({
      queue,
      currentTrack: queue[0],
      currentIndex: 0,
      status: "playing",
      durationMs: 180_000,
    });
    await vi.advanceTimersByTimeAsync(1_000);

    const totals = meter();
    for (let t = 0; t < SIMULATED_MS; t += TICK_MS) {
      usePlayerStore.getState().setPosition(t);
      vi.advanceTimersByTime(TICK_MS);
    }
    vi.restoreAllMocks();

    process.stdout.write(
      `[perf] 10s playback, 3000-track queue: ${totals.stringifiedBytes} bytes JSON-serialized, ${totals.storageWrites} storage writes, ${totals.storageBytes} bytes written\n`,
    );
    expect(totals.stringifiedBytes).toBeLessThan(2_000);
    expect(totals.storageWrites).toBeLessThanOrEqual(2);
    expect(totals.storageBytes).toBeLessThan(2_000);
  });

  it("still writes the queue when it actually changes", async () => {
    const { usePlayerStore, flush } = await loadStore();
    const queue = makeQueue(10);
    usePlayerStore.setState({ queue, currentTrack: queue[0], currentIndex: 0 });
    flush();
    const saved = JSON.parse(localStorage.getItem(SESSION_KEY) ?? "{}");
    expect(saved.state.queue).toHaveLength(10);
    expect(saved.state.currentTrack.id).toBe("track-0");

    usePlayerStore.getState().setQueue(queue.slice(0, 3));
    flush();
    expect(
      JSON.parse(localStorage.getItem(SESSION_KEY) ?? "{}").state.queue,
    ).toHaveLength(3);
  });

  it("restores track and position saved by an older build", async () => {
    const queue = makeQueue(5);
    localStorage.setItem(
      SESSION_KEY,
      JSON.stringify({
        state: {
          queue,
          currentIndex: 2,
          currentTrack: queue[2],
          positionMs: 42_000,
          durationMs: 180_002,
          volume: 0.4,
        },
        version: 0,
      }),
    );
    const { usePlayerStore } = await loadStore();
    const state = usePlayerStore.getState();
    expect(state.currentTrack?.id).toBe("track-2");
    expect(state.positionMs).toBe(42_000);
    expect(state.status).toBe("paused");
    expect(state.queue).toHaveLength(5);
    expect(state.volume).toBe(0.4);
  });

  it("restores the resume position saved on pause", async () => {
    const first = await loadStore();
    const queue = makeQueue(5);
    first.usePlayerStore.setState({
      queue,
      currentTrack: queue[1],
      currentIndex: 1,
      status: "playing",
    });
    first.usePlayerStore.getState().setPosition(5_000);
    first.usePlayerStore.getState().setPosition(73_250);
    first.usePlayerStore.getState().setStatus("paused");
    first.flush();

    const second = await loadStore();
    const state = second.usePlayerStore.getState();
    expect(state.currentTrack?.id).toBe("track-1");
    expect(state.positionMs).toBe(73_250);
    expect(state.status).toBe("paused");
  });

  it("saves the resume position on a slow cadence while playing and on unload", async () => {
    const first = await loadStore();
    const queue = makeQueue(5);
    first.usePlayerStore.setState({
      queue,
      currentTrack: queue[0],
      currentIndex: 0,
      status: "playing",
    });
    first.flush();
    for (let t = 0; t <= 12_000; t += TICK_MS) {
      first.usePlayerStore.getState().setPosition(t);
      vi.advanceTimersByTime(TICK_MS);
    }
    first.flush();
    const reloaded = await loadStore();
    expect(
      reloaded.usePlayerStore.getState().positionMs,
    ).toBeGreaterThanOrEqual(10_000);

    reloaded.usePlayerStore.setState({ status: "playing" });
    reloaded.usePlayerStore.getState().setPosition(15_500);
    window.dispatchEvent(new Event("beforeunload"));
    const afterUnload = await loadStore();
    expect(afterUnload.usePlayerStore.getState().positionMs).toBe(15_500);
  });

  it("does not restore a stale position onto a different track", async () => {
    const first = await loadStore();
    const queue = makeQueue(5);
    first.usePlayerStore.setState({
      queue,
      currentTrack: queue[0],
      currentIndex: 0,
      status: "playing",
    });
    first.usePlayerStore.getState().setPosition(90_000);
    first.usePlayerStore.getState().setStatus("paused");
    first.usePlayerStore.getState().setCurrentTrack(queue[3], 3);
    first.flush();

    const second = await loadStore();
    expect(second.usePlayerStore.getState().currentTrack?.id).toBe("track-3");
    expect(second.usePlayerStore.getState().positionMs).toBe(0);
  });
});
