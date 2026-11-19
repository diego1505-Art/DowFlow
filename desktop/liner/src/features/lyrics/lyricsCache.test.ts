import { describe, it, expect, beforeEach, beforeAll } from "vitest";
import {
  lyricsCache,
  shouldCacheLyricsCandidate,
  isProvisionalLyricsCandidate,
} from "./index";
import type { LyricsCandidate } from "@/shared/contracts/lyrics";

function makeCandidate(
  provider: string,
  syncLevel: "plain" | "line_level" | "word_level" | "syllable_level",
  qualityTotal = 80,
  content = "[00:01.00] test lyrics",
): LyricsCandidate {
  return {
    provider,
    contentKind:
      syncLevel === "word_level" || syncLevel === "syllable_level"
        ? "word_synced"
        : syncLevel === "line_level"
          ? "line_synced"
          : "plain",
    syncLevel,
    quality: {
      total: qualityTotal,
      match: 20,
      content: 30,
      sync: 30,
      source: 0,
      reasons: [],
    },
    lyrics: {
      format: "lrc",
      content,
    },
  };
}

describe("lyricsCache advanced caching logic", () => {
  const store = new Map<string, string>();
  const localStorageMock = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => store.set(key, value),
    removeItem: (key: string) => store.delete(key),
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  };

  beforeAll(() => {
    Object.defineProperty(globalThis, "localStorage", {
      value: localStorageMock,
      writable: true,
      configurable: true,
    });
    if (typeof window !== "undefined") {
      Object.defineProperty(window, "localStorage", {
        value: localStorageMock,
        writable: true,
        configurable: true,
      });
    }
  });

  beforeEach(() => {
    localStorageMock.clear();
    lyricsCache.clear();
  });

  describe("provider word-level validation (shouldCacheLyricsCandidate)", () => {
    it("allows word_level and syllable_level for cadence, polaris, polaris mono", () => {
      expect(
        shouldCacheLyricsCandidate(makeCandidate("cadence", "word_level")),
      ).toBe(true);
      expect(
        shouldCacheLyricsCandidate(makeCandidate("Cadence", "syllable_level")),
      ).toBe(true);
      expect(
        shouldCacheLyricsCandidate(makeCandidate("polaris", "word_level")),
      ).toBe(true);
      expect(
        shouldCacheLyricsCandidate(makeCandidate("Polaris Mono", "word_level")),
      ).toBe(true);
      expect(
        shouldCacheLyricsCandidate(
          makeCandidate("polaris_mono", "syllable_level"),
        ),
      ).toBe(true);
    });

    it("keeps plain and line_level from cadence, polaris, polaris mono so they work offline", () => {
      for (const candidate of [
        makeCandidate("cadence", "line_level"),
        makeCandidate("cadence", "plain"),
        makeCandidate("Polaris", "line_level"),
        makeCandidate("polaris mono", "line_level"),
        makeCandidate("polaris-mono", "plain"),
      ]) {
        expect(shouldCacheLyricsCandidate(candidate)).toBe(true);
        expect(isProvisionalLyricsCandidate(candidate)).toBe(true);
      }
      expect(
        isProvisionalLyricsCandidate(makeCandidate("cadence", "word_level")),
      ).toBe(false);
      expect(
        isProvisionalLyricsCandidate(makeCandidate("lrclib", "line_level")),
      ).toBe(false);
    });

    it("allows any sync level for other providers (e.g. lrclib, kugou, musixmatch, netease)", () => {
      expect(
        shouldCacheLyricsCandidate(makeCandidate("lrclib", "line_level")),
      ).toBe(true);
      expect(shouldCacheLyricsCandidate(makeCandidate("lrclib", "plain"))).toBe(
        true,
      );
      expect(
        shouldCacheLyricsCandidate(makeCandidate("kugou", "line_level")),
      ).toBe(true);
      expect(
        shouldCacheLyricsCandidate(makeCandidate("musixmatch", "plain")),
      ).toBe(true);
    });

    it("rejects empty/invalid candidates", () => {
      expect(shouldCacheLyricsCandidate(null)).toBe(false);
      expect(shouldCacheLyricsCandidate(undefined)).toBe(false);
      expect(
        shouldCacheLyricsCandidate({
          ...makeCandidate("lrclib", "line_level"),
          lyrics: { format: "lrc", content: "" },
        }),
      ).toBe(false);
    });
  });

  describe("per-provider caching", () => {
    it("caches multiple providers individually for the same track", () => {
      const lrclibCandidate = makeCandidate(
        "lrclib",
        "line_level",
        70,
        "[00:01.00] lrclib line",
      );
      const kugouCandidate = makeCandidate(
        "kugou",
        "word_level",
        90,
        "[00:01.00] kugou word",
      );

      lyricsCache.setProvider("track_1", lrclibCandidate);
      expect(lyricsCache.has("track_1")).toBe(true);
      expect(lyricsCache.has("track_1", "lrclib")).toBe(true);
      expect(lyricsCache.has("track_1", "kugou")).toBe(false);

      lyricsCache.setProvider("track_1", kugouCandidate);
      expect(lyricsCache.has("track_1", "lrclib")).toBe(true);
      expect(lyricsCache.has("track_1", "kugou")).toBe(true);

      const cachedLrclib = lyricsCache.getProvider("track_1", "lrclib");
      const cachedKugou = lyricsCache.getProvider("track_1", "kugou");
      expect(cachedLrclib?.lyrics.content).toBe("[00:01.00] lrclib line");
      expect(cachedKugou?.lyrics.content).toBe("[00:01.00] kugou word");

      const item = lyricsCache.get("track_1");
      expect(item).not.toBeNull();
      // kugou is word-level so it should be chosen as best candidate
      expect(item?.candidate.provider).toBe("kugou");
      expect(item?.availableProviders?.length).toBe(2);
    });

    it("caches provisional lyrics and upgrades them when word-level arrives", () => {
      const linePolaris = makeCandidate("Polaris Mono", "line_level", 85);
      lyricsCache.setProvider("track_2", linePolaris);
      expect(lyricsCache.has("track_2", "Polaris Mono")).toBe(true);
      expect(lyricsCache.get("track_2")?.candidate.syncLevel).toBe(
        "line_level",
      );

      const wordPolaris = makeCandidate("Polaris Mono", "word_level", 95);
      lyricsCache.setProvider("track_2", wordPolaris);
      expect(lyricsCache.get("track_2")?.candidate.syncLevel).toBe(
        "word_level",
      );

      lyricsCache.setProvider("track_2", linePolaris);
      expect(
        lyricsCache.getProvider("track_2", "Polaris Mono")?.syncLevel,
      ).toBe("word_level");
    });

    it("preserves individual provider options when set() with availableProviders is called", () => {
      const lrclib = makeCandidate("lrclib", "line_level", 65);
      const cadenceWord = makeCandidate("cadence", "word_level", 92);
      const cadenceLine = makeCandidate("cadence", "line_level", 60);

      lyricsCache.set("track_3", lrclib, [
        {
          provider: "lrclib",
          syncLevel: "line_level",
          quality: 65,
          candidate: lrclib,
        },
        {
          provider: "cadence",
          syncLevel: "word_level",
          quality: 92,
          candidate: cadenceWord,
        },
        {
          provider: "cadence_line",
          syncLevel: "line_level",
          quality: 60,
          candidate: cadenceLine,
        },
      ]);

      expect(lyricsCache.has("track_3", "lrclib")).toBe(true);
      expect(lyricsCache.has("track_3", "cadence")).toBe(true);
      expect(lyricsCache.getProvider("track_3", "cadence")?.syncLevel).toBe(
        "word_level",
      );
    });
  });
});
