import { asArray, asRecord, type JsonRecord } from "@/shared/utils/json";
import { rethrowIfAborted } from "@/shared/utils/abort";
import { fetchSoundCloudApi } from "./soundcloudApi";

export class SoundCloudCatalogError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "SoundCloudCatalogError";
  }
}

export function requireId(id: string | null, entity: string): string {
  if (!id)
    throw new SoundCloudCatalogError(`${entity} is not a SoundCloud id.`, 400);
  return id;
}

export async function getJson(
  path: string,
  params: Record<string, string>,
  signal?: AbortSignal,
): Promise<JsonRecord> {
  const response = await fetchSoundCloudApi(path, params, { signal });
  if (!response.ok)
    throw new SoundCloudCatalogError(
      `SoundCloud ${path} failed.`,
      response.status,
    );
  const body = asRecord((await response.json()) as unknown);
  if (!body)
    throw new SoundCloudCatalogError(
      `SoundCloud ${path} returned no data.`,
      502,
    );
  return body;
}

export async function getCollection(
  path: string,
  limit: string,
  signal?: AbortSignal,
): Promise<unknown[]> {
  try {
    return asArray(
      (await getJson(path, { limit, linked_partitioning: "1" }, signal))
        .collection,
    );
  } catch {
    rethrowIfAborted(signal);
    return [];
  }
}
