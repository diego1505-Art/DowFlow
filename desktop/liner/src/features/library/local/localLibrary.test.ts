// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Track } from "@/shared/types";

const track = (id: string, title = id): Track => ({
  id,
  title,
  artists: "Artist",
  coverUrl: `https://img/${id}`,
  durationMs: 1000,
  playCount: 0,
});

beforeEach(() => {
  window.localStorage.clear();
  vi.resetModules();
});

describe("local likes", () => {
  it("keeps a like across module reloads", async () => {
    const likes = await import("./likes");
    likes.addLocalLike(track("a", "Song A"));

    expect(likes.getLocalLikes().map((item) => item.id)).toEqual(["a"]);

    vi.resetModules();
    const reloaded = await import("./likes");
    expect(reloaded.getLocalLikes().map((item) => item.id)).toEqual(["a"]);
    expect(reloaded.isLocalTrackLiked("a")).toBe(true);
  });

  it("removes an unlike and keeps the newest first", async () => {
    const likes = await import("./likes");
    likes.addLocalLike(track("a"));
    likes.addLocalLike(track("b"));
    likes.addLocalLike(track("a"));

    expect(likes.getLocalLikes().map((item) => item.id)).toEqual(["a", "b"]);
    likes.removeLocalLike("a");
    expect(likes.getLocalLikes().map((item) => item.id)).toEqual(["b"]);
  });
});

describe("local playlists", () => {
  it("creates a playlist and adds playable tracks", async () => {
    const playlists = await import("./playlists");
    const created = playlists.createLocalPlaylist("My mix", "Local only");

    expect(playlists.isLocalPlaylistId(created.id)).toBe(true);
    playlists.addLocalPlaylistTrack(created.id, track("a"));
    playlists.addLocalPlaylistTrack(created.id, track("b"));

    const summary = playlists.getLocalPlaylistSummaries()[0];
    expect(summary.title).toBe("My mix");
    expect(summary.trackCount).toBe(2);
    expect(summary.coverUrls).toEqual(["https://img/a", "https://img/b"]);

    const detail = playlists.getLocalPlaylist(created.id);
    expect(detail?.tracks.map((item) => item.id)).toEqual(["a", "b"]);
    expect(detail?.tracks[0].playlistItemId).toBeTruthy();
  });

  it("renames, reorders, removes tracks and deletes the playlist", async () => {
    const playlists = await import("./playlists");
    const created = playlists.createLocalPlaylist("My mix");
    playlists.addLocalPlaylistTrack(created.id, track("a"));
    playlists.addLocalPlaylistTrack(created.id, track("b"));

    const detail = playlists.getLocalPlaylist(created.id)!;
    const firstItem = detail.tracks[0].playlistItemId!;
    playlists.moveLocalPlaylistTrack(created.id, firstItem, null);
    expect(
      playlists.getLocalPlaylist(created.id)?.tracks.map((item) => item.id),
    ).toEqual(["b", "a"]);

    playlists.updateLocalPlaylist(created.id, { title: "Renamed" });
    expect(playlists.getLocalPlaylist(created.id)?.title).toBe("Renamed");

    playlists.removeLocalPlaylistTrack(created.id, firstItem);
    expect(playlists.getLocalPlaylist(created.id)?.tracks).toHaveLength(1);

    playlists.deleteLocalPlaylist(created.id);
    expect(playlists.getLocalPlaylists()).toHaveLength(0);
  });
});
