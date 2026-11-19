import { runWorkerPool } from "@/shared/utils/workerPool";
import { SoundCloudUnavailableError } from "./soundcloudTranscodings";

export interface HlsMediaPlaylist {
  initSegment?: string;
  segments: string[];
}

export interface HlsDownloadOptions {
  signal?: AbortSignal;
  concurrency?: number;
  maxBytes?: number;
}

type ParsedPlaylist = HlsMediaPlaylist | { variant: string };

const DEFAULT_CONCURRENCY = 6;
const DEFAULT_MAX_BYTES = 300 * 1024 * 1024;
const MAX_SEGMENT_ATTEMPTS = 2;
const MAX_PLAYLIST_HOPS = 2;

export function parseHlsPlaylist(
  text: string,
  baseUrl: string,
): ParsedPlaylist {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines[0] !== "#EXTM3U") throw new Error("Not an HLS playlist");
  const resolve = (uri: string) => new URL(uri, baseUrl).toString();
  const segments: string[] = [];
  let initSegment: string | undefined;
  for (const [index, line] of lines.entries()) {
    if (line.startsWith("#EXT-X-STREAM-INF")) {
      const variant = lines
        .slice(index + 1)
        .find((candidate) => !candidate.startsWith("#"));
      if (!variant) throw new Error("HLS master playlist has no variants");
      return { variant: resolve(variant) };
    }
    if (line.startsWith("#EXT-X-KEY")) {
      const method = /METHOD=([A-Z0-9-]+)/.exec(line)?.[1];
      if (method && method !== "NONE")
        throw new SoundCloudUnavailableError("encrypted");
    } else if (line.startsWith("#EXT-X-MAP")) {
      const uri = /URI="([^"]+)"/.exec(line)?.[1];
      if (uri) initSegment = resolve(uri);
    } else if (!line.startsWith("#")) {
      segments.push(resolve(line));
    }
  }
  if (segments.length === 0) throw new Error("HLS playlist has no segments");
  return initSegment ? { initSegment, segments } : { segments };
}

async function fetchBytes(
  url: string,
  signal?: AbortSignal,
): Promise<Uint8Array<ArrayBuffer>> {
  let lastError: unknown = null;
  for (let attempt = 0; attempt < MAX_SEGMENT_ATTEMPTS; attempt += 1) {
    try {
      const response = await fetch(url, { signal });
      if (!response.ok)
        throw new Error(`HLS request returned HTTP ${response.status}`);
      return new Uint8Array(await response.arrayBuffer());
    } catch (error) {
      if (signal?.aborted) throw error;
      lastError = error;
    }
  }
  throw lastError;
}

async function loadMediaPlaylist(
  playlistUrl: string,
  signal?: AbortSignal,
): Promise<HlsMediaPlaylist> {
  let url = playlistUrl;
  for (let hop = 0; hop <= MAX_PLAYLIST_HOPS; hop += 1) {
    const parsed = parseHlsPlaylist(
      new TextDecoder().decode(await fetchBytes(url, signal)),
      url,
    );
    if (!("variant" in parsed)) return parsed;
    url = parsed.variant;
  }
  throw new Error("HLS playlist nests too deep");
}

export async function downloadHlsAudio(
  playlistUrl: string,
  options: HlsDownloadOptions = {},
): Promise<Uint8Array<ArrayBuffer>> {
  const { signal } = options;
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;
  const playlist = await loadMediaPlaylist(playlistUrl, signal);
  const urls = playlist.initSegment
    ? [playlist.initSegment, ...playlist.segments]
    : playlist.segments;
  const parts = Array.from({ length: urls.length }, () => new Uint8Array(0));
  let total = 0;
  await runWorkerPool(
    urls,
    options.concurrency ?? DEFAULT_CONCURRENCY,
    async (url, index) => {
      const part = await fetchBytes(url, signal);
      total += part.byteLength;
      if (total > maxBytes)
        throw new Error(`HLS stream is larger than ${maxBytes} bytes`);
      parts[index] = part;
    },
  );
  const output = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.byteLength;
  }
  return output;
}
