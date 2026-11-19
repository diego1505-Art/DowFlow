import { describe, expect, it } from "vitest";
import {
  parseSoundCloudTrack,
  toSoundCloudTrackId,
  type SoundCloudTrackInfo,
} from "./soundcloudTrack";
import {
  playableTranscodings,
  SoundCloudUnavailableError,
  transcodingFormat,
} from "./soundcloudTranscodings";

function transcoding(
  preset: string,
  protocol: string,
  mime: string,
  snipped = false,
) {
  return {
    url: `https://api-v2.soundcloud.com/media/${preset}/${protocol}`,
    preset,
    snipped,
    format: { protocol, mime_type: mime },
  };
}

function track(overrides: Record<string, unknown> = {}): SoundCloudTrackInfo {
  const parsed = parseSoundCloudTrack({
    id: 1,
    policy: "ALLOW",
    duration: 173_000,
    full_duration: 173_000,
    media: {
      transcodings: [
        transcoding("abr_sq", "hls", "audio/mpegurl"),
        transcoding("aac_160k", "hls", 'audio/mp4; codecs="mp4a.40.2"'),
        transcoding("opus_0_0", "hls", 'audio/ogg; codecs="opus"'),
        transcoding("mp3_1_0", "hls", "audio/mpeg"),
        transcoding("mp3_0_0", "ctr-encrypted-hls", "audio/mpeg"),
        transcoding("mp3_1_0", "progressive", "audio/mpeg"),
      ],
    },
    ...overrides,
  });
  if (!parsed) throw new Error("fixture did not parse");
  return parsed;
}

function reason(run: () => unknown): string | undefined {
  try {
    run();
    return undefined;
  } catch (error) {
    return error instanceof SoundCloudUnavailableError
      ? error.reason
      : String(error);
  }
}

describe("playableTranscodings", () => {
  it("prefers progressive mp3, then mpeg hls, then other hls, and skips playlists and encrypted streams", () => {
    expect(
      playableTranscodings(track()).map(
        (item) => `${item.preset}/${item.protocol}`,
      ),
    ).toEqual([
      "mp3_1_0/progressive",
      "mp3_1_0/hls",
      "aac_160k/hls",
      "opus_0_0/hls",
    ]);
  });

  it("treats blocked tracks as unavailable", () => {
    expect(reason(() => playableTranscodings(track({ policy: "BLOCK" })))).toBe(
      "blocked",
    );
  });

  it("treats SNIP previews as unavailable instead of playing 30 seconds", () => {
    expect(reason(() => playableTranscodings(track({ policy: "SNIP" })))).toBe(
      "preview_only",
    );
  });

  it("treats snipped transcodings and preview durations as unavailable", () => {
    const snippedOnly = {
      transcodings: [transcoding("mp3_1_0", "progressive", "audio/mpeg", true)],
    };
    expect(
      reason(() => playableTranscodings(track({ media: snippedOnly }))),
    ).toBe("preview_only");
    expect(
      reason(() =>
        playableTranscodings(
          track({ duration: 30_000, full_duration: 200_000 }),
        ),
      ),
    ).toBe("preview_only");
  });

  it("drops individual snipped transcodings and reports when nothing playable is left", () => {
    const media = {
      transcodings: [
        transcoding("abr_sq", "hls", "audio/mpegurl"),
        transcoding("mp3_1_0", "hls", "audio/mpeg", true),
      ],
    };
    expect(reason(() => playableTranscodings(track({ media })))).toBe(
      "no_playable_transcoding",
    );
    expect(
      reason(() => playableTranscodings(track({ streamable: false }))),
    ).toBe("not_streamable");
  });
});

describe("soundcloud track helpers", () => {
  it("maps transcodings to codec, mime type and bitrate", () => {
    const [progressive, , aac, opus] = playableTranscodings(track());
    expect(transcodingFormat(progressive)).toEqual({
      codec: "mp3",
      mimeType: "audio/mpeg",
      bitrate: 128_000,
    });
    expect(transcodingFormat(aac)).toEqual({
      codec: "aac",
      mimeType: "audio/mp4",
      bitrate: 160_000,
    });
    expect(transcodingFormat(opus).codec).toBe("opus");
  });

  it("recognises every soundcloud track id shape", () => {
    expect(toSoundCloudTrackId("sc:1099045843")).toBe("1099045843");
    expect(toSoundCloudTrackId("soundcloud:tracks:12")).toBe("12");
    expect(toSoundCloudTrackId("2018898144")).toBe("2018898144");
    expect(toSoundCloudTrackId("dQw4w9WgXcQ")).toBeNull();
    expect(toSoundCloudTrackId("sc_user_5")).toBeNull();
  });
});
