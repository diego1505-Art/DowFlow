import { useEffect, useState, type ReactNode } from "react";
import {
  HeartFill,
  Download2Line,
  FolderOpenLine,
  YoutubeFill,
} from "@mingcute/react";
import Button from "@/shared/ui/Button";
import { ToggleSwitch, useToast } from "@/shared/ui";
import { PresetPills } from "@/shared/ui/PresetPills";
import { useTranslation } from "@/languages";
import { LocalFilesIcon, useLocalLibraryStore } from "@/features/library/local";
import { useSavedTracksStore } from "@/features/library/saved";
import {
  formatStorageBytes,
  type StorageCategoryItem,
} from "@/shared/utils/cacheManager";
import { SettingRow, SettingSection } from "../controls";
import { StorageSizeAction } from "./StorageSizeAction";
import { StorageFolderButton } from "./StorageFolderButton";
import { useSongEstimate } from "./StorageOverview";

const GB = 1024 * 1024 * 1024;
const LIMIT_OPTIONS = [2, 5, 20, 0];

function RowIcon({ children }: { children: ReactNode }) {
  return (
    <span className="flex h-[36px] w-[36px] items-center justify-center rounded-control bg-fill text-text-secondary">
      {children}
    </span>
  );
}

export type StorageRemoveKind = "liked" | "local" | "shared";

