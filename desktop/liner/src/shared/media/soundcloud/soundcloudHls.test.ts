import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadHlsAudio, parseHlsPlaylist } from "./soundcloudHls";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseHlsPlaylist", () => {
  it("resolves relative segment urls against the playlist url", () => {
    expect(
      parseHlsPlaylist(
        "#EXTM3U\n#EXTINF:10,\nseg0.mp3\n#EXTINF:10,\n/abs/seg1.mp3",
        "https://host/a/playlist.m3u8",
      ),
    ).toEqual({
      segments: ["https://host/a/seg0.mp3", "https://host/abs/seg1.mp3"],
    });
  });

  it("follows master playlists to their first variant", () => {
    expect(
      parseHlsPlaylist(
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nlow/index.m3u8",
        "https://host/master.m3u8",
      ),
    ).toEqual({
      variant: "https://host/low/index.m3u8",
    });
  });

  it("rejects encrypted and malformed playlists", () => {
    expect(() =>
      parseHlsPlaylist(
        '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k"\nseg.ts',
        "https://host/p.m3u8",
      ),
    ).toThrow("encrypted");
    expect(() => parseHlsPlaylist("<html>", "https://host/p.m3u8")).toThrow(
      "Not an HLS playlist",
    );
  });
});

describe("downloadHlsAudio", () => {
  it("downloads segments with bounded concurrency and keeps their order", async () => {
    const segmentCount = 12;
    let active = 0;
    let peak = 0;
    const playlist = [
      "#EXTM3U",
      ...Array.from(
        { length: segmentCount },
        (_, index) => `#EXTINF:10,\nseg${index}.mp3`,
      ),
    ].join("\n");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith(".m3u8")) return new Response(playlist);
        const index = Number(/seg(\d+)\.mp3$/.exec(url)?.[1]);
        active += 1;
        peak = Math.max(peak, active);
        await new Promise((resolve) =>
          setTimeout(resolve, (segmentCount - index) % 4),
        );
        active -= 1;
        return new Response(new Uint8Array([index]));
      }),
    );

    const bytes = await downloadHlsAudio("https://host/playlist.m3u8", {
      concurrency: 3,
    });

    expect([...bytes]).toEqual(
      Array.from({ length: segmentCount }, (_, index) => index),
    );
    expect(peak).toBeLessThanOrEqual(3);
  });

  it("retries a failed segment once before giving up", async () => {
    let attempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith(".m3u8"))
          return new Response("#EXTM3U\n#EXTINF:10,\nseg.mp3");
        attempts += 1;
        return attempts === 1
          ? new Response("", { status: 503 })
          : new Response(new Uint8Array([9]));
      }),
    );

    await expect(downloadHlsAudio("https://host/p.m3u8")).resolves.toEqual(
      new Uint8Array([9]),
    );
    expect(attempts).toBe(2);
  });
});
