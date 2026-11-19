// @vitest-environment jsdom
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { freshFor, useCachedResource } from "./useCachedResource";
import {
  clearScreenCache,
  readScreenCache,
  writeScreenCache,
} from "./screenCache";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

let latest: { data: string[] | undefined; isLoading: boolean } | null = null;
let renders = 0;

function Probe({
  cacheKey,
  load,
}: {
  cacheKey: string;
  load: () => Promise<string[]>;
}) {
  renders += 1;
  latest = useCachedResource(cacheKey, load, { isFresh: freshFor(60_000) });
  return null;
}

function SessionProbe({
  cacheKey,
  load,
}: {
  cacheKey: string;
  load: () => Promise<string[]>;
}) {
  latest = useCachedResource(cacheKey, load, {
    isFresh: freshFor(60_000),
    sessionOnly: true,
  });
  return null;
}

describe("useCachedResource", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    clearScreenCache();
    renders = 0;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    latest = null;
    vi.useRealTimers();
  });

  it("serves fresh cached data without loading again", async () => {
    writeScreenCache("fresh", ["cached"]);
    const load = vi.fn(async () => ["network"]);
    await act(async () => {
      root.render(<Probe cacheKey="fresh" load={load} />);
    });
    expect(load).not.toHaveBeenCalled();
    expect(latest).toEqual({ data: ["cached"], isLoading: false });
  });

  it("revalidates stale data and skips a rerender when nothing changed", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    writeScreenCache("stale", ["same"]);
    vi.setSystemTime(Date.now() + 120_000);
    const load = vi.fn(async () => ["same"]);
    await act(async () => {
      root.render(<Probe cacheKey="stale" load={load} />);
    });
    expect(load).toHaveBeenCalledTimes(1);
    expect(latest?.data).toEqual(["same"]);
    expect(renders).toBe(1);
    expect(readScreenCache("stale")?.savedAt).toBe(Date.now());
  });

  it("ignores a copy from disk in session-only mode and shows only the server result", async () => {
    writeScreenCache("mixes", ["from disk"]);
    let resolve: (value: string[]) => void = () => undefined;
    const load = vi.fn(() => new Promise<string[]>((done) => (resolve = done)));
    await act(async () => {
      root.render(<SessionProbe cacheKey="mixes" load={load} />);
    });
    expect(load).toHaveBeenCalledTimes(1);
    expect(latest).toEqual({ data: undefined, isLoading: true });
    await act(async () => resolve(["from server"]));
    expect(latest).toEqual({ data: ["from server"], isLoading: false });
    expect(readScreenCache("mixes")?.sessionOnly).toBe(true);
  });

  it("stops reporting loading when the first load fails", async () => {
    const load = vi.fn(async (): Promise<string[]> => {
      throw new Error("offline");
    });
    await act(async () => {
      root.render(<Probe cacheKey="failing" load={load} />);
    });
    expect(latest).toEqual({ data: undefined, isLoading: false });
  });
});
