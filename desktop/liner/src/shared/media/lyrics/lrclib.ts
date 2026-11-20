/**
 * Lyrics from LRCLIB (https://lrclib.net), a free open database that returns
 * synced LRC lyrics without any account or API key. This replaces Liner's
 * `/v1/.../lyrics` endpoints so playback never depends on the Liner server.
 */
import type {
  LyricsCandidate,
  LyricsSearchResult,
  LyricsStreamEvent,
} from "@/shared/contracts/lyrics";

const LRCLIB_PATH_PREFIX = "/";
const REQUEST_TIMEOUT_MS = 8_000;

export interface LyricsHint {
  title: string;
  artist: string;
  durationMs?: number;
}

interface LrclibRecord {
  id?: number;
  trackName?: string;
  artistName?: string;
  albumName?: string;
  duration?: number;
  instrumental?: boolean;
  plainLyrics?: string | null;
  syncedLyrics?: string | null;
}

type LrclibQuery = Record<string, string | number | undefined>;

function normalize(value: string | undefined): string {
  return (value ?? "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function durationSeconds(durationMs: number | undefined): number | undefined {
  if (!durationMs || durationMs <= 0) return undefined;
  return Math.round(durationMs / 1000);
}

/** The Electron main process performs the request (no CORS), the browser fetches directly. */
async function requestJson(
  path: string,
  params: LrclibQuery,
): Promise<unknown> {
  const bridge =
    typeof window !== "undefined" ? window.linerElectron : undefined;
  const cleaned: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    cleaned[key] = String(value);
  }
  if (bridge?.fetchLyrics) {
    return bridge.fetchLyrics({ path, params: cleaned });
  }
  const url = new URL(`https://lrclib.net/api${path}`);
  for (const [key, value] of Object.entries(cleaned)) {
    url.searchParams.set(key, value);
  }
  const response = await fetch(url.toString(), {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!response.ok) return null;
  return response.json().catch(() => null);
}

function scoreRecord(record: LrclibRecord, hint: LyricsHint): number {
  let score = 0;
  const wantedTitle = normalize(hint.title);
  const recordTitle = normalize(record.trackName);
  if (recordTitle && recordTitle === wantedTitle) score += 3;
  else if (recordTitle && recordTitle.includes(wantedTitle)) score += 1;

  const wantedArtist = normalize(hint.artist);
  const recordArtist = normalize(record.artistName);
  if (wantedArtist && recordArtist.includes(wantedArtist)) score += 2;

  const wantedDuration = durationSeconds(hint.durationMs);
  if (wantedDuration && typeof record.duration === "number") {
    const diff = Math.abs(record.duration - wantedDuration);
    if (diff <= 2) score += 2;
    else if (diff <= 8) score += 1;
  }
  return score;
}

export function candidateFromRecord(
  record: LrclibRecord,
): LyricsCandidate | null {
  const synced = (record.syncedLyrics ?? "").trim();
  const plain = (record.plainLyrics ?? "").trim();
  if (!synced && !plain) return null;
  const lineSynced = synced.length > 0;
  return {
    provider: "LRCLIB",
    lyrics: {
      format: lineSynced ? "lrc" : "plain",
      content: lineSynced ? synced : plain,
    },
    syncLevel: lineSynced ? "line_level" : "plain",
    contentKind: lineSynced ? "line_synced" : "plain",
    matchedTrack: {
      ...(record.trackName ? { title: record.trackName } : {}),
      ...(record.artistName ? { artists: [record.artistName] } : {}),
      ...(typeof record.duration === "number"
        ? { durationMs: record.duration * 1000 }
        : {}),
    },
    quality: {
      total: lineSynced ? 88 : 60,
      match: 90,
      content: lineSynced ? 90 : 60,
      sync: lineSynced ? 95 : 20,
      source: 70,
      reasons: [],
    },
  };
}

async function searchForRecord(
  hint: LyricsHint,
): Promise<LrclibRecord | null> {
  const title = hint.title?.trim();
  if (!title) return null;
  const artist = (hint.artist ?? "").trim();

  const exact = await requestJson(LRCLIB_PATH_PREFIX + "get", {
    track_name: title,
    artist_name: artist || undefined,
    duration: durationSeconds(hint.durationMs),
  }).catch(() => null);
  if (exact && typeof exact === "object" && !Array.isArray(exact)) {
    return exact as LrclibRecord;
  }

  const found = await requestJson(LRCLIB_PATH_PREFIX + "search", {
    q: [title, artist].filter(Boolean).join(" "),
  }).catch(() => null);
  const list = Array.isArray(found) ? (found as LrclibRecord[]) : [];
  let best: LrclibRecord | null = null;
  let bestScore = 0;
  for (const item of list) {
    const score = scoreRecord(item, hint);
    if (score > bestScore) {
      bestScore = score;
      best = item;
    }
  }
  // A recorded title match is required: a random "search" hit is worse than nothing.
  return bestScore >= 3 ? best : null;
}

export async function searchLrclibLyrics(
  hint: LyricsHint,
): Promise<LyricsSearchResult | null> {
  const record = await searchForRecord(hint);
  const candidate = record ? candidateFromRecord(record) : null;
  return candidate
    ? { cached: false, candidate, provider: candidate.provider }
    : null;
}

export async function* streamLrclibLyrics(
  trackId: string,
  hint?: LyricsHint,
  signal?: AbortSignal,
): AsyncGenerator<LyricsStreamEvent> {
  yield {
    type: "metadata",
    track: {
      id: trackId,
      title: hint?.title ?? "",
      artists: hint?.artist ? [{ id: "", name: hint.artist }] : [],
      durationMs: hint?.durationMs ?? 0,
    },
  };

  if (!hint?.title?.trim() || signal?.aborted) {
    yield { type: "done", cached: false, status: "not_found" };
    return;
  }

  let result: LyricsSearchResult | null = null;
  try {
    result = await searchLrclibLyrics(hint);
  } catch {
    result = null;
  }

  if (signal?.aborted) return;

  if (!result) {
    yield { type: "provider", provider: "LRCLIB", status: "not_found" };
    yield { type: "done", cached: false, status: "not_found" };
    return;
  }

  yield {
    type: "provider",
    provider: result.candidate.provider,
    status: "found",
    syncLevel: result.candidate.syncLevel,
    candidate: result.candidate,
    ...(hint.durationMs ? { durationMs: hint.durationMs } : {}),
  };
  yield {
    type: "done",
    cached: false,
    best: {
      provider: result.candidate.provider,
      quality: result.candidate.quality.total,
      syncLevel: result.candidate.syncLevel,
    },
  };
}
