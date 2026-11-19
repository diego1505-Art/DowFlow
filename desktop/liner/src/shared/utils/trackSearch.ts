// In-page track search (playlist / album / mix / liked pages).
//
// Matching is forgiving on purpose: case-insensitive, accent-insensitive
// (NFKD + strip combining marks, so "ё"→"е", "ї"→"і", "é"→"e"), with
// typographic apostrophes and dashes folded. Every whitespace-separated word
// of the query must appear somewhere in title, artists or album, in any order,
// so "madk dyn" finds "ДИНАСТИЯ — madk1d" style rows.

export interface SearchableTrack {
  title: string;
  artists?: string;
  album?: { title?: string } | null;
}

export interface TrackMatch<T> {
  track: T;
  /** position in the unfiltered list (track numbers, playback start) */
  index: number;
}

const APOSTROPHES = /[‘’ʼ`´]/g;
const DASHES = /[‐-―−]/g;
const MARKS = /\p{M}/gu;

function foldChar(ch: string): string {
  return ch
    .normalize("NFKD")
    .replace(MARKS, "")
    .replace(APOSTROPHES, "'")
    .replace(DASHES, "-")
    .toLowerCase();
}

export function normalizeForSearch(text: string): string {
  let out = "";
  for (const ch of text) out += foldChar(ch);
  return out;
}

export function tokenizeQuery(query: string): string[] {
  return normalizeForSearch(query).split(/\s+/).filter(Boolean);
}

/** Tracks that match every query word, in their original order. */
export function filterTracks<T extends SearchableTrack>(
  tracks: readonly T[],
  query: string,
): TrackMatch<T>[] {
  const tokens = tokenizeQuery(query);
  const all = tracks.map((track, index) => ({ track, index }));
  if (tokens.length === 0) return all;
  return all.filter(({ track }) => {
    const haystack = normalizeForSearch(
      `${track.title} ${track.artists ?? ""} ${track.album?.title ?? ""}`,
    );
    return tokens.every((token) => haystack.includes(token));
  });
}

/**
 * Character ranges [start, end) in the original `text` covered by query words,
 * merged and sorted, so the UI can wrap them in <mark>.
 */
export function findHighlightRanges(
  text: string,
  query: string,
): Array<[number, number]> {
  const tokens = tokenizeQuery(query);
  if (!text || tokens.length === 0) return [];

  // normalized string plus, for every normalized char, the original span it came from
  let normalized = "";
  const origStart: number[] = [];
  const origEnd: number[] = [];
  let offset = 0;
  for (const ch of text) {
    const folded = foldChar(ch);
    for (let i = 0; i < folded.length; i++) {
      origStart.push(offset);
      origEnd.push(offset + ch.length);
    }
    normalized += folded;
    offset += ch.length;
  }

  const ranges: Array<[number, number]> = [];
  for (const token of tokens) {
    let from = 0;
    for (;;) {
      const at = normalized.indexOf(token, from);
      if (at === -1) break;
      ranges.push([origStart[at], origEnd[at + token.length - 1]]);
      from = at + token.length;
    }
  }
  if (ranges.length === 0) return [];

  ranges.sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [ranges[0]];
  for (let i = 1; i < ranges.length; i++) {
    const last = merged[merged.length - 1];
    const cur = ranges[i];
    if (cur[0] <= last[1]) last[1] = Math.max(last[1], cur[1]);
    else merged.push(cur);
  }
  return merged;
}
