import type { Track } from "@/shared/contracts";
import { computeArtistScore } from "./artistScore";
import { artistsMatch } from "./artists";
import { parseArtistAndTitle } from "./artistTitle";
import { DISQUALIFY_DELTA_MS, durationDelta, durationScore } from "./duration";
import { cleanBaseTitle } from "./junk";
import type { SourceProfile } from "./sourceProfile";
import { computeInvertedMatch, computeTitleRatio } from "./titleScore";
import { compareVersionTags, getVersionTags } from "./versionTags";

export interface RankedCandidate {
  track: Track;
  score: number;
  delta?: number;
  isDisqualified: boolean;
  titleExact: boolean;
  bestTitleRatio: number;
  artistExact: boolean;
  bestArtistRatio: number;
  titleClean: string;
  primaryArtist: string;
  versionMatches: boolean;
}

export function rankCandidate(
  profile: SourceProfile,
  candidate: Track,
): RankedCandidate {
  const parsed = parseArtistAndTitle(candidate.title);
  const candidateBaseTitle = cleanBaseTitle(parsed.title || candidate.title);
  const candidateFullClean = cleanBaseTitle(candidate.title);
  const versionResult = compareVersionTags(
    profile.versionTags,
    getVersionTags(candidate.title),
  );

  const candidateArtists = candidate.artists.map((artist) => artist.name);
  const parsedArtist = parsed.artist;
  if (
    parsedArtist &&
    !candidateArtists.some((artist) => artistsMatch(artist, parsedArtist))
  ) {
    candidateArtists.push(parsedArtist);
  }
  const primaryArtist = candidateArtists[0] ?? "";

  let bestTitleRatio = computeTitleRatio(
    profile,
    candidateBaseTitle,
    candidateFullClean,
  );
  let { artistExact, bestArtistRatio } = computeArtistScore(
    profile,
    candidateArtists,
    primaryArtist,
  );

  const inverted = computeInvertedMatch(
    profile,
    candidateBaseTitle,
    candidateArtists,
  );
  if (inverted) {
    bestTitleRatio = Math.max(bestTitleRatio, inverted.titleRatio);
    bestArtistRatio = Math.max(bestArtistRatio, inverted.artistRatio);
    artistExact = true;
  }

  const delta = durationDelta(profile.durationMs, candidate.durationMs);
  const score =
    Math.round(45 * (bestTitleRatio / 100)) +
    Math.round(30 * (bestArtistRatio / 100)) +
    durationScore(delta) +
    versionResult.bonus -
    versionResult.penalty;

  return {
    track: candidate,
    score: Math.max(0, Math.min(100, score)),
    delta,
    isDisqualified: delta !== undefined && delta > DISQUALIFY_DELTA_MS,
    titleExact: bestTitleRatio >= 90,
    bestTitleRatio,
    artistExact,
    bestArtistRatio,
    titleClean: candidateBaseTitle,
    primaryArtist,
    versionMatches: versionResult.matches,
  };
}
