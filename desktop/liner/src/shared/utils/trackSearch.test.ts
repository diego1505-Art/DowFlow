import { describe, expect, it } from "vitest";
import {
  filterTracks,
  findHighlightRanges,
  normalizeForSearch,
} from "./trackSearch";

const tracks = [
  { title: "ДИНАСТИЯ", artists: "VILLIAN, madk1d" },
  { title: "ты в моих мыслях навсегда", artists: "урал гайсин, снялцепи" },
  { title: "Дві весни", artists: "Jerry Heil, Sviatoslav Vakarchuk" },
  { title: "Пьяный", artists: "Катрин Штоль", album: { title: "Ёлки" } },
  { title: "Café del Mar", artists: "Energy 52" },
  { title: "Don’t Stop", artists: "Someone" },
];

const titles = (q: string) => filterTracks(tracks, q).map((m) => m.track.title);

describe("normalizeForSearch", () => {
  it("folds case, accents and Cyrillic diacritics", () => {
    expect(normalizeForSearch("ЁЛКИ")).toBe("елки");
    expect(normalizeForSearch("Їжак")).toBe("іжак");
    expect(normalizeForSearch("Café")).toBe("cafe");
  });
});

describe("filterTracks", () => {
  it("returns everything with the original index for an empty query", () => {
    const all = filterTracks(tracks, "   ");
    expect(all).toHaveLength(tracks.length);
    expect(all[3].index).toBe(3);
  });

  it("matches title or artists, case-insensitively", () => {
    expect(titles("династия")).toEqual(["ДИНАСТИЯ"]);
    expect(titles("JERRY")).toEqual(["Дві весни"]);
  });

  it("needs every word, in any order and across fields", () => {
    expect(titles("madk dyn")).toEqual([]);
    expect(titles("madk1d дин")).toEqual(["ДИНАСТИЯ"]);
    expect(titles("весни heil")).toEqual(["Дві весни"]);
  });

  it("ignores accents and ё/е, and searches the album", () => {
    expect(titles("cafe")).toEqual(["Café del Mar"]);
    expect(titles("елки")).toEqual(["Пьяный"]);
  });

  it("folds typographic apostrophes", () => {
    expect(titles("don't")).toEqual(["Don’t Stop"]);
  });

  it("keeps the playlist order and original indices", () => {
    const res = filterTracks(tracks, "a");
    const indices = res.map((m) => m.index);
    expect(indices).toEqual([...indices].sort((a, b) => a - b));
  });
});

describe("findHighlightRanges", () => {
  it("maps matches back onto the original text", () => {
    expect(findHighlightRanges("ДИНАСТИЯ", "нас")).toEqual([[2, 5]]);
    expect(findHighlightRanges("Café del Mar", "cafe")).toEqual([[0, 4]]);
  });

  it("merges overlapping words and finds repeats", () => {
    expect(findHighlightRanges("la la land", "la lan")).toEqual([
      [0, 2],
      [3, 5],
      [6, 9],
    ]);
  });

  it("returns nothing for no match or empty query", () => {
    expect(findHighlightRanges("abc", "zz")).toEqual([]);
    expect(findHighlightRanges("abc", " ")).toEqual([]);
  });
});
