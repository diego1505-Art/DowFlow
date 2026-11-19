import { normalizeTrackString } from "./phonetic";

export function levenshtein(a: string, b: string): number {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;

  const v0 = new Int32Array(b.length + 1);
  const v1 = new Int32Array(b.length + 1);
  for (let i = 0; i <= b.length; i++) v0[i] = i;

  for (let i = 0; i < a.length; i++) {
    v1[0] = i + 1;
    for (let j = 0; j < b.length; j++) {
      const cost = a[i] === b[j] ? 0 : 1;
      v1[j + 1] = Math.min(v1[j] + 1, v0[j + 1] + 1, v0[j] + cost);
    }
    for (let j = 0; j <= b.length; j++) v0[j] = v1[j];
  }

  return v0[b.length];
}

export function tokenSortRatio(a: string, b: string): number {
  const normA = normalizeTrackString(a);
  const normB = normalizeTrackString(b);
  if (!normA.length || !normB.length) return 0;
  if (normA === normB) return 100;

  const sortedA = normA.split(" ").filter(Boolean).sort().join(" ");
  const sortedB = normB.split(" ").filter(Boolean).sort().join(" ");
  if (sortedA === sortedB) return 100;

  const distance = levenshtein(sortedA, sortedB);
  const maxLength = Math.max(sortedA.length, sortedB.length);
  return Math.max(0, Math.round((1 - distance / maxLength) * 100));
}

export function tokenSetRatio(a: string, b: string): number {
  const normA = normalizeTrackString(a);
  const normB = normalizeTrackString(b);
  if (!normA || !normB) return 0;
  if (normA === normB) return 100;

  const setA = new Set(normA.split(" ").filter(Boolean));
  const setB = new Set(normB.split(" ").filter(Boolean));
  const intersection = [...setA].filter((token) => setB.has(token));
  if (intersection.length === 0) return 0;

  const minTokens = Math.min(setA.size, setB.size);
  const maxTokens = Math.max(setA.size, setB.size);
  if (setA.size === setB.size && intersection.length === setA.size) return 100;

  const coverage = (2 * intersection.length) / (setA.size + setB.size);
  let ratio = Math.round(coverage * 100);

  if (intersection.length === minTokens) {
    if (minTokens >= 2) {
      ratio = Math.max(ratio, Math.round((minTokens / maxTokens) * 35 + 55));
    } else if (
      minTokens === 1 &&
      intersection[0] &&
      intersection[0].length >= 5 &&
      minTokens / maxTokens >= 0.5
    ) {
      ratio = Math.max(ratio, 72);
    }
  }

  return ratio;
}
