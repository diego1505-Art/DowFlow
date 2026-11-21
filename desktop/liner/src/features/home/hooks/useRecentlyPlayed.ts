import { useMemo } from "react";
import { api, toClientTrack } from "@/shared/api";
import type { PopularItem } from "./usePopularTracks";
import { loadWithRetry, useSessionOwner } from "./sessionAwareLoad";
import { useLocalListeningHistory } from "./useLocalListeningHistory";
import { freshFor, useCachedResource } from "@/shared/cache/useCachedResource";

export const recentlyPlayedKeys = {
  all: ["recently_played"] as const,
};

const RECENT_POLICY = { isFresh: freshFor(60_000), revalidateOnFocus: true };

async function loadRecentlyPlayed(limit: number): Promise<PopularItem[]> {
  const fetchLimit = Math.min(100, Math.max(limit * 3, 60));
  const res = await loadWithRetry(
    () => api.getHistory(undefined, fetchLimit),
    () => true,
  );
  const seen = new Set<string>();
  const items: PopularItem[] = [];
  for (const entry of res.items || []) {
    if (!entry.track?.id) continue;

    const isAlbum = entry.context?.type === "album";
    const albumId = isAlbum
      ? entry.context?.id || entry.track.album?.id
      : undefined;

    if (albumId) {
      const albumKey = `album:${albumId}`;
      if (seen.has(albumKey)) continue;
      seen.add(albumKey);
      seen.add(`track:${entry.track.id}`);

      const clientTrack = toClientTrack(entry.track);
      items.push({
        type: "album",
        item: {
          id: albumId,
          title: entry.track.album?.title || clientTrack.title,
          artist: clientTrack.artists,
          coverUrl: clientTrack.coverUrl,
          totalTracks: 0,
          albumType: "album",
        },
        playCount: 1,
      });
    } else {
      const trackKey = `track:${entry.track.id}`;
      if (seen.has(trackKey)) continue;
      seen.add(trackKey);

      items.push({
        type: "track",
        item: toClientTrack(entry.track),
        playCount: 1,
      });
    }

    if (items.length >= limit) {
      break;
    }
  }
  return items;
}

export function useRecentlyPlayed(limit = 20) {
  const owner = useSessionOwner();
  // Signed-out users have no server-side history, and a fresh account can be
  // empty: merge the tracks played on this device instead of hiding the
  // "jump back in" row. Local plays come first so a track started a second
  // ago shows up before the server-side history catches up.
  const localItems = useLocalListeningHistory(limit);
  const { data, isLoading } = useCachedResource(
    `home:recent:${owner}:${limit}`,
    () => loadRecentlyPlayed(limit),
    RECENT_POLICY,
  );
  const items = useMemo(() => {
    const seen = new Set<string>();
    const merged: PopularItem[] = [];
    for (const item of [...localItems, ...(data ?? [])]) {
      const key =
        item.type === "track"
          ? `track:${item.item.id}`
          : `${item.type}:${item.item.id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(item);
      if (merged.length >= limit) break;
    }
    return merged;
  }, [localItems, data, limit]);
  return { data: items, isLoading };
}
