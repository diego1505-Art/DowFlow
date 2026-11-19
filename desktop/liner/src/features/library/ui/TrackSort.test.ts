import { describe, expect, it } from "vitest";
import { sortOptionsFor, sortTracks } from "./TrackSort";

const track = (title: string, addedAt?: string) => ({
  title,
  durationMs: 0,
  playCount: 0,
  addedAt,
});

describe("sort by date added", () => {
  it("puts the most recently added tracks first", () => {
    const tracks = [
      track("old", "2026-01-01T00:00:00Z"),
      track("newest", "2026-10-20T00:00:00Z"),
      track("middle", "2026-05-01T00:00:00Z"),
    ];
    expect(sortTracks(tracks, "added").map((t) => t.title)).toEqual([
      "newest",
      "middle",
      "old",
    ]);
  });

  it("keeps tracks without a date at the end in their original order", () => {
    const tracks = [
      track("a"),
      track("dated", "2026-03-01T00:00:00Z"),
      track("b"),
    ];
    expect(sortTracks(tracks, "added").map((t) => t.title)).toEqual([
      "dated",
      "a",
      "b",
    ]);
  });

  it("only offers the option when the list has dates", () => {
    expect(sortOptionsFor([track("album track")])).not.toContain("added");
    expect(
      sortOptionsFor([track("playlist track", "2026-03-01T00:00:00Z")]),
    ).toContain("added");
  });
});
