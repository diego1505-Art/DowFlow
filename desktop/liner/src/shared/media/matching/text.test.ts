import { describe, expect, it } from "vitest";
import { artistsMatch } from "./artists";
import { cleanSoundCloudMetadata, parseArtistAndTitle } from "./artistTitle";
import { cleanSearchTitle, stripJunk } from "./junk";
import { toPhoneticLatin } from "./phonetic";
import { levenshtein, tokenSetRatio, tokenSortRatio } from "./similarity";
import { compareVersionTags, getVersionTags } from "./versionTags";

describe("matcher text helpers", () => {
  it("tokenSortRatio handles inverted word orders cleanly", () => {
    expect(tokenSortRatio("Кино - Кукушка", "Кукушка Кино")).toBe(100);
    expect(
      tokenSortRatio("Pharaoh & Boulevard Depo", "Boulevard Depo, Pharaoh"),
    ).toBe(100);
  });

  it("tokenSetRatio rewards subsets", () => {
    expect(
      tokenSetRatio("в машине целуемся", "мы в машине с тобой целуемся"),
    ).toBe(73);
    expect(tokenSetRatio("abc", "xyz")).toBe(0);
  });

  it("computes levenshtein distance", () => {
    expect(levenshtein("kitten", "sitting")).toBe(3);
    expect(levenshtein("", "abc")).toBe(3);
  });

  it("transliterates cyrillic to phonetic latin", () => {
    expect(toPhoneticLatin("Пошлая Молли")).toBe(
      toPhoneticLatin("Poshlaya Molly"),
    );
  });

  it("matches artist aliases", () => {
    expect(artistsMatch("Кино", "Виктор Цой")).toBe(true);
    expect(artistsMatch("Pharaoh", "Фараон")).toBe(true);
    expect(artistsMatch("Skrillex", "Kavinsky")).toBe(false);
  });

  it("detects version tags", () => {
    expect([...getVersionTags("Nightcall (Slowed + Reverb)")].sort()).toEqual([
      "reverb",
      "slowed",
    ]);
    expect(compareVersionTags(new Set(), new Set())).toEqual({
      matches: true,
      penalty: 0,
      bonus: 5,
    });
    expect(compareVersionTags(new Set(["remix"]), new Set())).toEqual({
      matches: false,
      penalty: 50,
      bonus: 0,
    });
  });

  it("strips junk and search noise", () => {
    expect(stripJunk("Track (Official Video) @handle")).toBe("Track");
    expect(cleanSearchTitle("Song (Official Music Video) [Explicit]")).toBe(
      "Song",
    );
  });

  it("parses artist and title pairs", () => {
    expect(parseArtistAndTitle("Doja Cat - Say So")).toMatchObject({
      artist: "Doja Cat",
      title: "Say So",
    });
    expect(parseArtistAndTitle("Uploader - Artist - Title")).toMatchObject({
      artist: "Artist",
      title: "Title",
    });
    expect(parseArtistAndTitle("Plain Title")).toEqual({
      title: "Plain Title",
    });
  });

  it("cleanSoundCloudMetadata strips junk while preserving artist and version tags", () => {
    const meta1 = cleanSoundCloudMetadata(
      "Skrillex - Scary Monsters (VIP Flip) [FREE DL] (prod by Skrillex)",
      "DubstepNation",
    );
    expect(meta1.artist).toBe("Skrillex");
    expect(meta1.title).toBe("Scary Monsters (VIP Flip)");
    expect(meta1.searchQuery).toBe("Skrillex Scary Monsters (VIP Flip)");
    expect(Array.from(meta1.versionTags).sort()).toEqual(["flip", "vip"]);

    const meta2 = cleanSoundCloudMetadata("Doja Cat - Say So", "Doja Cat");
    expect(meta2.artist).toBe("Doja Cat");
    expect(meta2.title).toBe("Say So");
    expect(meta2.searchQuery).toBe("Doja Cat Say So");

    const meta3 = cleanSoundCloudMetadata(
      "Lil Peep - Star Shopping (Prod. Kryptik) [FREE DL] (Link in bio) *OG*",
      "Lil Peep",
    );
    expect(meta3.title).toBe("Star Shopping");
    expect(meta3.searchQuery).toBe("Lil Peep Star Shopping");
  });
});
