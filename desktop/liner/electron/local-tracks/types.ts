export interface LocalTrackRecord {
  id: string;
  title: string;
  artist: string;
  album?: string;
  durationMs: number;
  fileName: string;
  audioFile: string;
  mimeType: string;
  coverFile?: string;
  byteSize: number;
  addedAt: number;
}

export interface LocalLibraryUsage {
  count: number;
  bytes: number;
}

export interface LocalImportResult {
  added: LocalTrackRecord[];
  duplicates: number;
  failed: string[];
}

export const LOCAL_AUDIO_EXTENSIONS = [
  "mp3",
  "flac",
  "m4a",
  "aac",
  "ogg",
  "opus",
  "wav",
  "webm",
  // DowFlow's downloader saves single videos (Shorts included) as mp4/m4v;
  // they are reported as tracks and played for their audio.
  "mp4",
  "m4v",
] as const;
