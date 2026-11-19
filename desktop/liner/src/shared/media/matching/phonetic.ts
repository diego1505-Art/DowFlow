const CYR_TO_LAT: Record<string, string> = {
  а: "a",
  б: "b",
  в: "v",
  г: "g",
  д: "d",
  е: "e",
  ё: "e",
  ж: "zh",
  з: "z",
  и: "i",
  й: "y",
  к: "k",
  л: "l",
  м: "m",
  н: "n",
  о: "o",
  п: "p",
  р: "r",
  с: "s",
  т: "t",
  у: "u",
  ф: "f",
  х: "h",
  ц: "ts",
  ч: "ch",
  ш: "sh",
  щ: "shch",
  ъ: "",
  ы: "y",
  ь: "",
  э: "e",
  ю: "yu",
  я: "ya",
  є: "ye",
  і: "i",
  ї: "yi",
  ґ: "g",
};

export function toPhoneticLatin(value: string): string {
  let result = value.toLowerCase().replace(/ё/gi, "e");
  for (const [cyrillic, latin] of Object.entries(CYR_TO_LAT)) {
    result = result.replaceAll(cyrillic, latin);
  }
  return result
    .replace(/kh/g, "h")
    .replace(/[yj]/g, "i")
    .replace(/[w]/g, "v")
    .replace(/ph/g, "f")
    .replace(/oo/g, "u")
    .replace(/ee/g, "i")
    .replace(/z/g, "s")
    .replace(/e\b/g, "")
    .replace(/[^a-z0-9\s]/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function normalizeWords(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function normalizeTrackString(value: string): string {
  return normalizeWords(
    value.replace(/ё/gi, "е").replace(/\.(?:mp3|wav|flac|m4a|aac|ogg)\b/gi, ""),
  );
}