export function StorageDownloadsSection({
  liked,
  local,
  shared,
  onRemove,
  songBytes,
  searchQuery,
}: {
  songBytes: number;
  liked?: StorageCategoryItem;
  local?: StorageCategoryItem;
  shared?: StorageCategoryItem;
  onRemove: (
    kind: StorageRemoveKind,
    bytes: number,
    remove: () => Promise<unknown>,
  ) => void;
  searchQuery?: string;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [downloadRoot, setDownloadRoot] = useState<string | null>(null);
  const [cookies, setCookies] = useState<string[]>([]);
  const [busy, setBusy] = useState<"cookies" | "root" | null>(null);
  const enabled = useSavedTracksStore((state) => state.enabled);
  const limitBytes = useSavedTracksStore((state) => state.limitBytes);
  const status = useSavedTracksStore((state) => state.status);
  const records = useSavedTracksStore((state) => state.records);
  const setEnabled = useSavedTracksStore((state) => state.setEnabled);
  const setLimitBytes = useSavedTracksStore((state) => state.setLimitBytes);
  const removeSaved = useSavedTracksStore((state) => state.removeAll);
  const removeLocal = useLocalLibraryStore((state) => state.removeAll);
  const removeShared = useSavedTracksStore((state) => state.removeShared);
  const sharedCount = useSavedTracksStore((state) => state.sharedCount);

  const limitSongs = useSongEstimate(limitBytes, songBytes);
  const savedCount = records.length;
  const likedBytes =
    records.length > 0
      ? records.reduce((sum, record) => sum + record.byteSize, 0)
      : (liked?.bytes ?? 0);
  const sharedBytes = sharedCount > 0 ? (shared?.bytes ?? 0) : 0;
  const localBytes = local?.bytes ?? 0;
  const localCount = local?.count ?? 0;

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const result = await window.linerElectron?.musicSettings?.();
      if (cancelled || !result?.success) return;
      setDownloadRoot(result.downloadRoot ?? null);
      setCookies(result.cookies ?? []);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const changeDownloadRoot = async () => {
    setBusy("root");
    try {
      const result = await window.linerElectron?.chooseDownloadRoot?.();
      if (result?.success && result.path) {
        setDownloadRoot(result.path);
        toast(t("settings.storage.download_root_changed"), "success");
        return;
      }
      if (!result?.cancelled) {
        toast(
          result?.error || t("settings.storage.download_root_error"),
          "error",
        );
      }
    } finally {
      setBusy(null);
    }
  };

  const importCookies = async () => {
    setBusy("cookies");
    try {
      const result = await window.linerElectron?.importCookies?.();
      if (result?.success) {
        const filename = result.filename || "cookies.txt";
        setCookies((current) =>
          Array.from(new Set([...current, filename])).sort(),
        );
        toast(t("settings.storage.cookies_imported", { filename }), "success");
        return;
      }
      if (!result?.cancelled) {
        toast(result?.error || t("settings.storage.cookies_error"), "error");
      }
    } finally {
      setBusy(null);
    }
  };

  const openDownloadRoot = async () => {
    const result = await window.linerElectron?.openDownloadRoot?.();
    if (!result?.success) {
      toast(result?.error || t("settings.storage.open_folder_failed"), "error");
    }
  };

  const likedDescription = (() => {
    if (!enabled) return t("settings.storage.liked_status.disabled");
    switch (status.phase) {
      case "saving":
        return t("settings.storage.liked_status.saving", {
          count: status.pending,
        });
      case "starting":
        return t("settings.storage.liked_status.starting");
      case "waiting":
        return t("settings.storage.liked_status.waiting", {
          time: new Date(status.resumeAt ?? Date.now()).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          }),
        });
      case "offline":
        return t("settings.storage.liked_status.offline");
      case "limit":
        return t("settings.storage.liked_status.limit", {
          count: status.pending,
        });
      case "disk":
        return t("settings.storage.liked_status.disk");
      default:
        return t("settings.storage.liked_desc", {
          songs: t("common.songs", { count: savedCount }),
        });
    }
  })();

  return (
    <SettingSection
      label={t("settings.storage.downloads_title")}
      action={
        <StorageFolderButton
          label={t("settings.storage.open_folder_short")}
          onOpen={() => void openDownloadRoot()}
        />
      }
    >
      <SettingRow
        icon={
          <RowIcon>
            <HeartFill size={17} />
          </RowIcon>
        }
        title={t("settings.storage.categories.liked")}
        description={likedDescription}
        explained
        titleKey="settings.storage.categories.liked"
        searchQuery={searchQuery}
        control={
          <div className="flex items-center gap-[12px]">
            <StorageSizeAction
              bytes={likedBytes}
              actionLabel={t("settings.storage.remove")}
              confirmLabel={t("settings.storage.remove_size", {
                size: formatStorageBytes(likedBytes),
              })}
              disabled={likedBytes === 0 && savedCount === 0}
              onConfirm={() => onRemove("liked", likedBytes, removeSaved)}
            />
            <ToggleSwitch
              checked={enabled}
              onChange={setEnabled}
              ariaLabel={t("settings.storage.liked_toggle")}
            />
          </div>
        }
      />

      {sharedCount > 0 ? (
        <SettingRow
          icon={
            <RowIcon>
              <Download2Line size={17} />
            </RowIcon>
          }
          title={t("settings.storage.categories.shared")}
          description={t("settings.storage.shared_desc", {
            songs: t("common.songs", { count: sharedCount }),
          })}
          explained
          titleKey="settings.storage.categories.shared"
          searchQuery={searchQuery}
          control={
            <StorageSizeAction
              bytes={sharedBytes}
              actionLabel={t("settings.storage.remove")}
              confirmLabel={t("settings.storage.remove_size", {
                size: formatStorageBytes(sharedBytes),
              })}
              onConfirm={() => onRemove("shared", sharedBytes, removeShared)}
            />
          }
        />
      ) : null}

      <SettingRow
        icon={
          <RowIcon>
            <LocalFilesIcon size={18} />
          </RowIcon>
        }
        title={t("settings.storage.categories.local")}
        description={
          localCount > 0
            ? t("settings.storage.local_desc", {
                songs: t("common.songs", { count: localCount }),
              })
            : t("settings.storage.local_empty")
        }
        explained
        titleKey="settings.storage.categories.local"
        searchQuery={searchQuery}
        control={
          <StorageSizeAction
            bytes={localBytes}
            actionLabel={t("settings.storage.remove")}
            confirmLabel={t("settings.storage.remove_size", {
              size: formatStorageBytes(localBytes),
            })}
            disabled={localCount === 0}
            onConfirm={() => onRemove("local", localBytes, removeLocal)}
          />
        }
      />

      <SettingRow
        icon={
          <RowIcon>
            <FolderOpenLine size={17} />
          </RowIcon>
        }
        title={t("settings.storage.download_root")}
        description={
          downloadRoot
            ? downloadRoot
            : t("settings.storage.download_root_missing")
        }
        explained
        titleKey="settings.storage.download_root"
        descKey="settings.storage.download_root_desc"
        searchQuery={searchQuery}
        control={
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={busy === "root"}
            onClick={() => void changeDownloadRoot()}
          >
            {t("settings.storage.download_root_change")}
          </Button>
        }
      />

      <SettingRow
        icon={
          <RowIcon>
            <YoutubeFill size={17} />
          </RowIcon>
        }
        title={t("settings.storage.cookies_title")}
        description={
          cookies.length > 0
            ? t("settings.storage.cookies_current", {
                files: cookies.join(", "),
              })
            : t("settings.storage.cookies_desc")
        }
        explained
        titleKey="settings.storage.cookies_title"
        descKey="settings.storage.cookies_desc"
        searchQuery={searchQuery}
        control={
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={busy === "cookies"}
            onClick={() => void importCookies()}
          >
            {t("settings.storage.cookies_import")}
          </Button>
        }
      />

      <SettingRow
        title={t("settings.storage.downloads_limit")}
        description={
          limitBytes > 0
            ? t("settings.storage.downloads_limit_hint", {
                count: limitSongs,
              })
            : t("settings.storage.downloads_limit_unlimited")
        }
        explained
        titleKey="settings.storage.downloads_limit"
        searchQuery={searchQuery}
        control={
          <PresetPills
            ariaLabel={t("settings.storage.downloads_limit")}
            size="md"
            fill={false}
            value={limitBytes}
            onChange={setLimitBytes}
            disabled={!enabled}
            options={LIMIT_OPTIONS.map((gb) => ({
              value: gb * GB,
              label: gb === 0 ? t("settings.storage.no_limit") : `${gb} GB`,
            }))}
          />
        }
      />
    </SettingSection>
  );
}
