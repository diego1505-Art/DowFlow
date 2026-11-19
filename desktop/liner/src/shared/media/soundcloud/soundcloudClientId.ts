import { tryFetchText } from "@/shared/api/tryFetch";

const SOUNDCLOUD_HOME = "https://soundcloud.com";
const SCRIPT_URL =
  /src="((?:https:)?\/\/a-v2\.sndcdn\.com\/assets\/[^"]+\.js)"/g;
const CLIENT_ID_PATTERN = /client_id\s*[:=]\s*"([a-zA-Z0-9]{32})"/;

let cachedSoundCloudClientId: string | undefined;

export function rememberSoundCloudClientId(clientId: string): void {
  cachedSoundCloudClientId = clientId;
}

export function resetSoundCloudClientIdCache(): void {
  cachedSoundCloudClientId = undefined;
}

function scriptUrlsFromHtml(html: string): string[] {
  return [...html.matchAll(SCRIPT_URL)].map((match) =>
    match[1].startsWith("//") ? `https:${match[1]}` : match[1],
  );
}

async function discoverSoundCloudClientId(
  signal?: AbortSignal,
): Promise<string | undefined> {
  const html = await tryFetchText(SOUNDCLOUD_HOME, {
    headers: { accept: "text/html,application/xhtml+xml" },
    signal,
  });
  for (const scriptUrl of html ? scriptUrlsFromHtml(html).reverse() : []) {
    const found = (await tryFetchText(scriptUrl, { signal }))?.match(
      CLIENT_ID_PATTERN,
    )?.[1];
    if (found) {
      cachedSoundCloudClientId = found;
      return found;
    }
  }
  return undefined;
}

export async function getSoundCloudClientId(
  configuredClientId?: string,
  signal?: AbortSignal,
): Promise<string> {
  if (configuredClientId?.trim()) return configuredClientId.trim();
  if (cachedSoundCloudClientId) return cachedSoundCloudClientId;
  const discovered = await discoverSoundCloudClientId(signal);
  if (!discovered)
    throw new Error("SoundCloud is unavailable right now, try again later.");
  return discovered;
}

export async function refreshSoundCloudClientId(
  rejectedClientId: string,
  signal?: AbortSignal,
): Promise<string | undefined> {
  if (cachedSoundCloudClientId === rejectedClientId)
    cachedSoundCloudClientId = undefined;
  const discovered = await discoverSoundCloudClientId(signal);
  return discovered && discovered !== rejectedClientId ? discovered : undefined;
}
