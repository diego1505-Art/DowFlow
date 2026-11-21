import { isLocalTrackId } from "@/shared/media/local";
import type { Track } from "@/shared/types";

export interface ListeningHistoryEntry {
  track: Track;
  playedAt: number;
}

const STORAGE_KEY = "liner_listening_history_v1";
const HISTORY_LIMIT = 60;
const CHANGE_EVENT = "liner:listening-history-changed";

function isEntry(value: unknown): value is ListeningHistoryEntry {
  if (!value || typeof value !== "object") return false;
  const entry = value as Partial<ListeningHistoryEntry>;
  return (
    typeof entry.playedAt === "number" &&
    Number.isFinite(entry.playedAt) &&
    Boolean(entry.track) &&
    typeof entry.track === "object" &&
    typeof entry.track.id === "string" &&
    entry.track.id.length > 0 &&
    typeof entry.track.title === "string" &&
    typeof entry.track.artists === "string"
  );
}

function readStoredHistory(): ListeningHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isEntry).slice(0, HISTORY_LIMIT);
  } catch {
    return [];
  }
}

let snapshot: ListeningHistoryEntry[] = readStoredHistory();

function persist(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // The row still works for this session when storage is unavailable.
  }
}

/** Newest first, without duplicates. */
export function getListeningHistory(): ListeningHistoryEntry[] {
  return snapshot;
}

export function recordListeningHistory(track: Track | null | undefined): void {
  if (!track?.id || isLocalTrackId(track.id)) return;
  const previous = snapshot.find((entry) => entry.track.id === track.id);
  // A replayed track stays at the top, but keeps its original first-play time
  // only when nothing changed; otherwise refresh it to now.
  const rest = snapshot.filter((entry) => entry.track.id !== track.id);
  snapshot = [
    { track, playedAt: previous?.playedAt ?? Date.now() },
    ...rest,
  ].slice(0, HISTORY_LIMIT);
  persist();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }
}

export function subscribeListeningHistory(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(CHANGE_EVENT, listener);
  return () => window.removeEventListener(CHANGE_EVENT, listener);
}

export function clearListeningHistory(): void {
  snapshot = [];
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}
