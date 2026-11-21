import { useEffect, useSyncExternalStore } from "react";
import { api, getAuthSession, toClientTrack } from "@/shared/api";
import { clientCatalog } from "@/shared/api/clientCatalog";
import {
  addLocalLike,
  getLocalLikes,
  removeLocalLike,
  subscribeLocalLikes,
} from "../local/likes";
import { notifyLibraryChanged } from "./usePlaylists";
import type { Track } from "@/shared/types";

type LikedData = { tracks: Track[]; total: number };
const EMPTY: LikedData = { tracks: [], total: 0 };
let cache: LikedData = EMPTY;
let loaded = false;
let fetchedFromServer = false;
let loadFailed = false;
let request: Promise<void> | null = null;
let reloadQueued = false;
const listeners = new Set<() => void>();
let view = { data: cache, isLoading: true, error: false };

const optimisticOverrides = new Map<string, boolean>();
const desiredLikes = new Map<string, boolean>();
const syncingLikes = new Set<string>();
const likeWaiters = new Map<
  string,
  Array<{ resolve: () => void; reject: (error: unknown) => void }>
>();
const likeSettledEpoch = new Map<string, number>();
let likeEpoch = 0;

function buildView(isLoading: boolean): {
  data: LikedData;
  isLoading: boolean;
  error: boolean;
} {
  const error = loadFailed;
  if (optimisticOverrides.size === 0) return { data: cache, isLoading, error };

  let tracks = cache.tracks.filter(
    (t) => optimisticOverrides.get(t.id) !== false,
  );
  for (const [id, liked] of optimisticOverrides) {
    if (liked && !tracks.some((t) => t.id === id)) {
      tracks = [
        {
          id,
          title: "",
          artists: "",
          artistId: undefined,
          coverUrl: "",
          durationMs: 0,
          playCount: 0,
        } as Track,
        ...tracks,
      ];
    }
  }
  return { data: { tracks, total: tracks.length }, isLoading, error };
}

