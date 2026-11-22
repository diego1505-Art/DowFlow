import path from "node:path";
import { BrowserWindow, app, dialog } from "electron";
import { handleTrusted } from "../ipc-guard.js";
import {
  findDowflowMusicFolder,
  requestDowflowCoverBackfill,
} from "../dowflow-backend.js";
import { LocalTrackLibrary } from "./library.js";
import { handleLocalTrackScheme } from "./protocol.js";
import type { SavedTrackLibrary } from "../saved-tracks/library.js";
import { LOCAL_AUDIO_EXTENSIONS } from "./types.js";

const DOWFLOW_SYNC_INTERVAL_MS = 1_500;

let requestSync: (() => void) | null = null;

/** Ask the local library to import new DowFlow downloads right now. */
export function syncLocalTracksNow(): void {
  requestSync?.();
}

const stringList = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is string => typeof item === "string" && item.length > 0,
      )
    : [];

export function setupLocalTracks(saved: SavedTrackLibrary) {
  const library = new LocalTrackLibrary(
    path.join(app.getPath("userData"), "local-tracks"),
  );
  handleLocalTrackScheme(library, saved);

  handleTrusted("local-tracks:list", () => {
    // Opening "On this device" should include a track that just finished
    // downloading, even if the periodic sync has not run yet.
    requestSync?.();
    return library.list();
  });

  handleTrusted("local-tracks:import", (_event, paths: unknown) =>
    library.importFiles(stringList(paths)),
  );

  handleTrusted("local-tracks:pick", async (event) => {
    const owner = BrowserWindow.fromWebContents(event.sender);
    const options: Electron.OpenDialogOptions = {
      properties: ["openFile", "multiSelections"],
      filters: [{ name: "Audio", extensions: [...LOCAL_AUDIO_EXTENSIONS] }],
    };
    const picked = owner
      ? await dialog.showOpenDialog(owner, options)
      : await dialog.showOpenDialog(options);
    if (picked.canceled || picked.filePaths.length === 0) return null;
    return library.importFiles(picked.filePaths);
  });

  handleTrusted("local-tracks:remove", (_event, ids: unknown) =>
    library.remove(stringList(ids)),
  );

  handleTrusted("local-tracks:remove-all", () => library.removeAll());

  handleTrusted("local-tracks:usage", () => library.usage());

  // Keep DowFlow's downloaded tracks in sync with "On this device".
  let syncing = false;
  let queued = false;
  let coversRequested = false;
  const syncDowflowMusic = async () => {
    // A track that just finished downloading must not be missed because a tick
    // happened to be running: run again as soon as this pass is done.
    if (syncing) {
      queued = true;
      return;
    }
    syncing = true;
    try {
      const folder = await findDowflowMusicFolder();
      if (!folder) return;
      if (!coversRequested) {
        coversRequested = true;
        // Let DowFlow fill in the artwork missing beside older tracks once.
        void requestDowflowCoverBackfill();
      }
      const result = await library.importExternalFolder(folder);
      if (result.added.length > 0) {
        for (const win of BrowserWindow.getAllWindows()) {
          if (!win.isDestroyed()) win.webContents.send("local-tracks:changed");
        }
      }
    } catch {
      // DowFlow may be closed; the next tick retries.
    } finally {
      syncing = false;
      if (queued) {
        queued = false;
        void syncDowflowMusic();
      }
    }
  };
  requestSync = () => void syncDowflowMusic();
  const timer = setInterval(
    () => void syncDowflowMusic(),
    DOWFLOW_SYNC_INTERVAL_MS,
  );
  void syncDowflowMusic();
  app.on("before-quit", () => {
    requestSync = null;
    clearInterval(timer);
  });
}
