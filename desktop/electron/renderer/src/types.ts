export interface TrackArtist {
  id: string;
  name: string;
}

export interface Cover {
  url: string;
  width: number;
  height: number;
}

export interface MusicTrack {
  id: string;
  title: string;
  artists: TrackArtist[];
  album?: { id: string; title: string };
  durationMs: number;
  cover: Cover;
  explicit?: boolean;
}

declare global {
  interface Window {
    dowflow?: {
      youtube?: {
        mintPoToken?: (identifier: string) => Promise<string>;
      };
    };
  }
}
