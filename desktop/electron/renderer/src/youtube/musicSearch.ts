// Adapted for private DowFlow use from Liner commit 5bec3c7; no Liner API fallback.
import { collectByKey } from "./json";
import { mapInnertubeTrack } from "./innertubeTrackMapper";
import { getClientVisitorData, resetVisitorData } from "./visitorSession";
import type { MusicTrack } from "../types";

const CLIENT_VERSION = "1.20260911.08.00";
const TRACK_PARAMS = "EgWKAQIIAWoKEAkQBRAKEAMQBA%3D%3D";
const SEARCH_URL = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false";

async function postSearch(query: string, visitorData: string, signal?: AbortSignal): Promise<Response> {
  const requestSignal = signal
    ? AbortSignal.any([signal, AbortSignal.timeout(12_000)])
    : AbortSignal.timeout(12_000);
  return fetch(SEARCH_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
      "x-youtube-client-name": "67",
      "x-youtube-client-version": CLIENT_VERSION,
      "x-origin": "https://music.youtube.com",
      ...(visitorData ? { "x-goog-visitor-id": visitorData } : {}),
    },
    body: JSON.stringify({
      query,
      params: TRACK_PARAMS,
      context: {
        client: {
          clientName: "WEB_REMIX",
          clientVersion: CLIENT_VERSION,
          hl: "en",
          gl: "US",
          ...(visitorData ? { visitorData } : {}),
        },
        user: { lockedSafetyMode: false },
      },
    }),
    signal: requestSignal,
  });
}

export async function searchMusicTracks(query: string, signal?: AbortSignal): Promise<MusicTrack[]> {
  const normalized = query.trim();
  if (normalized.length < 2) return [];

  let visitorData = await getClientVisitorData();
  let response = await postSearch(normalized, visitorData, signal);
  if (response.status === 401 || response.status === 403) {
    resetVisitorData();
    visitorData = await getClientVisitorData();
    response = await postSearch(normalized, visitorData, signal);
  }
  if (response.status === 403) {
    throw new Error("YouTube Music a temporairement refusé cette requête (403). Réessaie plus tard ou vérifie ta connexion.");
  }
  if (!response.ok) throw new Error(`YouTube Music search failed (HTTP ${response.status}).`);

  const body: unknown = await response.json();
  const seen = new Set<string>();
  return collectByKey(body, "musicResponsiveListItemRenderer")
    .map(mapInnertubeTrack)
    .filter((track): track is MusicTrack => {
      if (!track || !track.id || seen.has(track.id)) return false;
      seen.add(track.id);
      return true;
    });
}
