export type MusicFavoriteSource = "youtube" | "local";

export interface StoredMusicFavorite {
  source: MusicFavoriteSource;
  track_id: string;
  title: string;
  artist: string;
  cover_url: string | null;
  duration_ms: number | null;
  created_at: number;
}

export interface SaveMusicFavorite {
  source: "youtube";
  track_id: string;
  title: string;
  artist: string;
  cover_url: string;
  duration_ms: number;
}

interface FavoritesResponse {
  success: boolean;
  items?: StoredMusicFavorite[];
}

interface RemoveFavoriteResponse {
  success: boolean;
  removed?: boolean;
}

const FAVORITES_URL = "/api/music/stream/favorites";

async function responseError(response: Response): Promise<Error> {
  let detail = "";
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object") {
      const record = body as Record<string, unknown>;
      const message = record.error ?? record.message ?? record.detail;
      if (typeof message === "string") detail = message;
    }
  } catch {
    // A non-JSON response is still reported with its HTTP status below.
  }
  return new Error(detail || `Erreur API (${response.status} ${response.statusText || "requête refusée"}).`);
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw await responseError(response);
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error("La réponse de l’API favoris est invalide (JSON attendu).");
  }
}

export async function fetchMusicFavorites(signal?: AbortSignal): Promise<StoredMusicFavorite[]> {
  const response = await fetch(FAVORITES_URL, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  const body = await readJson<FavoritesResponse>(response);
  if (body.success !== true || !Array.isArray(body.items)) {
    throw new Error("La réponse de l’API favoris ne contient pas de liste valide.");
  }
  return body.items;
}

export async function addMusicFavorite(favorite: SaveMusicFavorite): Promise<void> {
  const response = await fetch(FAVORITES_URL, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(favorite),
  });
  if (!response.ok) throw await responseError(response);
  // The backend contract does not require a response body for successful writes.
}

export async function removeMusicFavorite(trackId: string): Promise<boolean> {
  const response = await fetch(`${FAVORITES_URL}/youtube/${encodeURIComponent(trackId)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  const body = await readJson<RemoveFavoriteResponse>(response);
  if (body.success !== true || typeof body.removed !== "boolean") {
    throw new Error("La réponse de suppression des favoris est invalide.");
  }
  return body.removed;
}
