// Adapted for private DowFlow use from Liner commit 5bec3c7.
import { asArray, asRecord } from "./json";
import type { Cover } from "../types";

const artworkHost = /(?:[a-zA-Z0-9_-]+\.googleusercontent\.com|yt3\.ggpht\.com)/i;

interface ThumbnailEntry {
  url: string;
  width: number;
  height: number;
}

function isSquareArtwork(entry: ThumbnailEntry): boolean {
  if (entry.width > 0 && entry.height > 0) {
    return entry.width === entry.height || artworkHost.test(entry.url);
  }
  return artworkHost.test(entry.url);
}

function toSquareArtworkUrl(url: string, size = 512): string {
  if (!artworkHost.test(url)) return url;
  const suffix = size === 0 ? "=s0" : `=w${size}-h${size}-l90-rj`;
  if (/=w\d+-h\d+/.test(url)) return url.replace(/=w\d+-h\d+(?:-[a-zA-Z0-9_-]+)*/, suffix);
  if (/=s\d+/.test(url)) return url.replace(/=s\d+(?:-[a-zA-Z0-9_-]+)*/, suffix);
  return `${url}${suffix}`;
}

function readEntries(thumbnail: unknown): ThumbnailEntry[] {
  const record = asRecord(thumbnail);
  const inner = asRecord(asRecord(record?.musicThumbnailRenderer)?.thumbnail) ?? record;
  return asArray(inner?.thumbnails)
    .map(asRecord)
    .flatMap((entry) =>
      entry && typeof entry.url === "string"
        ? [{ url: entry.url, width: typeof entry.width === "number" ? entry.width : 0, height: typeof entry.height === "number" ? entry.height : 0 }]
        : [],
    );
}

function largestFirst(a: ThumbnailEntry, b: ThumbnailEntry): number {
  return Math.max(b.width, b.height) - Math.max(a.width, a.height);
}

export function coverFromThumbnail(thumbnail: unknown): Cover | undefined {
  const entries = readEntries(thumbnail);
  const square = entries.filter(isSquareArtwork).sort(largestFirst)[0];
  if (square) {
    return { url: toSquareArtworkUrl(square.url, 512), width: 512, height: 512 };
  }
  const fallback = entries.sort(largestFirst)[0];
  if (!fallback) return undefined;
  return { url: fallback.url, width: fallback.width, height: fallback.height };
}

export function videoThumbnailCover(videoId: string): Cover {
  return { url: `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`, width: 480, height: 360 };
}
