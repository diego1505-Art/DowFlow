import { cleanBaseTitle, stripJunk } from "./junk";
import { getVersionTags } from "./versionTags";

export interface ParsedArtistTitle {
  artist?: string;
  title: string;
  rawArtist?: string;
  rawTitle?: string;
}

export interface SoundCloudMetadata {
  artist: string;
  title: string;
  cleanTitle: string;
  versionTags: Set<string>;
  searchQuery: string;
}

export const TITLE_DELIMITER = /\s*[-–—:|~]\s*/;

export function parseArtistAndTitle(rawTitle: string): ParsedArtistTitle {
  const cleaned = stripJunk(rawTitle);
  const parts = cleaned.split(TITLE_DELIMITER);
  if (
    parts.length >= 3 &&
    parts[1].trim().length >= 2 &&
    parts[2].trim().length >= 1
  ) {
    const artist = parts[1].trim();
    const title = parts.slice(2).join(" - ").trim();
    return { artist, title, rawArtist: artist, rawTitle: title };
  }
  if (
    parts.length === 2 &&
    parts[0].trim().length >= 2 &&
    parts[1].trim().length >= 1 &&
    /[^\p{N}\s]/u.test(parts[0])
  ) {
    const artist = parts[0].trim();
    const title = parts[1].trim();
    return { artist, title, rawArtist: artist, rawTitle: title };
  }
  return { title: cleaned };
}

export function cleanSoundCloudMetadata(
  rawTitle: string,
  uploaderArtist?: string,
): SoundCloudMetadata {
  const parsed = parseArtistAndTitle(rawTitle);
  const versionTags = getVersionTags(rawTitle);
  const cleanedTitle = stripJunk(parsed.title);
  const artist = (parsed.artist || uploaderArtist || "").trim();

  const searchQuery =
    artist && !cleanedTitle.toLowerCase().startsWith(artist.toLowerCase())
      ? `${artist} ${cleanedTitle}`.trim()
      : cleanedTitle.trim();

  return {
    artist,
    title: cleanedTitle,
    cleanTitle: cleanBaseTitle(cleanedTitle),
    versionTags,
    searchQuery: searchQuery.replace(/\s+/g, " "),
  };
}
