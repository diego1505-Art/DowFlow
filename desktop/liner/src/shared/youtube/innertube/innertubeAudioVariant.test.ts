import { describe, expect, it } from "vitest";
import { audioVariantOf } from "./innertubeAudioVariant";

const row = (renderer: Record<string, unknown>) => ({
  musicResponsiveListItemRenderer: {
    playlistItemData: { videoId: "abcdefghijk" },
    ...renderer,
  },
});

describe("audioVariantOf", () => {
  it("marks greyed out album rows as premium only", () => {
    expect(
      audioVariantOf(
        row({
          musicItemRendererDisplayPolicy:
            "MUSIC_ITEM_RENDERER_DISPLAY_POLICY_GREY_OUT",
        }),
      ),
    ).toBe("premium-only");
  });

  it("marks official music videos", () => {
    const endpoint = {
      watchEndpoint: {
        videoId: "abcdefghijk",
        watchEndpointMusicSupportedConfigs: {
          watchEndpointMusicConfig: { musicVideoType: "MUSIC_VIDEO_TYPE_OMV" },
        },
      },
    };
    expect(audioVariantOf(row({ navigationEndpoint: endpoint }))).toBe(
      "music-video",
    );
  });

  it("leaves songs alone", () => {
    expect(audioVariantOf(row({}))).toBeUndefined();
  });
});
