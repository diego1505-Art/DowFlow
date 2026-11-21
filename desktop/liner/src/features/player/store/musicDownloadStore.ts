import { create } from "zustand";
import { createTranslatorSync, getStoredLocale } from "@/languages";
import { showToast } from "@/shared/ui";

export type MusicDownloadStatus = "running" | "success" | "failed";

export interface MusicDownloadEntry {
  trackId: string;
  jobId: string;
  title: string;
  artists: string;
  percent: number;
  status: MusicDownloadStatus;
  error?: string;
}

interface MusicDownloadState {
  downloads: Record<string, MusicDownloadEntry>;
  start: (entry: {
    trackId: string;
    jobId: string;
    title: string;
    artists: string;
  }) => void;
  markExisting: (entry: {
    trackId: string;
    title: string;
    artists: string;
  }) => void;
  update: (trackId: string, patch: Partial<MusicDownloadEntry>) => void;
  remove: (trackId: string) => void;
}

const POLL_INTERVAL_MS = 1_000;

function clampPercent(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.min(99, Math.max(0, value));
}

function hasRunning(downloads: Record<string, MusicDownloadEntry>): boolean {
  return Object.values(downloads).some((entry) => entry.status === "running");
}

let timer: ReturnType<typeof setTimeout> | null = null;
let polling = false;

function schedulePoll(): void {
  if (timer !== null) return;
  timer = setTimeout(() => {
    timer = null;
    void pollDownloads();
  }, POLL_INTERVAL_MS);
}

function notify(
  entry: MusicDownloadEntry,
  succeeded: boolean,
  error?: string,
): void {
  const t = createTranslatorSync(getStoredLocale());
  const description = entry.artists
    ? `${entry.title} — ${entry.artists}`
    : entry.title;
  showToast(t("common.download"), succeeded ? "checkmark" : "error", {
    description: succeeded ? description : error || t("common.download"),
  });
}

async function pollDownloads(): Promise<void> {
  if (polling) return;
  polling = true;
  try {
    const bridge =
      typeof window !== "undefined" ? window.linerElectron : undefined;
    if (typeof bridge?.downloadMusicStatus !== "function") return;
    const running = Object.values(
      useMusicDownloadStore.getState().downloads,
    ).filter((entry) => entry.status === "running");
    await Promise.all(
      running.map(async (entry) => {
        const state = await bridge
          .downloadMusicStatus(entry.jobId)
          .catch(() => null);
        if (!state) return;
        const store = useMusicDownloadStore.getState();
        if (state.status === "queued" || state.status === "running") {
          store.update(entry.trackId, {
            percent: clampPercent(state.progress),
          });
          return;
        }
        if (state.status === "success") {
          store.update(entry.trackId, { status: "success", percent: 100 });
          notify(entry, true);
          return;
        }
        const error = state.error || state.message || "";
        store.update(entry.trackId, { status: "failed", error });
        notify(entry, false, error);
      }),
    );
  } finally {
    polling = false;
    if (hasRunning(useMusicDownloadStore.getState().downloads)) schedulePoll();
  }
}

export const useMusicDownloadStore = create<MusicDownloadState>((set) => ({
  downloads: {},
  start: ({ trackId, jobId, title, artists }) => {
    set((state) => ({
      downloads: {
        ...state.downloads,
        [trackId]: {
          trackId,
          jobId,
          title,
          artists,
          percent: 0,
          status: "running",
        },
      },
    }));
    schedulePoll();
  },
  markExisting: ({ trackId, title, artists }) => {
    set((state) => ({
      downloads: {
        ...state.downloads,
        [trackId]: {
          trackId,
          jobId: "",
          title,
          artists,
          percent: 100,
          status: "success",
        },
      },
    }));
  },
  update: (trackId, patch) => {
    set((state) => {
      const current = state.downloads[trackId];
      if (!current) return state;
      return {
        downloads: {
          ...state.downloads,
          [trackId]: { ...current, ...patch },
        },
      };
    });
  },
  remove: (trackId) => {
    set((state) => {
      const downloads = { ...state.downloads };
      delete downloads[trackId];
      return { downloads };
    });
  },
}));
