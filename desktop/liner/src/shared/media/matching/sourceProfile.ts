import type { ImportedTrack } from "@/shared/contracts";
import { artistsMatch } from "./artists";
import {
  cleanSoundCloudMetadata,
  parseArtistAndTitle,
  TITLE_DELIMITER,
  type SoundCloudMetadata,
} from "./artistTitle";
import { cleanBaseTitle, stripJunk } from "./junk";

export interface SourceProfile {
  title: string;
  meta: SoundCloudMetadata;
  baseTitle: string;
  fullClean: string;
  versionTags: Set<string>;
  artists: string[];
  primaryArtist: string;
  hasTwoParts: boolean;
  part0Clean: string;
  part1Clean: string;
  durationMs?: number;
}

export function buildSourceProfile(source: ImportedTrack): SourceProfile {
  const meta = cleanSoundCloudMetadata(source.title, source.artists[0]);
  const parsed = parseArtistAndTitle(source.title);
  const artists = [...source.artists];
  if (
    meta.artist &&
    !artists.some((artist) => artistsMatch(artist, meta.artist))
  ) {
    artists.push(meta.artist);
  }

  const titleParts = stripJunk(source.title).split(TITLE_DELIMITER);
  const hasTwoParts =
    titleParts.length === 2 &&
    titleParts[0].trim().length >= 2 &&
    titleParts[1].trim().length >= 1;

  return {
    title: source.title,
    meta,
    baseTitle: cleanBaseTitle(parsed.title || source.title),
    fullClean: cleanBaseTitle(source.title),
    versionTags: meta.versionTags,
    artists,
    primaryArtist: artists[0] ?? "",
    hasTwoParts,
    part0Clean: hasTwoParts ? cleanBaseTitle(titleParts[0]) : "",
    part1Clean: hasTwoParts ? cleanBaseTitle(titleParts[1]) : "",
    durationMs: source.durationMs,
  };
}
