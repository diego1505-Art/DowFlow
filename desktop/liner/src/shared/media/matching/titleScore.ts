import { cleanBaseTitle } from "./junk";
import { toPhoneticLatin } from "./phonetic";
import { tokenSetRatio, tokenSortRatio } from "./similarity";
import type { SourceProfile } from "./sourceProfile";

function bestRatio(left: string, right: string): number {
  return Math.max(tokenSortRatio(left, right), tokenSetRatio(left, right));
}

function isNearSubstring(left: string, right: string): boolean {
  const minLength = Math.min(left.length, right.length);
  const maxLength = Math.max(left.length, right.length);
  return (
    minLength >= 4 &&
    minLength / maxLength >= 0.7 &&
    (left.includes(right) || right.includes(left))
  );
}

export function computeTitleRatio(
  profile: SourceProfile,
  candidateBaseTitle: string,
  candidateFullClean: string,
): number {
  let titleRatio = Math.max(
    bestRatio(profile.baseTitle, candidateBaseTitle),
    bestRatio(profile.fullClean, candidateFullClean),
    bestRatio(profile.baseTitle, candidateFullClean),
    bestRatio(profile.fullClean, candidateBaseTitle),
  );

  if (
    isNearSubstring(profile.baseTitle, candidateBaseTitle) ||
    isNearSubstring(profile.fullClean, candidateFullClean)
  ) {
    titleRatio = Math.max(titleRatio, 92);
  }

  const phoneticRatio = bestRatio(
    toPhoneticLatin(profile.baseTitle),
    toPhoneticLatin(candidateBaseTitle),
  );
  return Math.max(titleRatio, phoneticRatio);
}

export interface InvertedMatch {
  titleRatio: number;
  artistRatio: number;
}

export function computeInvertedMatch(
  profile: SourceProfile,
  candidateBaseTitle: string,
  candidateArtists: string[],
): InvertedMatch | undefined {
  if (!profile.hasTwoParts) return undefined;
  const titleRatio = bestRatio(profile.part0Clean, candidateBaseTitle);
  const artistRatio = Math.max(
    ...candidateArtists.map((artist) =>
      bestRatio(profile.part1Clean, cleanBaseTitle(artist)),
    ),
    0,
  );
  return titleRatio >= 85 && artistRatio >= 85
    ? { titleRatio, artistRatio }
    : undefined;
}
