import { describe, expect, it } from "vitest";
import { evaluateImportedTrack } from "./evaluate";

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

describe("evaluateImportedTrack reuploads and versions", () => {
  it("matches SoundCloud reupload titles with Artist - Title and random uploader account", () => {
    expectMatch(
      evaluateImportedTrack(
        source_("В. Цой - Кукушка", "Raven S.P.Q.R.", 400_000),
        [track("t6", "Кукушка", "Кино", 399_000)],
      ),
      "t6",
      80,
    );
    expectMatch(
      evaluateImportedTrack(
        source_("Агата Кристи - Как на войне", "чернова пвп", 245_000),
        [track("t7", "Как на войне", "Агата Кристи", 245_000)],
      ),
      "t7",
      85,
    );
  });

  it("strips telegram and social tags like (tgk: whitek3d) and matches cleanly", () => {
    const result = evaluateImportedTrack(
      source_("whitek3d - Катюха (tgk: whitek3d)", "whitek3d", 77_000),
      [track("t8", "Катюха", "whitek3d", 78_000)],
    );
    expectMatch(result, "t8", 85);
  });

  it("matches phonetic and transliterated track titles with matching artist and duration", () => {
    const result = evaluateImportedTrack(
      source_("Overdose Чувств", "тёмный принц", 89_000),
      [track("t9", "овердоз", "тёмный принц", 89_000)],
    );
    expectMatch(result, "t9", 80);
  });

  it("hard duration filter rejects long intro clips", () => {
    const result = evaluateImportedTrack(
      source_("Nice Track", "Some Artist", 195_000),
      [track("yt1", "Nice Track", "Some Artist", 260_000)],
    );
    expect(result).toMatchObject({
      reason: "duration_mismatch",
      proposedTrack: { id: "yt1" },
    });
  });

  it("favors tight duration match over intro video", () => {
    const result = evaluateImportedTrack(
      source_("Bangarang", "Skrillex", 195_000),
      [
        track(
          "yt_video",
          "Bangarang (Official Music Video)",
          "Skrillex",
          260_000,
        ),
        track("yt_audio", "Bangarang", "Skrillex", 196_000),
      ],
    );
    expectMatch(result, "yt_audio", 95);
  });

  it("matches VIP Flip version and rejects original or mismatched remixes", () => {
    const result = evaluateImportedTrack(
      source_(
        "Scary Monsters (VIP Flip) [FREE DL] (prod by Skrillex)",
        "Skrillex",
        195_000,
      ),
      [
        track("c_orig", "Scary Monsters", "Skrillex", 195_000),
        track("c_remix", "Scary Monsters (Zomboy Remix)", "Skrillex", 195_000),
        track("c_vip", "Scary Monsters (VIP Flip)", "Skrillex", 196_000),
      ],
    );
    expectMatch(result, "c_vip", 90);
  });

  it("matches Slowed + Reverb version and rejects original", () => {
    const result = evaluateImportedTrack(
      source_("Nightcall (Slowed + Reverb) [FREE DL]", "Kavinsky", 280_000),
      [
        track("c_orig", "Nightcall", "Kavinsky", 259_000),
        track("c_slow", "Nightcall (Slowed + Reverb)", "Kavinsky", 281_000),
      ],
    );
    expectMatch(result, "c_slow", 90);
  });

  it("matches inverted Title - Artist patterns like Она Вернется - MBAND", () => {
    const result = evaluateImportedTrack(
      source_("Она Вернется - MBAND", "isthename", 249_210),
      [track("c_mband", "Она вернётся", "MBAND", 250_000)],
    );
    expectMatch(result, "c_mband", 95);
  });

  it("detects in-title artist when uploader account is random", () => {
    const result = evaluateImportedTrack(
      source_(
        "Танцуй пока молодой (рэп версия) Ne Budite Spyashchikh",
        "wqallz",
        214_382,
      ),
      [
        track(
          "c_dance",
          "Танцуй пока молодой (рэп версия)",
          "Не будите спящих",
          215_000,
        ),
      ],
    );
    expectMatch(result, "c_dance", 85);
  });

  it("matches token subsets and strips audio extensions like .mp3", () => {
    const result = evaluateImportedTrack(
      source_("Света - Мы в машине с тобой целуемся.mp3", "zhivchik", 210_541),
      [track("c_sveta", "В машине целуемся", "Света", 214_000)],
    );
    expectMatch(result, "c_sveta", 80);
  });

  it("rejects low title similarity false-positives even when artist matches", () => {
    const face = evaluateImportedTrack(
      source_("FACE - Еду в магазин", "FACE", 140_000),
      [track("c_face_wrong", "Магазин", "FACE", 140_000)],
    );
    expect(face).toMatchObject({ reason: "low_confidence_match" });
    const yung = evaluateImportedTrack(
      source_("YUNG TRAPPA - Давай кинем барыгу", "YUNG TRAPPA", 150_000),
      [track("c_yung_wrong", "Любит", "YUNG TRAPPA", 150_000)],
    );
    expect("reason" in yung).toBe(true);
  });
});
