// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api", () => ({
  api: {
    likeTrack: vi.fn(),
    unlikeTrack: vi.fn(),
    listLikedTracks: vi.fn(),
  },
  getAuthSession: () => null,
  toClientTrack: (track: any) => ({
    id: track.id,
    title: track.title,
    artists: track.artists,
    coverUrl: track.cover?.url ?? "",
    durationMs: track.durationMs ?? 0,
    playCount: 0,
  }),
}));

vi.mock("@/shared/api/clientCatalog", () => ({
  clientCatalog: {
    resolveSnapshot: vi.fn(async (id: string) => ({
      id,
      title: "Song",
      artists: "Artist",
      durationMs: 1000,
    })),
  },
}));

describe("anonymous likes", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    vi.resetModules();
  });

  it("persists the like without calling the account API", async () => {
    const { isTrackLikedNow, loadLikedTracks, toggleTrackLike } =
      await import("./useLikedTracks");
    const { api } = await import("@/shared/api");
    await loadLikedTracks();

    const { settled } = toggleTrackLike("local-a");
    expect(isTrackLikedNow("local-a")).toBe(true);

    await settled;

    expect(api.likeTrack).not.toHaveBeenCalled();
    expect(isTrackLikedNow("local-a")).toBe(true);
    const stored = JSON.parse(
      window.localStorage.getItem("liner_local_likes_v1") ?? "[]",
    );
    expect(stored).toHaveLength(1);
    expect(stored[0].track.id).toBe("local-a");
  });

  it("removes the like locally too", async () => {
    const { isTrackLikedNow, loadLikedTracks, toggleTrackLike } =
      await import("./useLikedTracks");
    const { api } = await import("@/shared/api");
    await loadLikedTracks();

    await toggleTrackLike("local-a").settled;
    const { settled } = toggleTrackLike("local-a");
    expect(isTrackLikedNow("local-a")).toBe(false);

    await settled;

    expect(api.unlikeTrack).not.toHaveBeenCalled();
    expect(
      JSON.parse(window.localStorage.getItem("liner_local_likes_v1") ?? "[]"),
    ).toHaveLength(0);
  });
});
