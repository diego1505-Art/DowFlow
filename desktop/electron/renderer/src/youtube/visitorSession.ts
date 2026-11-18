// Adapted for private DowFlow use from Liner commit 5bec3c7.
import { asArray } from "./json";

const VISITOR_DATA_PATTERN = /Cg[s-v][A-Za-z0-9_-]{20,}(?:%3D|=){0,2}/;
const SESSION_TTL_MS = 5.5 * 60 * 60 * 1000;
let cached: { value: string; expiresAt: number } | null = null;
let pending: Promise<string> | null = null;

function visitorDataFromJson(text: string): string | null {
  try {
    const body = text.startsWith(")]}'") ? text.slice(text.indexOf("\n") + 1) : text;
    const parsed = JSON.parse(body) as unknown;
    const value = asArray(asArray(asArray(asArray(asArray(parsed)[0])[2])[0])[0])[13];
    return typeof value === "string" && VISITOR_DATA_PATTERN.test(value) ? value : null;
  } catch {
    return null;
  }
}

function parseVisitorData(text: string): string {
  return visitorDataFromJson(text) ?? text.match(VISITOR_DATA_PATTERN)?.[0] ?? "";
}

export function resetVisitorData(): void {
  cached = null;
}

export async function getClientVisitorData(): Promise<string> {
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  if (pending) return pending;
  pending = (async () => {
    try {
      const response = await fetch("https://www.youtube.com/sw.js_data", {
        signal: AbortSignal.timeout(8_000),
      });
      if (!response.ok) throw new Error(`YouTube visitor session returned ${response.status}`);
      const value = parseVisitorData(await response.text());
      if (value) cached = { value, expiresAt: Date.now() + SESSION_TTL_MS };
      return value;
    } catch {
      return cached?.value ?? "";
    } finally {
      pending = null;
    }
  })();
  return pending;
}
