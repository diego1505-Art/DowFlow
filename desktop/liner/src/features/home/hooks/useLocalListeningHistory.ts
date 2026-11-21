import { useEffect, useMemo, useSyncExternalStore } from "react";
import { useCachedTracksStore } from "@/features/library/cached/store/cachedTracksStore";
import {
  getListeningHistory,
  subscribeListeningHistory,
} from "@/features/player/lib/listeningHistory";
import type { PopularItem } from "./usePopularTracks";

/**
 * Tracks already listened to on this device: explicit plays first, then the
 * audio cache left by earlier playback (the cache survives restarts and
 * already contains tracks played before this row existed).
 */
export function useLocalListeningHistory(limit = 20): PopularItem[] {
  const entries = useSyncExternalStore(
    subscribeListeningHistory,
    getListeningHistory,
    getListeningHistory,
  );
  const cached = useCachedTracksStore((state) => state.items);
  const loadCached = useCachedTracksStore((state) => state.load);

  useEffect(() => {
    void loadCached();
  }, [loadCached]);

  return useMemo(() => {
    const seen = new Set<string>();
    const items: PopularItem[] = [];
    for (const entry of entries) {
      if (seen.has(entry.track.id)) continue;
      seen.add(entry.track.id);
      items.push({ type: "track", item: entry.track, playCount: 1 });
    }
    for (const cachedTrack of cached) {
      if (seen.has(cachedTrack.track.id)) continue;
      seen.add(cachedTrack.track.id);
      items.push({ type: "track", item: cachedTrack.track, playCount: 1 });
    }
    return items.slice(0, limit);
  }, [entries, cached, limit]);
}
