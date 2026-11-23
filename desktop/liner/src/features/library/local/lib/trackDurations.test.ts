// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

const resolveSnapshot = vi.fn(async (id: string) => ({
  id,
  title: id,
  artists: "Artist",
  durationMs: 180_000,
  playCount: 0,
}));

vi.mock("@/shared/api/clientCatalog", () => ({
  clientCatalog: { resolveSnapshot: (id: string) => resolveSnapshot(id) },
}));

describe("track durations", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.resetModules();
    resolveSnapshot.mockClear();
  });

  it("resolves a missing length once and keeps it", async () => {
    const durations = await import("./trackDurations");

    durations.requestDurations(["track-a", "track-a"]);
    await vi.waitFor(() => expect(durations.knownDurationMs("track-a")).toBe(180_000));
    expect(resolveSnapshot).toHaveBeenCalledTimes(1);

    durations.requestDurations(["track-a"]);
    await Promise.resolve();
    expect(resolveSnapshot).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem("liner:track-durations-v1")).toContain(
      "track-a",
    );
  });

  it("gives a local playlist the length it stored without", async () => {
    const playlists = await import("../playlists");
    const durations = await import("./trackDurations");
    const created = playlists.createLocalPlaylist("bestoff");
    playlists.addLocalPlaylistTrack(created.id, {
      id: "track-a",
      title: "Track A",
      artists: "Artist",
      coverUrl: "",
      durationMs: 0,
      playCount: 0,
    });
    expect(playlists.getLocalPlaylist(created.id)?.tracks[0].durationMs).toBe(0);

    durations.requestDurations(["track-a"]);

    await vi.waitFor(() =>
      expect(playlists.getLocalPlaylist(created.id)?.tracks[0].durationMs).toBe(
        180_000,
      ),
    );
  });
});
