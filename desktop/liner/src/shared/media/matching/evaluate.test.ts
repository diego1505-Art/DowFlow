import { describe, expect, it } from "vitest";
import { evaluateImportedTrack, matchImportedTrack } from "./evaluate";

const source = {
  sourceId: "source",
  title: "Song Name",
  artists: ["Artist"],
  durationMs: 180_000,
};
const matching = {
  id: "track",
  title: "Song Name",
  artists: [{ id: "artist", name: "Artist" }],
  durationMs: 181_000,
};

function track(id: string, title: string, artist: string, durationMs: number) {
  return { id, title, artists: [{ id: `a_${id}`, name: artist }], durationMs };
}

function source_(title: string, artist: string, durationMs: number) {
  return { sourceId: "src", title, artists: [artist], durationMs };
}

function expectMatch(
  result: ReturnType<typeof evaluateImportedTrack>,
  id: string,
  minScore: number,
) {
  expect("track" in result).toBe(true);
  if ("track" in result) {
    expect(result.track.id).toBe(id);
    expect(result.score).toBeGreaterThanOrEqual(minScore);
  }
}

describe("evaluateImportedTrack basics", () => {
  it("accepts a strong title, artist, and duration match", () => {
    expect(matchImportedTrack(source, [matching])).toMatchObject({
      track: matching,
    });
  });

  it("rejects a high-title but wrong-artist, wrong-duration substitution", () => {
    const wrong = {
      ...matching,
      artists: [{ id: "other", name: "Someone Else" }],
      durationMs: 240_000,
    };
    expect(matchImportedTrack(source, [wrong])).toBeUndefined();
  });

  it("rejects ambiguous candidates instead of guessing", () => {
    const remix = track("track1", "Song Name (Remix)", "Artist", 180_000);
    const live = track("track2", "Song Name (Live)", "Artist", 180_000);
    expect(matchImportedTrack(source, [remix, live])).toBeUndefined();
  });

  it("explains a rejected duration mismatch", () => {
    expect(
      evaluateImportedTrack(source, [{ ...matching, durationMs: 240_000 }]),
    ).toMatchObject({
      reason: "duration_mismatch",
    });
  });

  it("returns low confidence when there are no candidates", () => {
    expect(evaluateImportedTrack(source, [])).toEqual({
      reason: "low_confidence_match",
    });
  });

  it("correctly matches Cyrillic track title and artist with bounded score", () => {
    const result = evaluateImportedTrack(
      source_("Скажи мне кто ты", "xxxmanera", 132162),
      [
        track("t1", "Скажи мне кто ты", "xxxmanera", 132000),
        track("t2", "Другой трек", "xxxmanera", 180000),
      ],
    );
    expect(result).toMatchObject({ score: 100, track: { id: "t1" } });
  });

  it("matches tracks ignoring parentheses on both source and candidate", () => {
    const featSource = source_(
      "Say So (feat. Nicki Minaj)",
      "Doja Cat",
      206_000,
    );
    expect(
      evaluateImportedTrack(featSource, [
        track("t2", "Say So", "Doja Cat", 206_000),
      ]),
    ).toMatchObject({
      score: 100,
      track: { id: "t2" },
    });
    const cleanSource = source_("Say So", "Doja Cat", 206_000);
    const featCandidate = track(
      "t3",
      "Say So (feat. Doja Cat)",
      "Doja Cat",
      206_000,
    );
    expect(evaluateImportedTrack(cleanSource, [featCandidate])).toMatchObject({
      score: 100,
      track: { id: "t3" },
    });
  });

  it("matches transliterated artist names like Poshlaya Molly and Пошлая Молли", () => {
    const result = evaluateImportedTrack(
      source_("Адская колыбельная", "Poshlaya Molly", 178_000),
      [track("t4", "Адская колыбельная", "Пошлая Молли", 179_000)],
    );
    expectMatch(result, "t4", 0);
  });

  it("matches hyphenated version tags like - Mono with bracketed (Mono)", () => {
    const result = evaluateImportedTrack(
      source_(
        "(I Can't Get No) Satisfaction - Mono",
        "The Rolling Stones",
        223_000,
      ),
      [
        track(
          "t5",
          "(I Can't Get No) Satisfaction (Mono)",
          "The Rolling Stones",
          224_000,
        ),
      ],
    );
    expectMatch(result, "t5", 0);
  });
});
