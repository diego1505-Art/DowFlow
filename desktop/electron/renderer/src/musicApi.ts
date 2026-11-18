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

export interface LocalMusicFile {
  filename: string;
  title: string;
  artist: string;
  audio_url: string;
  cover_url: string | null;
  size: number;
  mtime: number;
}

interface FavoritesResponse {
  success: boolean;
  items?: StoredMusicFavorite[];
}

interface RemoveFavoriteResponse {
  success: boolean;
  removed?: boolean;
}

interface LibraryResponse {
  success: boolean;
  items?: LocalMusicFile[];
}

interface LocalFavoritesResponse {
  success: boolean;
  items?: string[];
}

const STREAM_FAVORITES_URL = "/api/music/stream/favorites";
const LOCAL_FAVORITES_URL = "/api/music/favorites";

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
  const statusText = `${response.status} ${response.statusText || "requête refusée"}`;
  return new Error(detail ? `${detail} (${statusText})` : `Erreur API (${statusText}).`);
}

async function readJson<T>(response: Response, label: string): Promise<T> {
  if (!response.ok) throw await responseError(response);
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error(`La réponse de l’API ${label} est invalide (JSON attendu).`);
  }
}

export async function fetchMusicLibrary(signal?: AbortSignal): Promise<LocalMusicFile[]> {
  const response = await fetch("/api/music/library", {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  const body = await readJson<LibraryResponse>(response, "bibliothèque");
  if (body.success !== true || !Array.isArray(body.items)) {
    throw new Error("La réponse de l’API bibliothèque ne contient pas de liste valide.");
  }
  return body.items;
}

export async function fetchLocalMusicFavorites(signal?: AbortSignal): Promise<string[]> {
  const response = await fetch(LOCAL_FAVORITES_URL, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  const body = await readJson<LocalFavoritesResponse>(response, "favoris locaux");
  if (body.success !== true || !Array.isArray(body.items) || !body.items.every((item) => typeof item === "string")) {
    throw new Error("La réponse de l’API favoris locaux ne contient pas de liste valide.");
  }
  return body.items;
}

export async function addLocalMusicFavorite(filename: string): Promise<void> {
  const response = await fetch(LOCAL_FAVORITES_URL, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ filename }),
  });
  if (!response.ok) throw await responseError(response);
}

export async function removeLocalMusicFavorite(filename: string): Promise<void> {
  const response = await fetch(`${LOCAL_FAVORITES_URL}/${encodeURIComponent(filename)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw await responseError(response);
}

export async function fetchMusicFavorites(signal?: AbortSignal): Promise<StoredMusicFavorite[]> {
  const response = await fetch(STREAM_FAVORITES_URL, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  const body = await readJson<FavoritesResponse>(response, "favoris streaming");
  if (body.success !== true || !Array.isArray(body.items)) {
    throw new Error("La réponse de l’API favoris streaming ne contient pas de liste valide.");
  }
  return body.items;
}

export async function addMusicFavorite(favorite: SaveMusicFavorite): Promise<void> {
  const response = await fetch(STREAM_FAVORITES_URL, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(favorite),
  });
  if (!response.ok) throw await responseError(response);
}

export async function removeMusicFavorite(trackId: string): Promise<boolean> {
  const response = await fetch(`${STREAM_FAVORITES_URL}/youtube/${encodeURIComponent(trackId)}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  const body = await readJson<RemoveFavoriteResponse>(response, "favoris streaming");
  if (body.success !== true || typeof body.removed !== "boolean") {
    throw new Error("La réponse de suppression des favoris streaming est invalide.");
  }
  return body.removed;
}
