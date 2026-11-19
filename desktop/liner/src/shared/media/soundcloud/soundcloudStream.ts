import {
  fetchSoundCloudApi,
  type SoundCloudRequestOptions,
} from "./soundcloudApi";
import { downloadHlsAudio } from "./soundcloudHls";
import {
  parseSoundCloudTrack,
  toSoundCloudTrackId,
  type SoundCloudTrackInfo,
  type SoundCloudTranscoding,
} from "./soundcloudTrack";
import {
  playableTranscodings,
  SoundCloudUnavailableError,
  transcodingFormat,
  type SoundCloudCodec,
} from "./soundcloudTranscodings";
import { signedUrlExpiry } from "./signedUrlExpiry";

interface SoundCloudStreamFormat {
  mimeType: string;
  codec: SoundCloudCodec;
  bitrate: number;
}

export interface SoundCloudUrlStream extends SoundCloudStreamFormat {
  url: string;
  expiresAt: string | null;
  contentLength?: number;
  blob?: undefined;
}

export interface SoundCloudBufferedStream extends SoundCloudStreamFormat {
  blob: Blob;
  expiresAt: null;
  contentLength: number;
  url?: undefined;
}

export type ResolvedSoundCloudStream =
  SoundCloudUrlStream | SoundCloudBufferedStream;

const UNSIGNED_URL_TTL_MS = 4 * 60_000;

async function lookupTrack(
  soundCloudId: string,
  options: SoundCloudRequestOptions,
): Promise<SoundCloudTrackInfo> {
  const response = await fetchSoundCloudApi(
    `/tracks/${soundCloudId}`,
    {},
    options,
  );
  if (response.status === 404 || response.status === 410)
    throw new SoundCloudUnavailableError("not_found");
  if (response.status === 403) throw new SoundCloudUnavailableError("blocked");
  if (!response.ok)
    throw new Error(`SoundCloud track lookup returned HTTP ${response.status}`);
  const track = parseSoundCloudTrack(await response.json());
  if (!track) throw new SoundCloudUnavailableError("not_found");
  return track;
}

async function transcodingMediaUrl(
  track: SoundCloudTrackInfo,
  transcoding: SoundCloudTranscoding,
  options: SoundCloudRequestOptions,
): Promise<string> {
  const params: Record<string, string> = track.trackAuthorization
    ? { track_authorization: track.trackAuthorization }
    : {};
  const response = await fetchSoundCloudApi(transcoding.url, params, options);
  if (!response.ok)
    throw new Error(`SoundCloud stream url returned HTTP ${response.status}`);
  const body: unknown = await response.json();
  const url =
    typeof body === "object" && body !== null && "url" in body
      ? body.url
      : undefined;
  if (typeof url !== "string" || !url)
    throw new Error("SoundCloud stream url response has no url");
  return url;
}

function urlExpiry(url: string): string {
  const signed = signedUrlExpiry(url);
  const now = Date.now();
  return new Date(
    signed && signed.getTime() > now
      ? signed.getTime()
      : now + UNSIGNED_URL_TTL_MS,
  ).toISOString();
}

async function openTranscoding(
  track: SoundCloudTrackInfo,
  transcoding: SoundCloudTranscoding,
  options: SoundCloudRequestOptions,
): Promise<ResolvedSoundCloudStream> {
  const format = transcodingFormat(transcoding);
  const mediaUrl = await transcodingMediaUrl(track, transcoding, options);
  if (transcoding.protocol === "progressive") {
    return { ...format, url: mediaUrl, expiresAt: urlExpiry(mediaUrl) };
  }
  const bytes = await downloadHlsAudio(mediaUrl, { signal: options.signal });
  return {
    ...format,
    blob: new Blob([bytes], { type: format.mimeType }),
    expiresAt: null,
    contentLength: bytes.byteLength,
  };
}

export async function resolveSoundCloudStream(
  trackId: string,
  options: SoundCloudRequestOptions = {},
): Promise<ResolvedSoundCloudStream> {
  const soundCloudId = toSoundCloudTrackId(trackId);
  if (!soundCloudId) throw new SoundCloudUnavailableError("not_found");
  const track = await lookupTrack(soundCloudId, options);
  let lastError: unknown = new SoundCloudUnavailableError(
    "no_playable_transcoding",
  );
  for (const transcoding of playableTranscodings(track)) {
    try {
      return await openTranscoding(track, transcoding, options);
    } catch (error) {
      if (options.signal?.aborted) throw error;
      lastError = error;
    }
  }
  throw lastError;
}
