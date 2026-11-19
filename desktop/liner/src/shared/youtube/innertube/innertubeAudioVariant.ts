import type { TrackAudioVariant } from "@/shared/contracts";
import { asRecord } from "@/shared/utils/json";

const GREYED_OUT = "MUSIC_ITEM_RENDERER_DISPLAY_POLICY_GREY_OUT";

export function audioVariantOf(raw: unknown): TrackAudioVariant | undefined {
  const item = asRecord(raw);
  const renderer = asRecord(item?.musicResponsiveListItemRenderer) ?? item;
  if (!renderer) return undefined;
  if (renderer.musicItemRendererDisplayPolicy === GREYED_OUT)
    return "premium-only";
  if (JSON.stringify(renderer).includes('"MUSIC_VIDEO_TYPE_OMV"'))
    return "music-video";
  return undefined;
}
