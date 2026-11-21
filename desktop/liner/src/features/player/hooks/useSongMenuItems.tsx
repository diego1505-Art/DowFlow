import { useCallback } from "react";
import {
  LuRadio,
  LuStepForward,
  LuListPlus,
  LuHeart,
  LuPlus,
  LuTrash2,
  LuFolderPlus,
  LuEraser,
  LuDownload,
  LuCheck,
} from "react-icons/lu";
import { ShareForwardLine } from "@mingcute/react";
import type { DropdownMenuItem } from "@/shared/ui/DropdownMenu";
import { playerEngine } from "../engine/playerEngine";
import {
  usePlaylistsList,
  useToggleTrackLike,
  useIsTrackLiked,
  useModalStore,
} from "@/features/library";
import { useTranslation } from "@/languages";
import { showToast } from "@/shared/ui";
import { buildShareUrl } from "@/shared/utils/share";
import { toVideoId } from "@/shared/youtube";
import { findYoutubeStandIn } from "../engine/youtubeStandIn";
import { isLocalTrackId } from "@/shared/media/local";
import { useIsTrackCached } from "@/features/library/cached/hooks/useIsTrackCached";
import { removeTrackFromCache } from "@/shared/utils/cacheManager";
import { useMusicDownloadStore } from "../store/musicDownloadStore";

const CLOUD_ONLY_ITEMS = new Set([
  "start-radio",
  "like-track",
  "unlike-track",
  "add-to-playlist",
  "remove-from-playlist",
  "share",
  "download-audio",
]);

export interface SongMenuContext {
  id?: string;
  title: string;
  artists: string;
  coverUrl: string;
  duration?: string;
  durationMs?: number;
  searchType?: "track" | "album" | "artist" | "playlist";
  totalTracks?: number;
  playlistId?: string;
  playlistItemId?: string;
  playlistTitle?: string;
  /** play queue rows: adds "Remove from queue" (the queue animates the row out) */
  onRemoveFromQueue?: () => void;
  onRemoveFromDevice?: () => void;
}

