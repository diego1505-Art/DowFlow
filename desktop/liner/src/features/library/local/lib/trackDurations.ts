import { clientCatalog } from "@/shared/api/clientCatalog";
import { fillMissingDurations } from "../playlists";

/**
 * A playlist only knows a track's length when whatever added it carried one:
 * a track added from a list without its duration, or resolved while the
 * catalog was unreachable, is stored with `durationMs: 0` and the playlist
 * total then reads "0 min 0 s" forever. This keeps the lengths resolved
 * afterwards so a playlist can fill in what it is missing.
 */
const CACHE_KEY = "liner:track-durations-v1";
const CACHE_LIMIT = 5000;
const MAX_PARALLEL = 3;

let durations: Record<string, number> | null = null;
let version = 0;
const listeners = new Set<() => void>();
const pending = new Set<string>();

function read(): Record<string, number> {
  if (durations) return durations;
  const loaded: Record<string, number> = {};
  if (typeof window !== "undefined") {
    try {
      const parsed: unknown = JSON.parse(
        window.localStorage.getItem(CACHE_KEY) ?? "{}",
      );
      if (parsed && typeof parsed === "object") {
        for (const [id, value] of Object.entries(
          parsed as Record<string, unknown>,
        )) {
          if (typeof value === "number" && Number.isFinite(value) && value > 0) {
            loaded[id] = Math.round(value);
          }
        }
      }
    } catch {
      // An unreadable cache only means the lengths are resolved again.
    }
  }
  durations = loaded;
  return loaded;
}

function persist(cache: Record<string, number>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Keep the in-memory cache when storage is full or unavailable.
  }
}

export function knownDurationMs(id: string): number | undefined {
  if (!id) return undefined;
  const value = read()[id];
  return value && value > 0 ? value : undefined;
}

/** Changes whenever a newly resolved length becomes available. */
export function getDurationVersion(): number {
  return version;
}

export function subscribeDurations(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function remember(id: string, durationMs: number): void {
  const cache = read();
  cache[id] = durationMs;
  const ids = Object.keys(cache);
  if (ids.length > CACHE_LIMIT) {
    for (const stale of ids.slice(0, ids.length - CACHE_LIMIT)) {
      delete cache[stale];
    }
  }
  persist(cache);
  version += 1;
  listeners.forEach((listener) => listener());
}

async function fetchDuration(id: string): Promise<number> {
  try {
    const snapshot = await clientCatalog.resolveSnapshot(id);
    return Math.max(0, Math.round(snapshot?.durationMs ?? 0));
  } catch {
    return 0;
  }
}

/**
 * Resolve the lengths of tracks stored without one, at most three at a time.
 * Resolved lengths are kept for every playlist of this device.
 */
export function requestDurations(ids: readonly string[]): void {
  const queue: string[] = [];
  for (const id of ids) {
    if (!id || pending.has(id) || knownDurationMs(id)) continue;
    pending.add(id);
    queue.push(id);
  }
  if (queue.length === 0) return;

  let running = 0;
  let filled = false;

  const pump = (): void => {
    while (running < MAX_PARALLEL && queue.length > 0) {
      const id = queue.shift() as string;
      running += 1;
      void fetchDuration(id)
        .then((durationMs) => {
          if (durationMs <= 0) return;
          remember(id, durationMs);
          filled = true;
        })
        .finally(() => {
          pending.delete(id);
          running -= 1;
          if (running === 0 && queue.length === 0) {
            // Give the playlists that stored this track a length for free.
            if (filled) fillMissingDurations(knownDurationMs);
            return;
          }
          pump();
        });
    }
  };

  pump();
}
