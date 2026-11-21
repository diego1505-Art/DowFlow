import type { Track } from "@/shared/types";

const STORAGE_KEY = "liner_local_likes_v1";
const CHANGE_EVENT = "liner:local-likes-changed";

export interface LocalLikeEntry {
  track: Track;
  likedAt: string;
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

function read(): LocalLikeEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed: unknown = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) ?? "[]",
    );
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (entry): entry is LocalLikeEntry =>
          Boolean(entry) &&
          typeof entry === "object" &&
          isTrack((entry as LocalLikeEntry).track) &&
          typeof (entry as LocalLikeEntry).likedAt === "string",
      )
      .slice(0, 2000);
  } catch {
    return [];
  }
}

let entries: LocalLikeEntry[] = read();
let tracks: Track[] = entries.map((entry) => entry.track);
const listeners = new Set<() => void>();

function update(next: LocalLikeEntry[]): void {
  entries = next;
  tracks = entries.map((entry) => entry.track);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
    } catch {
      // Keep the in-memory likes when storage is unavailable.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
    window.dispatchEvent(new Event("library:changed"));
  }
  listeners.forEach((listener) => listener());
}

/** Newest first. The array is stable until the likes change. */
export function getLocalLikes(): Track[] {
  return tracks;
}

export function subscribeLocalLikes(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isLocalTrackLiked(trackId: string): boolean {
  return entries.some((entry) => entry.track.id === trackId);
}

export function addLocalLike(track: Track): void {
  update([
    { track, likedAt: new Date().toISOString() },
    ...entries.filter((entry) => entry.track.id !== track.id),
  ]);
}

export function removeLocalLike(trackId: string): void {
  if (!isLocalTrackLiked(trackId)) return;
  update(entries.filter((entry) => entry.track.id !== trackId));
}
