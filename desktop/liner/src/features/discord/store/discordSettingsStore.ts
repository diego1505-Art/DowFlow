import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { debouncedStorage } from "@/shared/utils/storage";
import {
  DEFAULT_DISCORD_SETTINGS,
  type DiscordRpcSettings,
  type DiscordStatusDisplayType,
} from "../contracts";

interface DiscordSettingsState extends DiscordRpcSettings {
  setEnabled: (enabled: boolean) => void;
  setStatusDisplayType: (statusDisplayType: DiscordStatusDisplayType) => void;
  setShowArtwork: (showArtwork: boolean) => void;
  setShowArtistSmallImage: (showArtistSmallImage: boolean) => void;
  setShowTime: (showTime: boolean) => void;
  setShowPaused: (showPaused: boolean) => void;
  setShowButton: (showButton: boolean) => void;
  setShowDownloadButton: (showDownloadButton: boolean) => void;
}

function notifyElectron(patch: Partial<DiscordRpcSettings>) {
  if (
    typeof window !== "undefined" &&
    window.linerElectron?.discordUpdateSettings
  ) {
    window.linerElectron.discordUpdateSettings(patch);
  }
}

const VALID_STATUS_DISPLAY_TYPES: readonly DiscordStatusDisplayType[] = [
  "artist",
  "title",
  "artist_title",
  "title_artist",
  "app",
] as const;

export const useDiscordSettingsStore = create<DiscordSettingsState>()(
  persist(
    (set) => ({
      ...DEFAULT_DISCORD_SETTINGS,
      setEnabled: (enabled) => {
        set({ enabled });
        notifyElectron({ enabled });
      },
      setStatusDisplayType: (statusDisplayType) => {
        set({ statusDisplayType });
        notifyElectron({ statusDisplayType });
      },
      setShowArtwork: (showArtwork) => {
        set({ showArtwork });
        notifyElectron({ showArtwork });
      },
      setShowArtistSmallImage: (showArtistSmallImage) => {
        set({ showArtistSmallImage });
        notifyElectron({ showArtistSmallImage });
      },
      setShowTime: (showTime) => {
        set({ showTime });
        notifyElectron({ showTime });
      },
      setShowPaused: (showPaused) => {
        set({ showPaused });
        notifyElectron({ showPaused });
      },
      setShowButton: (showButton) => {
        set({ showButton });
        notifyElectron({ showButton });
      },
      setShowDownloadButton: (showDownloadButton) => {
        set({ showDownloadButton });
        notifyElectron({ showDownloadButton });
      },
    }),
    {
      name: "liner_discord_settings_v1",
      storage: createJSONStorage(() => debouncedStorage),
      partialize: (state): DiscordRpcSettings => ({
        enabled: state.enabled,
        statusDisplayType: state.statusDisplayType,
        showArtwork: state.showArtwork,
        showArtistSmallImage: state.showArtistSmallImage,
        showTime: state.showTime,
        showPaused: state.showPaused,
        showButton: state.showButton,
        showDownloadButton: state.showDownloadButton,
      }),
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        if (typeof state.enabled !== "boolean") {
          state.setEnabled(DEFAULT_DISCORD_SETTINGS.enabled);
        }
        if (!VALID_STATUS_DISPLAY_TYPES.includes(state.statusDisplayType)) {
          state.setStatusDisplayType(
            DEFAULT_DISCORD_SETTINGS.statusDisplayType,
          );
        }
        if (typeof state.showArtwork !== "boolean") {
          state.setShowArtwork(DEFAULT_DISCORD_SETTINGS.showArtwork);
        }
        if (typeof state.showArtistSmallImage !== "boolean") {
          state.setShowArtistSmallImage(
            DEFAULT_DISCORD_SETTINGS.showArtistSmallImage,
          );
        }
        if (typeof state.showTime !== "boolean") {
          state.setShowTime(DEFAULT_DISCORD_SETTINGS.showTime);
        }
        if (typeof state.showPaused !== "boolean") {
          state.setShowPaused(DEFAULT_DISCORD_SETTINGS.showPaused);
        }
        if (typeof state.showButton !== "boolean") {
          state.setShowButton(DEFAULT_DISCORD_SETTINGS.showButton);
        }
        if (typeof state.showDownloadButton !== "boolean") {
          state.setShowDownloadButton(
            DEFAULT_DISCORD_SETTINGS.showDownloadButton,
          );
        }
      },
    },
  ),
);
