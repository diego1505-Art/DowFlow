import type { SearchResult, SearchType } from "@/shared/contracts";
import { rethrowIfAborted } from "@/shared/utils/abort";
import {
  type JsonRecord,
  numberValue,
  trimmedString,
} from "@/shared/utils/json";
import { getJson } from "./soundcloudCatalogRequest";
import { soundCloudPlaylistId } from "./soundcloudIds";
import {
  mapSoundCloudArtist,
  mapSoundCloudCatalogTrack,
  soundCloudCover,
  soundCloudPlaylistCover,
  soundCloudYear,
} from "./soundcloudMappers";

const SOUNDCLOUD_URL =
  /^(?:https?:\/\/)?(?:www\.|m\.|on\.)?soundcloud\.com\/\S+$/i;
const SHORT_LINK_HOST = "on.soundcloud.com";

export function isSoundCloudUrl(value: string): boolean {
  return SOUNDCLOUD_URL.test(value.trim());
}

function stripQuery(value: string): string {
  const url = new URL(value);
  return `${url.origin}${url.pathname}`;
}

async function canonicalUrl(
  value: string,
  signal?: AbortSignal,
): Promise<string> {
  const url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`);
  if (url.hostname.toLowerCase() === SHORT_LINK_HOST) {
    try {
      const response = await fetch(url, { redirect: "follow", signal });
      if (response.url) return stripQuery(response.url);
    } catch {
      rethrowIfAborted(signal);
    }
  }
  return `https://soundcloud.com${url.pathname}`;
}

function mapSet(record: JsonRecord): SearchResult | null {
  const id = numberValue(record.id);
  const title = trimmedString(record.title);
  if (id === undefined || !title) return null;
  const cover = soundCloudPlaylistCover(record);
  const artist = mapSoundCloudArtist(record.user);
  if (record.is_album === true || trimmedString(record.set_type)) {
    const year = soundCloudYear(record);
    return {
      type: "album",
      id: soundCloudPlaylistId(id),
      title,
      artists: artist ? [artist] : [],
      ...(year ? { year } : {}),
      ...(cover ? { cover } : {}),
    };
  }
  return {
    type: "playlist",
    id: soundCloudPlaylistId(id),
    title,
    ...(artist ? { author: artist.name } : {}),
    ...(cover ? { cover } : {}),
  };
}

function mapResolved(record: JsonRecord): SearchResult | null {
  if (record.kind === "user") {
    const artist = mapSoundCloudArtist(record);
    const cover = soundCloudCover(record.avatar_url);
    return artist
      ? { type: "artist", ...artist, ...(cover ? { cover } : {}) }
      : null;
  }
  if (record.kind === "playlist") return mapSet(record);
  if (record.kind === "track") {
    const track = mapSoundCloudCatalogTrack(record);
    return track ? { ...track, type: "track" } : null;
  }
  return null;
}

function matchesType(result: SearchResult, type: SearchType): boolean {
  return type === "all" || result.type === type;
}

export async function resolveSoundCloudUrl(
  value: string,
  type: SearchType = "all",
  signal?: AbortSignal,
): Promise<SearchResult[]> {
  const url = await canonicalUrl(value.trim(), signal);
  const result = mapResolved(await getJson("/resolve", { url }, signal));
  return result && matchesType(result, type) ? [result] : [];
}
