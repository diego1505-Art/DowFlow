import type { Cover } from "./cover";
import type { Track } from "./track";

export interface DailyMixItem {
  id: string;
  title: string;
  description: string;
  clusterArtists: string[];
  cover?: Cover;
  trackCount: number;
  tracks: Track[];
}

export interface DailyMixesResponse {
  items: DailyMixItem[];
  generatedAt: string;
}
