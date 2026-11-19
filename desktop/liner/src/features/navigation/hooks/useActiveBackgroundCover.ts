import {
  isCoverReady,
  useCoverCrossOrigin,
  useCoverReady,
  useCoverSrc,
} from "@/features/covers";
import { usePageBackdropStore, type PageBackdropOptions } from "@/shared/lib";

export type BackgroundCoverState =
  | { kind: "none" }
  | { kind: "pending" }
  | { kind: "ready"; src: string; crossOrigin?: "anonymous" };

export interface ActiveBackgroundCoverResult {
  cover: BackgroundCoverState;
  pageBackdropOptions?: PageBackdropOptions;
}

export function useActiveBackgroundCover(): ActiveBackgroundCoverResult {
  const pageCoverUrl = usePageBackdropStore((s) => s.coverUrl);
  const pageBackdropOptions = usePageBackdropStore((s) => s.options);
  const effectiveCoverSrc = useCoverSrc(pageCoverUrl);
  const settled = useCoverReady(pageCoverUrl);
  const crossOrigin = useCoverCrossOrigin(pageCoverUrl);

  let cover: BackgroundCoverState;
  if (!pageCoverUrl) cover = { kind: "none" };
  else if (!settled) cover = { kind: "pending" };
  else if (isCoverReady(pageCoverUrl) && effectiveCoverSrc) {
    cover = { kind: "ready", src: effectiveCoverSrc, crossOrigin };
  } else cover = { kind: "none" };

  return { cover, pageBackdropOptions };
}
