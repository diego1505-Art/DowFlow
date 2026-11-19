import { artistsMatch } from "./artists";
import { normalizeTrackString, toPhoneticLatin } from "./phonetic";
import { tokenSetRatio, tokenSortRatio } from "./similarity";
import type { SourceProfile } from "./sourceProfile";

export interface ArtistScore {
  artistExact: boolean;
  bestArtistRatio: number;
}

function hasDirectMatch(
  profile: SourceProfile,
  candidateArtists: string[],
  primaryCandidateArtist: string,
): boolean {
  return (
    artistsMatch(profile.primaryArtist, primaryCandidateArtist) ||
    (profile.meta.artist
      ? candidateArtists.some((artist) =>
          artistsMatch(profile.meta.artist, artist),
        )
      : false) ||
    profile.artists.some((sourceArtist) =>
      candidateArtists.some((artist) => artistsMatch(sourceArtist, artist)),
    )
  );
}

function hasInTitleArtist(
  profile: SourceProfile,
  candidateArtists: string[],
): boolean {
  const phoneticTitle = toPhoneticLatin(profile.title);
  return candidateArtists.some((artist) => {
    const normalized = normalizeTrackString(artist);
    return (
      normalized.length >= 3 &&
      (profile.fullClean.includes(normalized) ||
        phoneticTitle.includes(toPhoneticLatin(artist)))
    );
  });
}

export function computeArtistScore(
  profile: SourceProfile,
  candidateArtists: string[],
  primaryCandidateArtist: string,
): ArtistScore {
  if (
    hasDirectMatch(profile, candidateArtists, primaryCandidateArtist) ||
    hasInTitleArtist(profile, candidateArtists)
  ) {
    return { artistExact: true, bestArtistRatio: 100 };
  }

  let bestArtistRatio = 0;
  for (const sourceArtist of profile.artists) {
    for (const candidateArtist of candidateArtists) {
      const ratio = Math.max(
        tokenSortRatio(sourceArtist, candidateArtist),
        tokenSetRatio(sourceArtist, candidateArtist),
      );
      const phonetic = tokenSortRatio(
        toPhoneticLatin(sourceArtist),
        toPhoneticLatin(candidateArtist),
      );
      bestArtistRatio = Math.max(bestArtistRatio, ratio, phonetic);
    }
  }
  return { artistExact: bestArtistRatio >= 85, bestArtistRatio };
}
