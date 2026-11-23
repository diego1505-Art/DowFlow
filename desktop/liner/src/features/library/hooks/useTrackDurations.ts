import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import type { Track } from "@/shared/types";
import {
  getDurationVersion,
  knownDurationMs,
  requestDurations,
  subscribeDurations,
} from "../local/lib/trackDurations";

/**
 * Length of every track of a playlist, including the ones it stored with
 * `durationMs: 0`: those are resolved from the catalog and remembered, so the
 * playlist total stops reading "0 min 0 s".
 */
export function useTrackDurations(
  tracks: readonly Track[],
): (id: string) => number {
  useSyncExternalStore(
    subscribeDurations,
    getDurationVersion,
    getDurationVersion,
  );

  const missingKey = useMemo(
    () =>
      tracks
        .filter((track) => !((track.durationMs ?? 0) > 0))
        .map((track) => track.id)
        .join("|"),
    [tracks],
  );

  useEffect(() => {
    if (missingKey) requestDurations(missingKey.split("|"));
  }, [missingKey]);

  return useCallback((id: string) => knownDurationMs(id) ?? 0, []);
}
