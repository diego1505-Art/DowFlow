import { describe, expect, it } from "vitest";
import { toVideoId } from "@/shared/youtube/innertube/innertubeAudio";
import { toSoundCloudTrackId } from "@/shared/media/soundcloud/soundcloudTrack";
import {
  isLocalTrackId,
  localRecordToTrack,
  localTrackAudioUrl,
} from "./index";

const record = {
  id: "0123456789abcdef0123",
  title: "Roygbiv",
  artist: "Boards of Canada",
  durationMs: 151000,
  fileName: "roygbiv.mp3",
  audioFile: "0123456789abcdef0123.mp3",
  mimeType: "audio/mpeg",
  coverFile: "0123456789abcdef0123.jpg",
  byteSize: 10,
  addedAt: 1,
};

describe("local tracks", () => {
  it("map to tracks with stable liner-local urls", () => {
    const track = localRecordToTrack(record);
    expect(track).toMatchObject({
      id: "local:0123456789abcdef0123",
      artists: "Boards of Canada",
      coverUrl: "liner-local://cover/0123456789abcdef0123",
    });
    expect(localTrackAudioUrl(track.id)).toBe(
      "liner-local://audio/0123456789abcdef0123",
    );
  });

  it("are never mistaken for youtube or soundcloud ids", () => {
    const { id } = localRecordToTrack(record);
    expect(isLocalTrackId(id)).toBe(true);
    expect(toVideoId(id)).toBeNull();
    expect(toSoundCloudTrackId(id)).toBeNull();
    expect(isLocalTrackId("dQw4w9WgXcQ")).toBe(false);
  });

  it("leave the cover empty when the file has no artwork", () => {
    const { coverFile, ...withoutCover } = record;
    expect(coverFile).toBeDefined();
    expect(localRecordToTrack(withoutCover).coverUrl).toBe("");
  });
});
