const USER_ID = /^sc_user_(\d+)$/;
const PLAYLIST_ID = /^sc_playlist_(\d+)$/;

export function soundCloudTrackId(id: number | string): string {
  return `sc:${id}`;
}

export function soundCloudUserId(id: number | string): string {
  return `sc_user_${id}`;
}

export function soundCloudPlaylistId(id: number | string): string {
  return `sc_playlist_${id}`;
}

export function parseSoundCloudUserId(id: string): string | null {
  return USER_ID.exec(id.trim())?.[1] ?? null;
}

export function parseSoundCloudPlaylistId(id: string): string | null {
  return PLAYLIST_ID.exec(id.trim())?.[1] ?? null;
}

export function isSoundCloudCatalogId(id: string): boolean {
  return /^sc[:_]/i.test(id.trim());
}
