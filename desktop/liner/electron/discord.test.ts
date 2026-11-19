import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  setActivity: vi.fn(async (_activity: Record<string, unknown>) => undefined),
  clearActivity: vi.fn(async () => undefined),
  clients: [] as string[],
}));

vi.mock("electron", () => ({ ipcMain: { on: vi.fn(), handle: vi.fn() } }));

vi.mock("@xhayper/discord-rpc", () => {
  class Client {
    user = {
      setActivity: mocks.setActivity,
      clearActivity: mocks.clearActivity,
      username: "tester",
    };
    private handlers = new Map<string, () => void>();
    constructor({ clientId }: { clientId: string }) {
      mocks.clients.push(clientId);
    }
    on(event: string, handler: () => void) {
      this.handlers.set(event, handler);
    }
    async login() {
      this.handlers.get("ready")?.();
    }
    destroy() {}
  }
  return { Client, StatusDisplayType: { NAME: 0, STATE: 1, DETAILS: 2 } };
});

import {
  DiscordRpcManager,
  toDiscordImageUrl,
  type DiscordRpcStatePayload,
} from "./discord";

function playing(
  id: string,
  coverUrl = "https://i.ytimg.com/vi/x/hq.jpg",
): DiscordRpcStatePayload {
  return {
    status: "playing",
    track: {
      id,
      title: `Song ${id}`,
      artist: "Artist",
      coverUrl,
      durationMs: 200_000,
    },
    positionMs: 0,
    durationMs: 200_000,
    artistImageUrl: "https://lh3.googleusercontent.com/a.jpg",
  };
}

describe("toDiscordImageUrl", () => {
  it("passes only https urls short enough for discord", () => {
    expect(toDiscordImageUrl("https://i.ytimg.com/vi/x/hq.jpg")).toBe(
      "https://i.ytimg.com/vi/x/hq.jpg",
    );
    expect(toDiscordImageUrl("http://example.com/a.jpg")).toBeUndefined();
    expect(toDiscordImageUrl("blob:file:///abc")).toBeUndefined();
    expect(toDiscordImageUrl("data:image/png;base64,AAAA")).toBeUndefined();
    expect(
      toDiscordImageUrl(`https://example.com/${"a".repeat(260)}`),
    ).toBeUndefined();
    expect(toDiscordImageUrl(undefined)).toBeUndefined();
  });
});

describe("DiscordRpcManager", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.setActivity.mockClear();
    mocks.clients.length = 0;
    process.env.LINER_DISCORD_CLIENT_ID = "123456789012345678";
  });

  afterEach(() => {
    delete process.env.LINER_DISCORD_CLIENT_ID;
    vi.useRealTimers();
  });

  it("connects with Liner's built-in application id by default", async () => {
    delete process.env.LINER_DISCORD_CLIENT_ID;
    const manager = new DiscordRpcManager();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(mocks.clients).toEqual(["1561339119617974362"]);
    manager.destroy();
  });

  it("ignores an application id sent in a settings patch", async () => {
    delete process.env.LINER_DISCORD_CLIENT_ID;
    const manager = new DiscordRpcManager();
    const legacyPatch: Record<string, unknown> = {
      applicationId: "987654321098765432",
    };
    manager.updateSettings(legacyPatch);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(mocks.clients).toEqual(["1561339119617974362"]);
    manager.destroy();
  });

  it("collapses a burst of track changes into one update with the latest track", async () => {
    const manager = new DiscordRpcManager();
    await vi.advanceTimersByTimeAsync(5_000);
    mocks.setActivity.mockClear();
    for (const id of ["a", "b", "c", "d"]) {
      manager.updateState(playing(id));
      await vi.advanceTimersByTimeAsync(300);
    }
    await vi.advanceTimersByTimeAsync(5_000);
    expect(mocks.setActivity).toHaveBeenCalledTimes(1);
    expect(mocks.setActivity.mock.calls[0][0]).toMatchObject({
      details: "Song d",
    });
    manager.destroy();
  });

  it("keeps updates at least 4 seconds apart", async () => {
    const manager = new DiscordRpcManager();
    await vi.advanceTimersByTimeAsync(5_000);
    mocks.setActivity.mockClear();
    manager.updateState(playing("a"));
    await vi.advanceTimersByTimeAsync(1_100);
    manager.updateState(playing("b"));
    await vi.advanceTimersByTimeAsync(1_100);
    expect(mocks.setActivity).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3_000);
    expect(mocks.setActivity).toHaveBeenCalledTimes(2);
    manager.destroy();
  });

  it("leaves out images discord cannot load", async () => {
    const manager = new DiscordRpcManager();
    await vi.advanceTimersByTimeAsync(5_000);
    mocks.setActivity.mockClear();
    manager.updateState(playing("a", "blob:file:///cover"));
    await vi.advanceTimersByTimeAsync(5_000);
    const activity = mocks.setActivity.mock.calls[0][0];
    expect(activity.largeImageKey).toBeUndefined();
    expect(activity.smallImageKey).toBe(
      "https://lh3.googleusercontent.com/a.jpg",
    );
    manager.destroy();
  });
});
