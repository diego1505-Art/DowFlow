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

export interface MusicSettings {
  download_root: string | null;
  cookies_dir: string;
  cookies: string[];
}

export interface StartMusicDownload {
  id: string;
  title: string;
  artist: string;
}

export interface StartedMusicDownload {
  success: true;
  async: true;
  job_id: string;
}

export type MusicDownloadJobStatus = "queued" | "running" | "success" | "failed" | "skipped" | (string & {});

export interface MusicDownloadJob {
  status: MusicDownloadJobStatus;
  progress?: number | null;
  message?: string | null;
  error?: string | null;
  result?: unknown;
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

interface StartMusicDownloadResponse {
  success: boolean;
  async?: boolean;
  job_id?: string;
}

interface MusicDownloadJobResponse {
  success: boolean;
  job?: MusicDownloadJob;
}

interface MusicSettingsResponse {
  success: boolean;
  download_root?: string | null;
  cookies_dir?: string;
  cookies?: string[];
}

interface ChooseRootResponse {
  success: boolean;
  cancelled?: boolean;
  path?: string;
}

interface ImportCookiesResponse {
  success: boolean;
  cancelled?: boolean;
  filename?: string;
  domains?: string[];
}

const STREAM_FAVORITES_URL = "/api/music/stream/favorites";
const LOCAL_FAVORITES_URL = "/api/music/favorites";
const MUSIC_DOWNLOAD_URL = "/api/music/download";

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

export async function fetchMusicSettings(signal?: AbortSignal): Promise<MusicSettings> {
  const response = await fetch("/api/music/settings", {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  const body = await readJson<MusicSettingsResponse>(response, "paramètres Music");
  if (body.success !== true) {
    throw new Error("La réponse des paramètres Music est invalide.");
  }
  return {
    download_root: typeof body.download_root === "string" ? body.download_root : null,
    cookies_dir: typeof body.cookies_dir === "string" ? body.cookies_dir : "",
    cookies: Array.isArray(body.cookies)
      ? body.cookies.filter((name): name is string => typeof name === "string")
      : [],
  };
}

export async function chooseDownloadRoot(): Promise<string | null> {
  const response = await fetch("/api/download-folder/select", {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  const body = await readJson<ChooseRootResponse>(response, "dossier racine");
  if (body.cancelled) return null;
  if (body.success !== true || typeof body.path !== "string") {
    throw new Error("Le dossier racine n’a pas pu être enregistré.");
  }
  return body.path;
}

export async function importMusicCookies(): Promise<{ filename: string; domains: string[] } | null> {
  const response = await fetch("/api/music/cookies/import", {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  const body = await readJson<ImportCookiesResponse>(response, "importation des cookies");
  if (body.cancelled) return null;
  if (body.success !== true || typeof body.filename !== "string") {
    throw new Error("Les cookies n’ont pas pu être importés.");
  }
  return {
    filename: body.filename,
    domains: Array.isArray(body.domains)
      ? body.domains.filter((domain): domain is string => typeof domain === "string")
      : [],
  };
}

export async function startMusicDownload(track: StartMusicDownload): Promise<StartedMusicDownload> {
  const response = await fetch(MUSIC_DOWNLOAD_URL, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      url: `https://www.youtube.com/watch?v=${encodeURIComponent(track.id)}`,
      title: track.title,
      artist: track.artist,
      audio_format: "mp3",
      with_cover: true,
    }),
  });
  const body = await readJson<StartMusicDownloadResponse>(response, "téléchargement Music");
  if (body.success !== true || body.async !== true || typeof body.job_id !== "string" || !body.job_id) {
    throw new Error("La réponse de démarrage du téléchargement Music est invalide.");
  }
  return { success: true, async: true, job_id: body.job_id };
}

export async function fetchMusicDownloadJob(jobId: string, signal?: AbortSignal): Promise<MusicDownloadJob> {
  const response = await fetch(`/jobs/${encodeURIComponent(jobId)}`, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  const body = await readJson<MusicDownloadJobResponse>(response, "état du téléchargement Music");
  if (body.success !== true || !body.job || typeof body.job.status !== "string") {
    throw new Error("La réponse de suivi du téléchargement Music est invalide.");
  }
  return body.job;
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
