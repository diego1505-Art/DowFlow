import type { Dirent } from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { importLocalFile } from "./importer.js";
import {
  LOCAL_AUDIO_EXTENSIONS,
  type LocalImportResult,
  type LocalLibraryUsage,
  type LocalTrackRecord,
} from "./types.js";

const SUPPORTED_AUDIO = new Set<string>(LOCAL_AUDIO_EXTENSIONS);
const SIDECAR_COVERS = new Set(["jpg", "jpeg", "png", "webp"]);
const fileStem = (name: string) => path.basename(name, path.extname(name));
/** Match "poster boy.mp3" with "poster-boy.jpg": same track, different separators. */
const coverKey = (name: string) =>
  fileStem(name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");

const ID_PATTERN = /^[a-f0-9]{20}$/;
const LIBRARY_FOLDERS = ["audio", "covers"] as const;
/** A file written this recently may still be a download in progress. */
const SETTLE_MS = 5_000;
const PARTIAL_SUFFIXES = [
  ".part",
  ".ytdl",
  ".tmp",
  ".temp",
  ".crdownload",
  ".download",
  ".frag",
];

/** Temporary names yt-dlp/DowFlow use while a download is still running. */
const isPartialName = (name: string) => {
  const lowered = name.toLowerCase();
  return lowered.startsWith(".") || PARTIAL_SUFFIXES.some((s) => lowered.endsWith(s));
};

/**
 * Identify one version of a file in the download folder. The modification date
 * is part of it, so downloading the same track again is a new source.
 */
const stampOf = (name: string, size: number, mtimeMs: number) =>
  `${name.toLowerCase()}\u0000${size}\u0000${Math.round(mtimeMs)}`;

async function folderBytes(folder: string): Promise<number> {
  try {
    const entries = await fsp.readdir(folder, { withFileTypes: true });
    let total = 0;
    for (const entry of entries) {
      if (!entry.isFile()) continue;
      try {
        total += (await fsp.stat(path.join(folder, entry.name))).size;
      } catch {}
    }
    return total;
  } catch {
    return 0;
  }
}

export class LocalTrackLibrary {
  private records: LocalTrackRecord[] | null = null;
  private dismissedStamps: Set<string> | null = null;
  private queue: Promise<unknown> = Promise.resolve();

  constructor(private readonly root: string) {}

  private get indexPath() {
    return path.join(this.root, "library.json");
  }

  private get dismissedPath() {
    return path.join(this.root, "dismissed.json");
  }

  private filePath(...parts: string[]) {
    return path.join(this.root, ...parts);
  }

  private serialized<T>(task: () => Promise<T>): Promise<T> {
    const next = this.queue.then(task, task);
    this.queue = next.catch(() => undefined);
    return next;
  }

  private async load(): Promise<LocalTrackRecord[]> {
    if (this.records) return this.records;
    try {
      const parsed: unknown = JSON.parse(
        await fsp.readFile(this.indexPath, "utf8"),
      );
      this.records = Array.isArray(parsed)
        ? (parsed as LocalTrackRecord[])
        : [];
    } catch {
      this.records = [];
    }
    return this.records;
  }

  private async save(records: LocalTrackRecord[]) {
    await fsp.mkdir(this.root, { recursive: true });
    const temp = `${this.indexPath}.tmp`;
    await fsp.writeFile(temp, JSON.stringify(records));
    await fsp.rename(temp, this.indexPath);
    this.records = records;
  }

  /** Sources the user deleted, so the sync does not import them back. */
  private async loadDismissed(): Promise<Set<string>> {
    if (this.dismissedStamps) return this.dismissedStamps;
    try {
      const parsed: unknown = JSON.parse(
        await fsp.readFile(this.dismissedPath, "utf8"),
      );
      this.dismissedStamps = new Set(
        Array.isArray(parsed)
          ? parsed.filter((entry): entry is string => typeof entry === "string")
          : [],
      );
    } catch {
      this.dismissedStamps = new Set();
    }
    return this.dismissedStamps;
  }

  private async saveDismissed(stamps: Set<string>) {
    await fsp.mkdir(this.root, { recursive: true });
    const temp = `${this.dismissedPath}.tmp`;
    await fsp.writeFile(temp, JSON.stringify([...stamps]));
    await fsp.rename(temp, this.dismissedPath);
    this.dismissedStamps = stamps;
  }

  private async dismiss(records: LocalTrackRecord[]) {
    const stamps = records
      .map((record) => record.sourceStamp)
      .filter((stamp): stamp is string => Boolean(stamp));
    if (stamps.length === 0) return;
    const next = new Set(await this.loadDismissed());
    for (const stamp of stamps) next.add(stamp);
    await this.saveDismissed(next);
  }

  list(): Promise<LocalTrackRecord[]> {
    return this.serialized(() => this.load());
  }

  importFiles(paths: string[]): Promise<LocalImportResult> {
    return this.serialized(async () => {
      const records = [...(await this.load())];
      const known = new Set(records.map((record) => record.id));
      const result: LocalImportResult = {
        added: [],
        duplicates: 0,
        failed: [],
      };
      await fsp.mkdir(this.filePath("audio"), { recursive: true });
      await fsp.mkdir(this.filePath("covers"), { recursive: true });
      for (const source of paths) {
        try {
          const record = await importLocalFile(source, this.root, known);
          if (!record) result.duplicates += 1;
          else {
            known.add(record.id);
            records.push(record);
            result.added.push(record);
          }
        } catch {
          result.failed.push(path.basename(source));
        }
      }
      if (result.added.length > 0) await this.save(records);
      return result;
    });
  }

  /**
   * Import every new track from a folder managed by another app (DowFlow's
   * `downloads/music`) and pick up the cover image stored beside each file.
   */
  importExternalFolder(folder: string): Promise<LocalImportResult> {
    return this.serialized(async () => {
      const result: LocalImportResult = { added: [], duplicates: 0, failed: [] };
      let entries: Dirent[];
      try {
        entries = await fsp.readdir(folder, { withFileTypes: true });
      } catch {
        return result;
      }

      const covers = new Map<string, string>();
      for (const entry of entries) {
        if (!entry.isFile()) continue;
        const extension = path.extname(entry.name).slice(1).toLowerCase();
        if (SIDECAR_COVERS.has(extension)) {
          covers.set(coverKey(entry.name), path.join(folder, entry.name));
        }
      }

      const records = [...(await this.load())];
      const known = new Set(records.map((record) => record.id));
      // Recognise files that are already imported before hashing them: reading
      // every track on each sync tick saturated the disk and slowed the app.
      const bySource = new Map(
        records.map((record) => [
          `${record.fileName}\u0000${record.byteSize}`,
          record,
        ]),
      );
      const knownSources = new Set(bySource.keys());
      // A track deleted from the library stays deleted: its file is still in
      // the download folder, so without this every removal undid itself on the
      // next tick and the page looked like it was resurrecting old tracks.
      const dismissed = await this.loadDismissed();
      await fsp.mkdir(this.filePath("audio"), { recursive: true });
      await fsp.mkdir(this.filePath("covers"), { recursive: true });

      let changed = false;
      for (const entry of entries) {
        if (!entry.isFile()) continue;
        if (isPartialName(entry.name)) continue;
        const extension = path.extname(entry.name).slice(1).toLowerCase();
        if (!SUPPORTED_AUDIO.has(extension)) continue;
        const source = path.join(folder, entry.name);
        try {
          const before = await fsp.stat(source);
          if (!before.isFile()) continue;
          // DowFlow downloads straight into this folder: a file touched moments
          // ago may still be growing. Importing it now copied a truncated track
          // and left a duplicate next to the finished file, so wait one tick.
          if (Date.now() - before.mtimeMs < SETTLE_MS) continue;
          const stamp = stampOf(entry.name, before.size, before.mtimeMs);
          if (dismissed.has(stamp)) continue;
          if (knownSources.has(`${entry.name}\u0000${before.size}`)) {
            // Record the version that is already imported, so deleting it can
            // silence exactly that one and not a future re-download.
            const existing = bySource.get(`${entry.name}\u0000${before.size}`);
            if (existing && !existing.sourceStamp) {
              existing.sourceStamp = stamp;
              changed = true;
            }
            result.duplicates += 1;
            continue;
          }
          const record = await importLocalFile(source, this.root, known, {
            sidecarCover: covers.get(coverKey(entry.name)),
          });
          if (!record) {
            result.duplicates += 1;
            continue;
          }
          // The write may have resumed while the copy ran: drop that copy and
          // let the next tick import the finished file instead.
          const after = await fsp.stat(source);
          if (after.size !== before.size || after.mtimeMs !== before.mtimeMs) {
            await fsp.rm(this.filePath("audio", record.audioFile), {
              force: true,
            });
            if (record.coverFile) {
              await fsp.rm(this.filePath("covers", record.coverFile), {
                force: true,
              });
            }
            continue;
          }
          record.sourceStamp = stamp;
          known.add(record.id);
          knownSources.add(`${record.fileName}\u0000${record.byteSize}`);
          records.push(record);
          result.added.push(record);
          changed = true;
        } catch {
          result.failed.push(entry.name);
        }
      }

      // Backfill covers for tracks imported before their artwork existed.
      for (const record of records) {
        if (record.coverFile) continue;
        const cover = covers.get(coverKey(record.fileName));
        if (!cover) continue;
        const extension = path.extname(cover).slice(1).toLowerCase();
        if (!SIDECAR_COVERS.has(extension)) continue;
        try {
          const coverFile = `${record.id}.${extension}`;
          await fsp.copyFile(cover, this.filePath("covers", coverFile));
          record.coverFile = coverFile;
          changed = true;
        } catch {
          // keep the track without artwork
        }
      }

      if (changed) await this.save(records);
      return result;
    });
  }

  remove(ids: string[]): Promise<void> {
    return this.serialized(async () => {
      const removing = new Set(ids);
      const records = await this.load();
      const gone = records.filter((record) => removing.has(record.id));
      if (gone.length === 0) return;
      await this.dismiss(gone);
      await this.save(records.filter((record) => !removing.has(record.id)));
      for (const record of gone) {
        await fsp.rm(this.filePath("audio", record.audioFile), { force: true });
        if (record.coverFile) {
          await fsp.rm(this.filePath("covers", record.coverFile), {
            force: true,
          });
        }
      }
    });
  }

  removeAll(): Promise<number> {
    return this.serialized(async () => {
      const records = await this.load();
      const count = records.length;
      await this.dismiss(records);
      await this.save([]);
      for (const folder of LIBRARY_FOLDERS) {
        await fsp.rm(this.filePath(folder), { recursive: true, force: true });
      }
      return count;
    });
  }

  usage(): Promise<LocalLibraryUsage> {
    return this.serialized(async () => {
      const records = await this.load();
      let bytes = 0;
      for (const folder of LIBRARY_FOLDERS) {
        bytes += await folderBytes(this.filePath(folder));
      }
      if (records.length > 0) {
        try {
          bytes += (await fsp.stat(this.indexPath)).size;
        } catch {}
      }
      return { count: records.length, bytes };
    });
  }

  async locate(kind: "audio" | "cover", id: string) {
    if (!ID_PATTERN.test(id)) return null;
    const record = (await this.list()).find((entry) => entry.id === id);
    const file = kind === "audio" ? record?.audioFile : record?.coverFile;
    if (!record || !file) return null;
    return {
      path: this.filePath(kind === "audio" ? "audio" : "covers", file),
      record,
    };
  }
}