export function useSongMenuItems(ctx: SongMenuContext): DropdownMenuItem[] {
  const { t } = useTranslation();
  const {
    id,
    title,
    artists,
    coverUrl,
    duration,
    durationMs,
    searchType,
    totalTracks,
    playlistId,
    playlistItemId,
    playlistTitle,
    onRemoveFromQueue,
    onRemoveFromDevice,
  } = ctx;

  const { data: playlistsData } = usePlaylistsList();

  const toggleLike = useToggleTrackLike();

  const liked = useIsTrackLiked(id);

  const isTrack = searchType === "track" || !searchType;
  const cached = useIsTrackCached(isTrack ? id : undefined);

  const handleRemoveFromCache = useCallback(() => {
    if (!id) return;
    void removeTrackFromCache(id).then(() => {
      showToast(t("common.removed_from_cache"), "checkmark", {
        description: artists ? `${title} — ${artists}` : title,
      });
    });
  }, [id, title, artists, t]);

  const handleLike = useCallback(() => {
    if (!id) return;
    toggleLike(id);
  }, [id, toggleLike]);

  const download = useMusicDownloadStore((state) =>
    id ? state.downloads[id] : undefined,
  );
  const startMusicDownload = useMusicDownloadStore((state) => state.start);
  const markMusicDownloaded = useMusicDownloadStore(
    (state) => state.markExisting,
  );

  const handleDownload = useCallback(async () => {
    if (!id || download?.status === "running") return;
    const bridge =
      typeof window !== "undefined" ? window.linerElectron : undefined;
    if (!bridge?.downloadMusic) {
      showToast(t("common.download"), "error", {
        description: "Open the DowFlow app to download this track.",
      });
      return;
    }
    try {
      const videoId =
        toVideoId(id) ??
        (await findYoutubeStandIn({
          id,
          title,
          artists,
          durationMs: durationMs ?? 0,
        }));
      if (!videoId) {
        showToast(t("common.download"), "error", {
          description: "No YouTube link found for this track.",
        });
        return;
      }
      const result = await bridge.downloadMusic({
        url: `https://www.youtube.com/watch?v=${videoId}`,
        title,
        artist: artists,
      });
      if (!result?.success) {
        showToast(t("common.download"), "error", {
          description: result?.error || "Download failed.",
        });
        return;
      }
      // DowFlow already has this track: do not download a second copy.
      if (result.existing || !result.jobId) {
        markMusicDownloaded({ trackId: id, title, artists });
        showToast(t("common.download"), "checkmark", {
          description: artists ? `${title} — ${artists}` : title,
        });
        return;
      }
      startMusicDownload({
        trackId: id,
        jobId: result.jobId,
        title,
        artists,
      });
    } catch (error) {
      showToast(t("common.download"), "error", {
        description:
          error instanceof Error ? error.message : "Download failed.",
      });
    }
  }, [
    artists,
    download?.status,
    durationMs,
    id,
    markMusicDownloaded,
    startMusicDownload,
    title,
    t,
  ]);

  const handleShare = useCallback(() => {
    if (!id) return;
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      const type =
        (searchType as "track" | "album" | "artist" | "playlist") || "track";
      void navigator.clipboard.writeText(buildShareUrl(type, id));
      showToast(t("common.link_copied"), "checkmark", {
        description: artists ? `${title} — ${artists}` : title,
      });
    }
  }, [id, searchType, title, artists, t]);

  const downloading = download?.status === "running";
  const downloaded = download?.status === "success";
  const downloadPercent = Math.round(download?.percent ?? 0);
  const downloadLabel = downloading
    ? `${t("common.downloading")} ${downloadPercent} %`
    : t("common.download");

  const buildMenu = useCallback((): DropdownMenuItem[] => {
    const isTrack = searchType === "track" || !searchType;

    if (isTrack) {
      if (playlistId) {
        return [
          {
            id: "start-radio",
            label: t("common.start_radio"),
            icon: <LuRadio size={15} />,
            onClick: () => {
              if (!id) return;
              void playerEngine.startRadioStation({
                id,
                title,
                artists,
                coverUrl,
                durationMs: durationMs ?? 0,
                playCount: 0,
              });
            },
          },
          {
            id: "play-next",
            label: t("common.play_next"),
            icon: <LuStepForward size={15} />,
            onClick: () => {
              if (!id) return;
              playerEngine.playNext({
                id,
                title,
                artists,
                coverUrl,
                durationMs: durationMs ?? 0,
                playCount: 0,
              });
            },
          },
          {
            id: "add-to-queue",
            label: t("common.add_to_queue"),
            icon: <LuListPlus size={15} />,
            onClick: () => {
              if (!id) return;
              playerEngine.addToQueue({
                id,
                title,
                artists,
                coverUrl,
                durationMs: durationMs ?? 0,
                playCount: 0,
              });
              showToast(t("common.added_to_queue"), "checkmark", {
                description: artists ? `${title} — ${artists}` : title,
              });
            },
          },
          {
            id: liked ? "unlike-track" : "like-track",
            label: liked ? t("common.unlike") : t("common.like"),
            icon: (
              <LuHeart
                size={15}
                className={
                  liked ? "fill-red-500 text-red-500" : "text-text-secondary"
                }
              />
            ),
            onClick: handleLike,
          },
          {
            id: "download-audio",
            label: downloadLabel,
            icon: downloaded ? <LuCheck size={15} /> : <LuDownload size={15} />,
            progress: downloading ? downloadPercent : undefined,
            keepOpen: true,
            onClick: () => void handleDownload(),
          },
          {
            id: "share",
            label: t("common.share"),
            icon: <ShareForwardLine size={15} />,
            onClick: handleShare,
          },
          {
            id: "remove-from-playlist",
            label: t("common.remove_from_playlist"),
            icon: <LuTrash2 size={15} />,
            danger: true,
            onClick: () => {
              if (!id) return;
              useModalStore.getState().openRemoveFromPlaylist({
                trackId: id,
                playlistItemId,
                trackTitle: title,
                trackArtists: artists,
                trackCoverUrl: coverUrl,
                playlistId,
                playlistTitle,
              });
            },
          },
        ];
      }

      return [
        {
          id: "start-radio",
          label: t("common.start_radio"),
          icon: <LuRadio size={15} />,
          onClick: () => {
            if (!id) return;
            void playerEngine.startRadioStation({
              id,
              title,
              artists,
              coverUrl,
              durationMs: durationMs ?? 0,
              playCount: 0,
            });
          },
        },
        {
          id: "play-next",
          label: t("common.play_next"),
          icon: <LuStepForward size={15} />,
          onClick: () => {
            if (!id) return;
            playerEngine.playNext({
              id,
              title,
              artists,
              coverUrl,
              durationMs: durationMs ?? 0,
              playCount: 0,
            });
          },
        },
        {
          id: "add-to-queue",
          label: t("common.add_to_queue"),
          icon: <LuListPlus size={15} />,
          onClick: () => {
            if (!id) return;
            playerEngine.addToQueue({
              id,
              title,
              artists,
              coverUrl,
              durationMs: durationMs ?? 0,
              playCount: 0,
            });
            showToast(t("common.added_to_queue"), "checkmark", {
              description: artists ? `${title} — ${artists}` : title,
            });
          },
        },
        {
          id: liked ? "unlike-track" : "like-track",
          label: liked ? t("common.unlike") : t("common.like"),
          icon: (
            <LuHeart
              size={15}
              className={
                liked ? "fill-red-500 text-red-500" : "text-text-secondary"
              }
            />
          ),
          onClick: handleLike,
        },
        {
          id: "add-to-playlist",
          label: t("common.add_to_playlist"),
          icon: <LuPlus size={15} />,
          onClick: () => {
            if (!id) return;
            useModalStore.getState().openAddToPlaylist({
              id,
              title,
              artists,
              coverUrl,
              duration,
              playlists: playlistsData?.playlists ?? [],
            });
          },
        },
        {
          id: "download-audio",
          label: downloadLabel,
          icon: downloaded ? <LuCheck size={15} /> : <LuDownload size={15} />,
          progress: downloading ? downloadPercent : undefined,
          keepOpen: true,
          onClick: () => void handleDownload(),
        },
        {
          id: "share",
          label: t("common.share"),
          icon: <ShareForwardLine size={15} />,
          onClick: handleShare,
        },
        ...(onRemoveFromQueue
          ? [
              {
                id: "remove-from-queue",
                label: t("common.remove_from_queue"),
                icon: <LuTrash2 size={15} />,
                danger: true,
                onClick: onRemoveFromQueue,
              },
            ]
          : []),
      ];
    }

    return [
      {
        id: "add-to-library",
        label: t("common.add_to_library"),
        icon: <LuFolderPlus size={15} />,
        onClick: () => {
          if (!id) return;
          useModalStore.getState().openAddToLibrary({
            id,
            title,
            coverUrl,
            type: (searchType as "album" | "artist" | "playlist") || "album",
            subtitle: artists,
            totalTracks,
          });
        },
      },
      {
        id: "share",
        label: t("common.share"),
        icon: <ShareForwardLine size={15} />,
        onClick: handleShare,
      },
    ];
  }, [
    id,
    title,
    artists,
    coverUrl,
    duration,
    durationMs,
    searchType,
    totalTracks,
    playlistId,
    playlistItemId,
    playlistTitle,
    onRemoveFromQueue,
    liked,
    downloadLabel,
    downloading,
    downloaded,
    downloadPercent,
    handleLike,
    handleDownload,
    handleShare,
    playlistsData,
    t,
  ]);

  const items = buildMenu();
  if (!isLocalTrackId(id)) {
    if (!cached) return items;
    const removeFromCacheItem: DropdownMenuItem = {
      id: "remove-from-cache",
      label: t("common.remove_from_cache"),
      icon: <LuEraser size={15} />,
      onClick: handleRemoveFromCache,
    };
    const firstDanger = items.findIndex((item) => item.danger);
    if (firstDanger === -1) return [...items, removeFromCacheItem];
    return [
      ...items.slice(0, firstDanger),
      removeFromCacheItem,
      ...items.slice(firstDanger),
    ];
  }
  const deviceItems = items.filter((item) => !CLOUD_ONLY_ITEMS.has(item.id));
  if (!onRemoveFromDevice) return deviceItems;
  return [
    ...deviceItems,
    {
      id: "remove-from-device",
      label: t("library.local.remove"),
      icon: <LuTrash2 size={15} />,
      danger: true,
      onClick: onRemoveFromDevice,
    },
  ];
}
