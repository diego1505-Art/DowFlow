import { asArray, asRecord, type JsonRecord } from "@/shared/utils/json";
import { rethrowIfAborted } from "@/shared/utils/abort";
import { fetchSoundCloudApi } from "./soundcloudApi";

const STUB_CHUNK_SIZE = 50;

function stubIds(rawTracks: JsonRecord[]): number[] {
  return rawTracks.flatMap((track) =>
    typeof track.id === "number" && typeof track.title !== "string"
      ? [track.id]
      : [],
  );
}

async function fetchChunk(
  chunkIds: number[],
  hydrated: Map<string, JsonRecord>,
  signal?: AbortSignal,
) {
  const response = await fetchSoundCloudApi(
    "/tracks",
    { ids: chunkIds.join(",") },
    { signal },
  );
  if (!response.ok) return;
  for (const track of asArray((await response.json()) as unknown).map(
    asRecord,
  )) {
    if (track && typeof track.id === "number")
      hydrated.set(String(track.id), track);
  }
}

export async function hydrateSoundCloudStubs(
  rawTracks: JsonRecord[],
  signal?: AbortSignal,
): Promise<JsonRecord[]> {
  const ids = stubIds(rawTracks);
  const hydrated = new Map<string, JsonRecord>();
  for (let start = 0; start < ids.length; start += STUB_CHUNK_SIZE) {
    try {
      await fetchChunk(
        ids.slice(start, start + STUB_CHUNK_SIZE),
        hydrated,
        signal,
      );
    } catch {
      rethrowIfAborted(signal);
    }
  }
  return rawTracks.map((track) =>
    typeof track.id === "number"
      ? (hydrated.get(String(track.id)) ?? track)
      : track,
  );
}
