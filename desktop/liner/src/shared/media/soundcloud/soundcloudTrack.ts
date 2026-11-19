export interface SoundCloudTranscoding {
  url: string;
  preset: string;
  protocol: string;
  mimeType: string;
  snipped: boolean;
}

export interface SoundCloudTrackInfo {
  id: number;
  policy: string;
  streamable: boolean;
  durationMs?: number;
  fullDurationMs?: number;
  trackAuthorization?: string;
  transcodings: SoundCloudTranscoding[];
}

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function positiveNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : undefined;
}

function parseTranscoding(raw: unknown): SoundCloudTranscoding | null {
  if (!isObject(raw)) return null;
  const url = text(raw.url);
  const format = isObject(raw.format) ? raw.format : {};
  const protocol = text(format.protocol);
  if (!url || !protocol) return null;
  return {
    url,
    preset: text(raw.preset) ?? "",
    protocol,
    mimeType: (text(format.mime_type) ?? "").toLowerCase(),
    snipped: raw.snipped === true,
  };
}

export function parseSoundCloudTrack(raw: unknown): SoundCloudTrackInfo | null {
  if (!isObject(raw) || typeof raw.id !== "number") return null;
  const media = isObject(raw.media) ? raw.media : {};
  const transcodings = Array.isArray(media.transcodings)
    ? media.transcodings
    : [];
  return {
    id: raw.id,
    policy: (text(raw.policy) ?? "ALLOW").toUpperCase(),
    streamable: raw.streamable !== false,
    durationMs: positiveNumber(raw.duration),
    fullDurationMs: positiveNumber(raw.full_duration),
    trackAuthorization: text(raw.track_authorization),
    transcodings: transcodings
      .map(parseTranscoding)
      .filter((item): item is SoundCloudTranscoding => item !== null),
  };
}

export function toSoundCloudTrackId(trackId: string): string | null {
  const trimmed = trackId.trim();
  const match = /^(?:sc:|soundcloud:(?:tracks?:)?)?(\d+)$/.exec(trimmed);
  return match ? match[1] : null;
}
