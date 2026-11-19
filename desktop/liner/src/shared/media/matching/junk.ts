import { normalizeTrackString } from "./phonetic";
import { VERSION_PATTERNS } from "./versionTags";

const JUNK_PATTERNS: Array<[RegExp, string]> = [
  [/\.(?:mp3|wav|flac|m4a|aac|ogg)\b/gi, ""],
  [
    /(?:\(|\[|\{)?\s*(?:tgk|tg|t\.me|vk\.com|soundcloud\.com|soundcloud|instagram\.com|instagram|insta|inst|twitter\.com|x\.com)\s*[:/]?\s*[^)\]}]+(?:\)|\]|\})?/giu,
    "",
  ],
  [/@[\w.-]+/gu, ""],
  [
    /(?:\(|\[|\{)?\s*(?:prod(?:uced)?\s+by|beat\s+by|prod\b\.?|beat\b\.?)\s*[:/]?\s*[^)\]}]+(?:\)|\]|\})?/giu,
    "",
  ],
  [
    /(?:\(|\[|\{)\s*(?:free\s*(?:dl|download)|download(?:\s*link)?|free\s*beat|link\s+in\s+(?:bio|desc(?:ription)?)|out\s+now|stream\s+now|buy\s+now|premiere|exclusive|clip\s+officiel|official\s+video|official\s+audio|official\s+music\s+video|music\s+video|lyric\s+video|visualizer|official\s+visualizer|audio\s+visualizer|og\s+version|og\s+beat|full\s+version|hq|hd|4k)[^)\]}]*[)\]}]/giu,
    "",
  ],
  [
    /\s*[([{]\s*(?:remaster(?:ed)?(?:\s*\d{4})?|ремастеринг(?:\s*\d{4})?|deluxe(?:\s+edition)?|anniversary(?:\s+edition)?|original\s+mix|album\s+version|single\s+version|ost|soundtrack|из\s+(?:телесериала|фильма|к\/ф)[^)\]}]*)[^)\]}]*[)\]}]/giu,
    "",
  ],
  [
    /\s*[-–—|]\s*(?:out\s+now|premiere|exclusive|free\s*dl|official\s*video|visualizer|audio|remaster(?:ed)?|ремастеринг|prod\s+by[^\s]+).*$/iu,
    "",
  ],
  [/\*+[^*]+\*+/gu, ""],
  [/\(\s*\)|\[\s*\]|\{\s*\}/gu, ""],
];

export function stripJunk(value: string): string {
  return JUNK_PATTERNS.reduce(
    (result, [pattern, replacement]) => result.replace(pattern, replacement),
    value,
  )
    .trim()
    .replace(/\s+/g, " ");
}

export function cleanSearchTitle(title: string): string {
  return title
    .replace(
      /[([]\s*(?:official\s+(?:music\s+)?(?:video|audio)|visualizer|lyrics?|audio|hd|4k|mood\s+video|music\s+video|best\s+part)\s*[)\]]/gi,
      " ",
    )
    .replace(/[([]\s*p(?:rod)?(?:\.|uced)?\s+by\s+[^)\]]+[)\]]/gi, " ")
    .replace(/\[\s*p\.[^\]]+\]/gi, " ")
    .replace(/@\w+/g, " ")
    .replace(/[([]\s*(?:explicit|e|18\+)\s*[)\]]/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function cleanBaseTitle(value: string): string {
  let result = stripJunk(value);
  result = result.replace(
    /[([{]?\s*(?:feat\.?|ft\.?|with)\s+[^)\]}]+[)\]}]?/giu,
    "",
  );
  result = result.replace(
    /\s*[-–—]\s*(?:mono|stereo|remaster(?:ed)?(?:\s*\d{4})?|ремастеринг|live(?:\s+at[^)]+)?|acoustic|instrumental|radio\s+edit|single\s+version|original\s+mix|album\s+version)\b.*$/iu,
    "",
  );
  for (const { regex } of VERSION_PATTERNS) {
    result = result.replace(regex, "");
  }
  return normalizeTrackString(result);
}

export function cleanTitle(value: string): string {
  return cleanBaseTitle(value);
}

export function tokens(value: string): Set<string> {
  return new Set(
    cleanBaseTitle(value)
      .split(" ")
      .filter((token) => token.length >= 1),
  );
}

export function overlap(left: string, right: string): number {
  const a = tokens(left);
  const b = tokens(right);
  if (!a.size || !b.size) return 0;
  const common = [...a].filter((token) => b.has(token)).length;
  return common / new Set([...a, ...b]).size;
}