function emit(isLoading = false) {
  view = buildView(isLoading);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot() {
  return view;
}

const SERVER_SNAPSHOT = { data: EMPTY, isLoading: true, error: false };

function load(force = false): Promise<void> {
  if (request) {
    if (force) reloadQueued = true;
    return request;
  }
  const session = getAuthSession();
  if (!session?.accessToken) {
    // No account in DowFlow: likes live on this device and stay after a
    // restart instead of being thrown away by a 401.
    const local = getLocalLikes();
    cache = { tracks: local, total: local.length };
    loaded = true;
    fetchedFromServer = false;
    loadFailed = false;
    emit(false);
    return Promise.resolve();
  }
  if (loaded && !force) return Promise.resolve();

  if (!loaded) emit(true);

  const startEpoch = likeEpoch;
  const owner = session.user?.id ?? null;
  request = (async () => {
    const tracks: Track[] = [];
    let cursor: string | undefined;
    do {
      const page = await api.listLikedTracks(100, cursor);
      tracks.push(
        ...page.items.map(({ track, likedAt }) => ({
          ...toClientTrack(track),
          addedAt: likedAt,
        })),
      );
      cursor = page.nextCursor ?? undefined;
    } while (cursor);
    if ((getAuthSession()?.user?.id ?? null) !== owner) return;
    cache = { tracks, total: tracks.length };
    loaded = true;
    fetchedFromServer = true;
    loadFailed = false;
    dropConfirmedOverrides(startEpoch);
  })()
    .catch(() => {
      if ((getAuthSession()?.user?.id ?? null) !== owner) return;
      if (!fetchedFromServer) cache = EMPTY;
      loaded = fetchedFromServer;
      loadFailed = true;
    })
    .finally(() => {
      request = null;
      emit(false);
      if (reloadQueued) {
        reloadQueued = false;
        void load(true);
      }
    });
  return request;
}

function dropConfirmedOverrides(startEpoch: number) {
  for (const id of optimisticOverrides.keys()) {
    if (syncingLikes.has(id)) continue;
    if ((likeSettledEpoch.get(id) ?? 0) > startEpoch) continue;
    optimisticOverrides.delete(id);
    likeSettledEpoch.delete(id);
  }
}

export function isTrackLikedNow(trackId: string): boolean {
  const override = optimisticOverrides.get(trackId);
  if (override !== undefined) return override;
  return cache.tracks.some((t) => t.id === trackId);
}

function settleLikeWaiters(trackId: string, error?: unknown) {
  const waiters = likeWaiters.get(trackId) ?? [];
  likeWaiters.delete(trackId);
  for (const waiter of waiters) {
    if (error === undefined) waiter.resolve();
    else waiter.reject(error);
  }
}

async function resolveLikeTrack(
  trackId: string,
  snapshot?: Track,
): Promise<Track | undefined> {
  if (snapshot) return snapshot;
  const cached = cache.tracks.find((track) => track.id === trackId);
  if (cached) return cached;
  const resolved = await clientCatalog.resolveSnapshot(trackId);
  return resolved ? toClientTrack(resolved) : undefined;
}

async function syncTrackLike(
  trackId: string,
  confirmed: boolean,
  trackSnapshot?: Track,
) {
  syncingLikes.add(trackId);
  let serverLiked = confirmed;
  let sent = false;
  let failure: unknown;
  try {
    const session = getAuthSession();
    if (!session?.accessToken) {
      for (;;) {
        const wanted = desiredLikes.get(trackId);
        if (wanted === undefined || wanted === serverLiked) break;
        sent = true;
        if (wanted) {
          const track = await resolveLikeTrack(trackId, trackSnapshot);
          if (!track) throw new Error("This track cannot be liked yet.");
          addLocalLike(track);
        } else {
          removeLocalLike(trackId);
        }
        serverLiked = wanted;
      }
    } else {
      for (;;) {
        const wanted = desiredLikes.get(trackId);
        if (wanted === undefined || wanted === serverLiked) break;
        sent = true;
        if (wanted) await api.likeTrack(trackId);
        else await api.unlikeTrack(trackId);
        serverLiked = wanted;
      }
    }
  } catch (error) {
    failure = error ?? new Error("like sync failed");
  }
  desiredLikes.delete(trackId);
  syncingLikes.delete(trackId);
  likeEpoch += 1;
  likeSettledEpoch.set(trackId, likeEpoch);
  optimisticOverrides.set(trackId, serverLiked);
  emit(false);
  settleLikeWaiters(trackId, failure);
  if (sent) notifyLibraryChanged();
}

export function setTrackLiked(
  trackId: string,
  liked: boolean,
  trackSnapshot?: Track,
): Promise<void> {
  const settled = new Promise<void>((resolve, reject) => {
    const waiters = likeWaiters.get(trackId) ?? [];
    waiters.push({ resolve, reject });
    likeWaiters.set(trackId, waiters);
  });
  const confirmed = isTrackLikedNow(trackId);
  desiredLikes.set(trackId, liked);
  optimisticOverrides.set(trackId, liked);
  emit(false);
  if (!syncingLikes.has(trackId))
    void syncTrackLike(trackId, confirmed, trackSnapshot);
  return settled;
}

export function toggleTrackLike(
  trackId: string,
  trackSnapshot?: Track,
): {
  liked: boolean;
  settled: Promise<void>;
} {
  const liked = !isTrackLikedNow(trackId);
  return { liked, settled: setTrackLiked(trackId, liked, trackSnapshot) };
}

if (typeof window !== "undefined") {
  subscribeLocalLikes(() => {
    if (getAuthSession()?.accessToken) return;
    const local = getLocalLikes();
    cache = { tracks: local, total: local.length };
    loaded = true;
    emit(false);
  });
}

export function reloadLikedTracks(): Promise<void> {
  return load(true);
}

export function applyOptimisticLike(trackId: string): () => void {
  const prev = optimisticOverrides.get(trackId);
  optimisticOverrides.set(trackId, true);
  emit(false);
  return () => {
    if (prev === undefined) optimisticOverrides.delete(trackId);
    else optimisticOverrides.set(trackId, prev);
    emit(false);
  };
}

export function applyOptimisticUnlike(trackId: string): () => void {
  const prev = optimisticOverrides.get(trackId);
  optimisticOverrides.set(trackId, false);
  emit(false);
  return () => {
    if (prev === undefined) optimisticOverrides.delete(trackId);
    else optimisticOverrides.set(trackId, prev);
    emit(false);
  };
}

if (typeof window !== "undefined") {
  const handleRefresh = () => {
    const session = getAuthSession();
    if (!session?.accessToken) {
      const local = getLocalLikes();
      cache = { tracks: local, total: local.length };
      loaded = true;
      fetchedFromServer = false;
      loadFailed = false;
      optimisticOverrides.clear();
      likeSettledEpoch.clear();
      emit(false);
    } else {
      void load(true);
    }
  };
  window.addEventListener("library:changed", handleRefresh);
  window.addEventListener("auth:changed", handleRefresh);
}

export const loadLikedTracks = load;
export const subscribeLikedTracks = subscribe;

export function likedTracksSnapshot(): {
  tracks: Track[];
  fromServer: boolean;
} {
  return { tracks: view.data.tracks, fromServer: fetchedFromServer };
}

export function useLikedTracks(_params?: { limit?: number; offset?: number }) {
  const state = useSyncExternalStore(
    subscribe,
    snapshot,
    () => SERVER_SNAPSHOT,
  );
  useEffect(() => {
    void load();
  }, []);
  return state;
}

export function useLikedTrackCount() {
  const { data, isLoading } = useLikedTracks();
  return { data: data.total, isLoading };
}
