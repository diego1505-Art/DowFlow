export const VERSION_PATTERNS: Array<{ tag: string; regex: RegExp }> = [
  { tag: "remix", regex: /\b(remix(?:ed)?|ремикс|rmx)\b/i },
  { tag: "vip", regex: /\b(vip|v\.i\.p\.?)\b/i },
  { tag: "flip", regex: /\b(flip|флип)\b/i },
  { tag: "bootleg", regex: /\b(bootleg|бутлег)\b/i },
  { tag: "mashup", regex: /\b(mash\s*up|мэшап|мешап)\b/i },
  { tag: "edit", regex: /\b((?:radio|club|extended)?\s*edit|эдит)\b/i },
  { tag: "slowed", regex: /\b(slowed(?:\s*(?:\+|&|and)\s*reverb)?|слоу)\b/i },
  { tag: "reverb", regex: /\b(reverb|реверб)\b/i },
  {
    tag: "sped_up",
    regex: /\b(sp(?:ed|eed)\s*up|sp(?:ed|eed)up|спид\s*ап|спидап)\b/i,
  },
  { tag: "nightcore", regex: /\b(nightcore|найткор)\b/i },
  { tag: "instrumental", regex: /\b(instrumental|инструментал|inst\b\.?)\b/i },
  { tag: "acoustic", regex: /\b(acoustic|акустика)\b/i },
  { tag: "live", regex: /\b(live(?:\s+at[^)]+)?|лайв|концерт)\b/i },
  { tag: "cover", regex: /\b(cover|кавер)\b/i },
  { tag: "bass_boosted", regex: /\b(bass\s*boost(?:ed)?|басс\s*буст)\b/i },
];

export function getVersionTags(value: string): Set<string> {
  const tags = new Set<string>();
  for (const { tag, regex } of VERSION_PATTERNS) {
    if (regex.test(value)) tags.add(tag);
  }
  return tags;
}

export function getVersionTag(value: string): string | null {
  const tags = getVersionTags(value);
  return tags.size > 0 ? Array.from(tags)[0] : null;
}

export interface VersionComparison {
  matches: boolean;
  penalty: number;
  bonus: number;
}

export function compareVersionTags(
  sourceTags: Set<string>,
  candidateTags: Set<string>,
): VersionComparison {
  if (sourceTags.size === 0 && candidateTags.size === 0) {
    return { matches: true, penalty: 0, bonus: 5 };
  }
  if (sourceTags.size > 0 && candidateTags.size > 0) {
    const hasCommon = [...sourceTags].some((tag) => candidateTags.has(tag));
    return hasCommon
      ? { matches: true, penalty: 0, bonus: 15 }
      : { matches: false, penalty: 50, bonus: 0 };
  }
  return { matches: false, penalty: 50, bonus: 0 };
}
