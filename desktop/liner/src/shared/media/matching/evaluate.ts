import type { ImportedTrack, Track } from "@/shared/contracts";
import { artistsMatch } from "./artists";
import { durationDelta } from "./duration";
import { rankCandidate, type RankedCandidate } from "./rankCandidate";
import { buildSourceProfile } from "./sourceProfile";

export type Match = { track: Track; score: number };

export type MatchRejectionReason =
  "low_confidence_match" | "ambiguous_match" | "duration_mismatch";

export type MatchDecision =
  | Match
  | {
      reason: MatchRejectionReason;
      score?: number;
      proposedTrack?: Track;
    };

function reject(
  reason: MatchRejectionReason,
  best: RankedCandidate,
): MatchDecision {
  return { reason, score: best.score, proposedTrack: best.track };
}

function isAmbiguous(
  best: RankedCandidate,
  second: RankedCandidate | undefined,
): boolean {
  if (!second || second.isDisqualified || best.score - second.score >= 10)
    return false;
  const isDuplicate =
    best.titleClean === second.titleClean &&
    artistsMatch(best.primaryArtist, second.primaryArtist) &&
    (durationDelta(best.track.durationMs, second.track.durationMs) ??
      Number.POSITIVE_INFINITY) <= 3_000;
  const isClearWinner =
    best.score >= 75 &&
    best.versionMatches &&
    best.artistExact &&
    best.delta !== undefined &&
    best.delta <= 4_000;
  return (
    !isDuplicate && !isClearWinner && (!best.titleExact || !best.versionMatches)
  );
}

function acceptedScore(best: RankedCandidate): number | undefined {
  const withinDelta = (limit: number) =>
    best.delta === undefined || best.delta <= limit;
  if (
    best.bestTitleRatio >= 85 &&
    best.artistExact &&
    best.versionMatches &&
    withinDelta(10_000)
  ) {
    return Math.max(best.score, 95);
  }
  if (
    best.bestTitleRatio >= 88 &&
    best.titleClean.length >= 4 &&
    best.delta !== undefined &&
    best.delta <= 3_000 &&
    best.versionMatches
  ) {
    return Math.max(best.score, 88);
  }
  if (
    best.artistExact &&
    withinDelta(4_000) &&
    best.bestTitleRatio >= 70 &&
    best.versionMatches
  ) {
    return Math.max(best.score, 85);
  }
  if (
    best.score >= 75 &&
    best.bestTitleRatio >= 75 &&
    (best.artistExact || best.bestArtistRatio >= 70) &&
    best.versionMatches &&
    withinDelta(8_000)
  ) {
    return best.score;
  }
  return undefined;
}

export function evaluateImportedTrack(
  source: ImportedTrack,
  candidates: readonly Track[],
): MatchDecision {
  const profile = buildSourceProfile(source);
  const ranked = candidates
    .map((candidate) => rankCandidate(profile, candidate))
    .sort((a, b) => b.score - a.score);
  const best = ranked[0];
  if (!best) return { reason: "low_confidence_match" };
  if (best.isDisqualified) return reject("duration_mismatch", best);
  if (isAmbiguous(best, ranked[1])) return reject("ambiguous_match", best);

  const score = acceptedScore(best);
  return score === undefined
    ? reject("low_confidence_match", best)
    : { track: best.track, score };
}

export function matchImportedTrack(
  source: ImportedTrack,
  candidates: readonly Track[],
): Match | undefined {
  const result = evaluateImportedTrack(source, candidates);
  return "track" in result ? result : undefined;
}
