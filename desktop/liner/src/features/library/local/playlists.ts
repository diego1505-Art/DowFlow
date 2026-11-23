import type { Track } from "@/shared/types";

const STORAGE_KEY = "liner_local_playlists_v1";
const CHANGE_EVENT = "liner:local-playlists-changed";
export const LOCAL_PLAYLIST_PREFIX = "local-playlist:";
const LOCAL_ITEM_PREFIX = "local-item:";

export interface LocalPlaylist {
  id: string;
  title: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
  revision: number;
  tracks: Track[];
}

export interface LocalPlaylistSummary {
  id: string;
  title: string;
  description?: string;
  trackCount: number;
  coverUrl: string;
  coverUrls: string[];
  updatedAt: string;
  createdAt: string;
  revision: number;
}

function newId(prefix: string): string {
  const random =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}${random}`;
}

export function isLocalPlaylistId(id: string | null | undefined): boolean {
  return typeof id === "string" && id.startsWith(LOCAL_PLAYLIST_PREFIX);
}

function isTrack(value: unknown): value is Track {
  if (!value || typeof value !== "object") return false;
  const track = value as Partial<Track>;
  return (
    typeof track.id === "string" &&
    track.id.length > 0 &&
    typeof track.title === "string" &&
    typeof track.artists === "string"
  );
}

function isPlaylist(value: unknown): value is LocalPlaylist {
  if (!value || typeof value !== "object") return false;
  const playlist = value as Partial<LocalPlaylist>;
  return (
    isLocalPlaylistId(playlist.id) &&
    typeof playlist.title === "string" &&
    typeof playlist.createdAt === "string" &&
    typeof playlist.updatedAt === "string" &&
    typeof playlist.revision === "number" &&
    Array.isArray(playlist.tracks) &&
    playlist.tracks.every(isTrack)
  );
}

function read(): LocalPlaylist[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed: unknown = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) ?? "[]",
    );
    return Array.isArray(parsed) ? parsed.filter(isPlaylist) : [];
  } catch {
    return [];
  }
}

function covers(tracks: Track[]): string[] {
  return tracks
    .map((track) => track.coverUrl)
    .filter((url, index, list) => Boolean(url) && list.indexOf(url) === index)
    .slice(0, 4);
}

function summaries(playlists: LocalPlaylist[]): LocalPlaylistSummary[] {
  return playlists.map((playlist) => {
    const coverUrls = covers(playlist.tracks);
    return {
      id: playlist.id,
      title: playlist.title,
      description: playlist.description,
      trackCount: playlist.tracks.length,
      coverUrl: coverUrls[0] ?? "",
      coverUrls,
      updatedAt: playlist.updatedAt,
      createdAt: playlist.createdAt,
      revision: playlist.revision,
    };
  });
}

let playlists: LocalPlaylist[] = read();
let summariesCache = summaries(playlists);
const listeners = new Set<() => void>();

function update(next: LocalPlaylist[]): void {
  playlists = next;
  summariesCache = summaries(playlists);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(playlists));
    } catch {
      // Keep the in-memory playlists when storage is unavailable.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
    window.dispatchEvent(new Event("library:changed"));
  }
  listeners.forEach((listener) => listener());
}

/** Stable until a local playlist changes. */
export function getLocalPlaylists(): LocalPlaylist[] {
  return playlists;
}

export function getLocalPlaylistSummaries(): LocalPlaylistSummary[] {
  return summariesCache;
}

export function subscribeLocalPlaylists(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getLocalPlaylist(id: string): LocalPlaylist | undefined {
  return playlists.find((playlist) => playlist.id === id);
}

export function createLocalPlaylist(
  title: string,
  description?: string,
): LocalPlaylist {
  const now = new Date().toISOString();
  const playlist: LocalPlaylist = {
    id: newId(LOCAL_PLAYLIST_PREFIX),
    title,
    ...(description ? { description } : {}),
    createdAt: now,
    updatedAt: now,
    revision: 1,
    tracks: [],
  };
  update([playlist, ...playlists]);
  return playlist;
}

export function updateLocalPlaylist(
  id: string,
  patch: { title?: string; description?: string | null },
): LocalPlaylist | undefined {
  let updated: LocalPlaylist | undefined;
  const next = playlists.map((playlist) => {
    if (playlist.id !== id) return playlist;
    updated = {
      ...playlist,
      ...(patch.title !== undefined ? { title: patch.title } : {}),
      ...(patch.description !== undefined
        ? patch.description
          ? { description: patch.description }
          : { description: undefined }
        : {}),
      updatedAt: new Date().toISOString(),
      revision: playlist.revision + 1,
    };
    return updated;
  });
  if (updated) update(next);
  return updated;
}

export function addLocalPlaylistTrack(
  playlistId: string,
  track: Track,
): Track | undefined {
  let added: Track | undefined;
  const next = playlists.map((playlist) => {
    if (playlist.id !== playlistId) return playlist;
    const item: Track = {
      ...track,
      playlistItemId: track.playlistItemId ?? newId(LOCAL_ITEM_PREFIX),
      addedAt: track.addedAt ?? new Date().toISOString(),
    };
    added = item;
    return {
      ...playlist,
      tracks: [...playlist.tracks, item],
      updatedAt: new Date().toISOString(),
      revision: playlist.revision + 1,
    };
  });
  if (added) update(next);
  return added;
}

export function removeLocalPlaylistTrack(
  playlistId: string,
  itemId: string,
): void {
  let changed = false;
  const next = playlists.map((playlist) => {
    if (playlist.id !== playlistId) return playlist;
    const tracks = playlist.tracks.filter(
      (track) => track.playlistItemId !== itemId && track.id !== itemId,
    );
    if (tracks.length === playlist.tracks.length) return playlist;
    changed = true;
    return {
      ...playlist,
      tracks,
      updatedAt: new Date().toISOString(),
      revision: playlist.revision + 1,
    };
  });
  if (changed) update(next);
}

export function moveLocalPlaylistTrack(
  playlistId: string,
  itemId: string,
  beforeItemId: string | null,
): void {
  let changed = false;
  const next = playlists.map((playlist) => {
    if (playlist.id !== playlistId) return playlist;
    const index = playlist.tracks.findIndex(
      (track) => track.playlistItemId === itemId || track.id === itemId,
    );
    if (index < 0) return playlist;
    const tracks = [...playlist.tracks];
    const [moved] = tracks.splice(index, 1);
    const beforeIndex = beforeItemId
      ? tracks.findIndex(
          (track) =>
            track.playlistItemId === beforeItemId || track.id === beforeItemId,
        )
      : -1;
    tracks.splice(beforeIndex < 0 ? tracks.length : beforeIndex, 0, moved);
    changed = true;
    return {
      ...playlist,
      tracks,
      updatedAt: new Date().toISOString(),
      revision: playlist.revision + 1,
    };
  });
  if (changed) update(next);
}

/**
 * Give the tracks already stored in local playlists a length resolved later,
 * so a playlist no longer sums to "0 min 0 s" because a track was added
 * without one. Playlists without a missing length are left untouched.
 */
export function fillMissingDurations(
  durationOf: (trackId: string) => number | undefined,
): void {
  let changed = false;
  const next = playlists.map((playlist) => {
    let filled = false;
    const tracks = playlist.tracks.map((track) => {
      if ((track.durationMs ?? 0) > 0) return track;
      const durationMs = durationOf(track.id);
      if (!durationMs) return track;
      filled = true;
      return { ...track, durationMs };
    });
    if (!filled) return playlist;
    changed = true;
    return { ...playlist, tracks, revision: playlist.revision + 1 };
  });
  if (changed) update(next);
}

export function deleteLocalPlaylist(id: string): void {
  if (!playlists.some((playlist) => playlist.id === id)) return;
  update(playlists.filter((playlist) => playlist.id !== id));
}
