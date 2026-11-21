// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/shared/api", () => ({
  api: {
    listPlaylists: vi.fn(async () => ({ items: [] })),
    readUserPlaylist: vi.fn(),
    getUserPlaylist: vi.fn(),
  },
  getAuthSession: () => null,
  mediaUrl: (url: string) => url,
  toClientTrack: (track: any) => ({
    id: track.id,
    title: track.title,
    artists: track.artists ?? "",
    coverUrl: track.coverUrl ?? "",
    durationMs: track.durationMs ?? 0,
    playCount: 0,
  }),
}));

const flush = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

describe("local playlists in the library", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    window.localStorage.clear();
    vi.resetModules();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    document.body.removeChild(container);
  });

  it("lists and opens a playlist created without an account", async () => {
    const { usePlaylist, usePlaylistsList } = await import("./usePlaylists");
    const { addLocalPlaylistTrack, createLocalPlaylist } =
      await import("../local/playlists");
    const created = createLocalPlaylist("Local mix", "On this device");
    addLocalPlaylistTrack(created.id, {
      id: "track-a",
      title: "Track A",
      artists: "Artist",
      coverUrl: "https://img/a",
      durationMs: 2000,
      playCount: 0,
    });

    let list: ReturnType<typeof usePlaylistsList> | undefined;
    let detail: ReturnType<typeof usePlaylist> | undefined;
    function Probe() {
      list = usePlaylistsList();
      detail = usePlaylist(created.id);
      return null;
    }

    act(() => root.render(<Probe />));
    await flush();

    expect(list?.data.playlists.map((playlist) => playlist.id)).toContain(
      created.id,
    );
    expect(list?.data.playlists[0].title).toBe("Local mix");
    expect(detail?.data?.title).toBe("Local mix");
    expect(detail?.data?.tracks.map((track) => track.id)).toEqual(["track-a"]);
    expect(detail?.isLoading).toBe(false);
  });

  it("shows a playlist created while the library is already open", async () => {
    const { usePlaylistsList } = await import("./usePlaylists");
    const { createLocalPlaylist } = await import("../local/playlists");

    let list: ReturnType<typeof usePlaylistsList> | undefined;
    function Probe() {
      list = usePlaylistsList();
      return null;
    }

    act(() => root.render(<Probe />));
    await flush();
    expect(list?.data.playlists).toHaveLength(0);

    let createdId = "";
    act(() => {
      createdId = createLocalPlaylist("Created later").id;
    });
    await flush();

    expect(list?.data.playlists.map((playlist) => playlist.id)).toContain(
      createdId,
    );
    expect(list?.data.playlists[0].title).toBe("Created later");
  });
});
