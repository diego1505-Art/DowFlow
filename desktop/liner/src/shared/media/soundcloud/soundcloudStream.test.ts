import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  rememberSoundCloudClientId,
  resetSoundCloudClientIdCache,
} from "./soundcloudClientId";
import { resolveSoundCloudStream } from "./soundcloudStream";

type Route = (url: URL) => Response | undefined;

const STALE_ID = "s".repeat(32);
const FRESH_ID = "f".repeat(32);
const MEDIA = "https://api-v2.soundcloud.com/media/soundcloud:tracks:7";
const SIGNED_MP3 =
  "https://cf-media.sndcdn.com/abc.mp3?Expires=1893456000&Signature=x";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function trackBody(
  transcodings: Array<{ preset: string; protocol: string; mime: string }>,
  extra: Record<string, unknown> = {},
) {
  return {
    id: 7,
    policy: "ALLOW",
    track_authorization: "auth-token",
    media: {
      transcodings: transcodings.map((item) => ({
        url: `${MEDIA}/${item.preset}/${item.protocol}`,
        preset: item.preset,
        format: { protocol: item.protocol, mime_type: item.mime },
      })),
    },
    ...extra,
  };
}

function installFetch(routes: Route[]) {
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
    );
    for (const route of routes) {
      const response = route(url);
      if (response) return response;
    }
    return new Response("not found", { status: 404 });
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

beforeEach(() => {
  resetSoundCloudClientIdCache();
  rememberSoundCloudClientId(STALE_ID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetSoundCloudClientIdCache();
});

const homepage: Route = (url) =>
  url.hostname === "soundcloud.com"
    ? new Response(
        '<script src="https://a-v2.sndcdn.com/assets/app.js"></script>',
      )
    : undefined;
const appScript: Route = (url) =>
  url.hostname === "a-v2.sndcdn.com"
    ? new Response(`x={client_id:"${FRESH_ID}"}`)
    : undefined;

describe("resolveSoundCloudStream", () => {
  it("rediscovers the client_id once after a 401 and plays the progressive mp3", async () => {
    const fetchSpy = installFetch([
      homepage,
      appScript,
      (url) =>
        url.searchParams.get("client_id") === STALE_ID
          ? new Response("", { status: 401 })
          : undefined,
      (url) =>
        url.pathname === "/tracks/7"
          ? json(
              trackBody([
                { preset: "aac_160k", protocol: "hls", mime: "audio/mp4" },
                {
                  preset: "mp3_1_0",
                  protocol: "progressive",
                  mime: "audio/mpeg",
                },
              ]),
            )
          : undefined,
      (url) =>
        url.pathname.endsWith("/progressive") &&
        url.searchParams.get("track_authorization") === "auth-token"
          ? json({ url: SIGNED_MP3 })
          : undefined,
    ]);

    const stream = await resolveSoundCloudStream("sc:7");

    expect(stream).toEqual({
      url: SIGNED_MP3,
      mimeType: "audio/mpeg",
      codec: "mp3",
      bitrate: 128_000,
      expiresAt: "2030-01-01T00:00:00.000Z",
    });
    const lookups = fetchSpy.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("/tracks/7"));
    expect(lookups).toHaveLength(2);
    expect(lookups[1]).toContain(`client_id=${FRESH_ID}`);
  });

  it("joins the hls init segment and media segments in order into one blob", async () => {
    rememberSoundCloudClientId(FRESH_ID);
    const playlist = [
      "#EXTM3U",
      '#EXT-X-MAP:URI="init.mp4"',
      "#EXTINF:10,",
      "seg0.m4s",
      "#EXTINF:10,",
      "seg1.m4s",
      "#EXTINF:3,",
      "seg2.m4s",
      "#EXT-X-ENDLIST",
    ].join("\n");
    const bytes: Record<string, number[]> = {
      "init.mp4": [1, 2],
      "seg0.m4s": [3],
      "seg1.m4s": [4, 5],
      "seg2.m4s": [6],
    };
    installFetch([
      (url) =>
        url.pathname === "/tracks/7"
          ? json(
              trackBody([
                {
                  preset: "aac_160k",
                  protocol: "hls",
                  mime: 'audio/mp4; codecs="mp4a.40.2"',
                },
              ]),
            )
          : undefined,
      (url) =>
        url.pathname.endsWith("/hls")
          ? json({
              url: "https://playback.media-streaming.soundcloud.cloud/x/playlist.m3u8?expires=1",
            })
          : undefined,
      (url) =>
        url.pathname.endsWith("playlist.m3u8")
          ? new Response(playlist)
          : undefined,
      (url) => {
        const name = url.pathname.split("/").pop() ?? "";
        return bytes[name]
          ? new Response(new Uint8Array(bytes[name]))
          : undefined;
      },
    ]);

    const stream = await resolveSoundCloudStream("sc:7");

    expect(stream).toMatchObject({
      codec: "aac",
      mimeType: "audio/mp4",
      bitrate: 160_000,
      expiresAt: null,
      contentLength: 6,
    });
    if (!stream.blob) throw new Error("expected a buffered stream");
    expect([...new Uint8Array(await stream.blob.arrayBuffer())]).toEqual([
      1, 2, 3, 4, 5, 6,
    ]);
  });

  it("moves on to hls when the progressive url cannot be signed", async () => {
    rememberSoundCloudClientId(FRESH_ID);
    installFetch([
      (url) =>
        url.pathname === "/tracks/7"
          ? json(
              trackBody([
                { preset: "mp3_1_0", protocol: "hls", mime: "audio/mpeg" },
                {
                  preset: "mp3_1_0",
                  protocol: "progressive",
                  mime: "audio/mpeg",
                },
              ]),
            )
          : undefined,
      (url) =>
        url.pathname.endsWith("/progressive")
          ? new Response("", { status: 500 })
          : undefined,
      (url) =>
        url.pathname.endsWith("/hls")
          ? json({ url: "https://cf-hls-media.sndcdn.com/playlist/a.m3u8" })
          : undefined,
      (url) =>
        url.pathname.endsWith("a.m3u8")
          ? new Response(
              "#EXTM3U\n#EXTINF:10,\nhttps://cf-hls-media.sndcdn.com/media/0/a.mp3",
            )
          : undefined,
      (url) =>
        url.pathname.endsWith("a.mp3")
          ? new Response(new Uint8Array([0xff, 0xfb, 0x90]))
          : undefined,
    ]);

    await expect(resolveSoundCloudStream("sc:7")).resolves.toMatchObject({
      codec: "mp3",
      mimeType: "audio/mpeg",
      contentLength: 3,
    });
  });

  it("reports removed and preview-only tracks as unavailable", async () => {
    rememberSoundCloudClientId(FRESH_ID);
    installFetch([
      (url) =>
        url.pathname === "/tracks/8"
          ? json(
              trackBody(
                [
                  {
                    preset: "mp3_1_0",
                    protocol: "progressive",
                    mime: "audio/mpeg",
                  },
                ],
                { policy: "SNIP" },
              ),
            )
          : undefined,
    ]);

    await expect(resolveSoundCloudStream("sc:7")).rejects.toMatchObject({
      reason: "not_found",
    });
    await expect(resolveSoundCloudStream("sc:8")).rejects.toMatchObject({
      reason: "preview_only",
    });
  });
});
