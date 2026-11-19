import { afterEach, describe, expect, it, vi } from "vitest";
import type { SearchResult } from "@/shared/contracts";

const searchRaw = vi.hoisted(() => vi.fn());
vi.mock("@/shared/youtube", () => ({ searchRaw }));

import {
  clearExactSongVersions,
  findExactSongVersion,
} from "./exactSongVersion";

const KENDRICK = { id: "UCkendrick", name: "Kendrick Lamar" };

const albumRow = {
  id: "NLZRYQMLDW4",
  title: "DNA.",
  artists: "Kendrick Lamar",
  artistList: [KENDRICK],
  durationMs: 186_000,
  audioVariant: "music-video" as const,
};

const song = (overrides: Partial<SearchResult & { type: "track" }> = {}) =>
  ({
    type: "track",
    id: "Fb3j_yuFh1s",
    title: "DNA.",
    artists: [KENDRICK],
    durationMs: 185_500,
    ...overrides,
  }) as SearchResult;

afterEach(() => {
  searchRaw.mockReset();
  clearExactSongVersions();
});

describe("findExactSongVersion", () => {
  it("takes the song when title, artist and length all match", async () => {
    searchRaw.mockResolvedValue([song()]);
    await expect(findExactSongVersion(albumRow, albumRow.id)).resolves.toBe(
      "Fb3j_yuFh1s",
    );
    expect(searchRaw).toHaveBeenCalledWith(
      "DNA. Kendrick Lamar",
      "track",
      undefined,
    );
  });

  it.each([
    ["a different title", song({ title: "DNA. (Live)" })],
    [
      "another artist with the same name",
      song({ artists: [{ id: "UCother", name: "Kendrick Lamar" }] }),
    ],
    ["a length more than 2 seconds off", song({ durationMs: 189_000 })],
    ["the album row itself", song({ id: "NLZRYQMLDW4" })],
    ["a video result", { ...song(), type: "video" } as unknown as SearchResult],
  ])("rejects %s", async (_label, candidate) => {
    searchRaw.mockResolvedValue([candidate]);
    await expect(
      findExactSongVersion(albumRow, albumRow.id),
    ).resolves.toBeNull();
  });

  it("asks once per album row and remembers the answer", async () => {
    searchRaw.mockResolvedValue([song()]);
    await findExactSongVersion(albumRow, albumRow.id);
    await findExactSongVersion(albumRow, albumRow.id);
    expect(searchRaw).toHaveBeenCalledTimes(1);
  });

  it("does not remember a failed search", async () => {
    searchRaw.mockRejectedValueOnce(new Error("offline"));
    await expect(
      findExactSongVersion(albumRow, albumRow.id),
    ).resolves.toBeNull();
    searchRaw.mockResolvedValue([song()]);
    await expect(findExactSongVersion(albumRow, albumRow.id)).resolves.toBe(
      "Fb3j_yuFh1s",
    );
  });
});
