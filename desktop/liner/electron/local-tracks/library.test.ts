import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { LocalTrackLibrary } from "./library";

describe("LocalTrackLibrary", () => {
  let root: string;
  let sources: string;

  /** Pretend the file was written a while ago, so it is no longer downloading. */
  const settle = async (file: string, offsetMs = 60_000) => {
    const old = new Date(Date.now() - offsetMs);
    await fs.utimes(file, old, old);
    return file;
  };

  const source = async (name: string, content: string) => {
    const file = path.join(sources, name);
    await fs.writeFile(file, content);
    return settle(file);
  };

  beforeEach(async () => {
    const base = await fs.mkdtemp(path.join(os.tmpdir(), "liner-local-"));
    root = path.join(base, "library");
    sources = path.join(base, "sources");
    await fs.mkdir(sources);
  });

  afterEach(async () => {
    await fs.rm(path.dirname(root), { recursive: true, force: true });
  });

  it("copies audio into its own folder and names tracks from the file name", async () => {
    const library = new LocalTrackLibrary(root);
    const file = await source(
      "03 - Boards of Canada - Roygbiv.mp3",
      "not really mp3",
    );
    const result = await library.importFiles([file]);

    expect(result.added).toHaveLength(1);
    const [record] = result.added;
    expect(record).toMatchObject({
      artist: "Boards of Canada",
      title: "Roygbiv",
      mimeType: "audio/mpeg",
    });
    await expect(
      fs.readFile(path.join(root, "audio", record.audioFile), "utf8"),
    ).resolves.toBe("not really mp3");

    await fs.rm(file);
    expect(await new LocalTrackLibrary(root).list()).toEqual([record]);
  });

  it("skips the same file twice and rejects files that are not audio", async () => {
    const library = new LocalTrackLibrary(root);
    const first = await source("a.flac", "same bytes");
    const copy = await source("b.flac", "same bytes");
    const notes = await source("notes.txt", "hello");

    const result = await library.importFiles([first, copy, notes]);

    expect(result.added).toHaveLength(1);
    expect(result.duplicates).toBe(1);
    expect(result.failed).toEqual(["notes.txt"]);
  });

  it("removes the record together with its files", async () => {
    const library = new LocalTrackLibrary(root);
    const { added } = await library.importFiles([
      await source("song.ogg", "ogg"),
    ]);
    const [record] = added;

    await library.remove([record.id]);

    expect(await library.list()).toEqual([]);
    expect(await library.locate("audio", record.id)).toBeNull();
    await expect(
      fs.access(path.join(root, "audio", record.audioFile)),
    ).rejects.toThrow();
  });

  it("refuses an audio-named link that points at a non-audio file", async () => {
    const library = new LocalTrackLibrary(root);
    const secret = await source("id_rsa", "private key");
    const disguised = path.join(sources, "song.mp3");
    await fs.symlink(secret, disguised);

    const result = await library.importFiles([disguised]);

    expect(result.added).toEqual([]);
    expect(result.failed).toEqual(["song.mp3"]);
  });

  it("removes every track with its files and reports the space they used", async () => {
    const library = new LocalTrackLibrary(root);
    await library.importFiles([
      await source("One - A.mp3", "aaaa"),
      await source("Two - B.mp3", "bbbbbb"),
    ]);
    const usage = await library.usage();
    expect(usage.count).toBe(2);
    expect(usage.bytes).toBeGreaterThanOrEqual(10);

    expect(await library.removeAll()).toBe(2);
    expect(await library.list()).toEqual([]);
    await expect(fs.access(path.join(root, "audio"))).rejects.toThrow();
    expect(await library.usage()).toEqual({ count: 0, bytes: 0 });
  });

  it("imports an external folder together with its sidecar covers", async () => {
    const library = new LocalTrackLibrary(root);
    const folder = path.join(sources, "music");
    await fs.mkdir(folder);
    const song = path.join(folder, "Artist---Song.mp3");
    await fs.writeFile(song, "audio bytes");
    await settle(song);
    await fs.writeFile(path.join(folder, "Artist---Song.jpg"), "cover bytes");

    const first = await library.importExternalFolder(folder);

    expect(first.added).toHaveLength(1);
    const [record] = first.added;
    expect(record.title).toBe("Artist---Song");
    expect(record.coverFile).toBeDefined();
    await expect(
      fs.readFile(path.join(root, "covers", record.coverFile ?? ""), "utf8"),
    ).resolves.toBe("cover bytes");

    const again = await library.importExternalFolder(folder);
    expect(again.added).toEqual([]);
    expect(again.duplicates).toBe(1);
  });

  it("waits for a running download to settle before importing it", async () => {
    const library = new LocalTrackLibrary(root);
    const folder = path.join(sources, "music");
    await fs.mkdir(folder);
    const file = path.join(folder, "Downloading---Song.mp3");
    await fs.writeFile(file, "first fragment only");

    const during = await library.importExternalFolder(folder);
    expect(during.added).toEqual([]);

    await fs.appendFile(file, " and the rest");
    await settle(file);
    const after = await library.importExternalFolder(folder);

    expect(after.added).toHaveLength(1);
    expect(after.added[0].byteSize).toBe(
      Buffer.byteLength("first fragment only and the rest"),
    );
  });

  it("ignores yt-dlp fragments and temporary names", async () => {
    const library = new LocalTrackLibrary(root);
    const folder = path.join(sources, "music");
    await fs.mkdir(folder);
    const fragment = path.join(folder, "Song.mp3.part");
    await fs.writeFile(fragment, "part");
    await settle(fragment);
    const video = path.join(folder, "Song.mp4");
    await fs.writeFile(video, "video");
    await settle(video);

    const result = await library.importExternalFolder(folder);

    expect(result.added.map((record) => record.fileName)).toEqual(["Song.mp4"]);
    expect(result.added[0].mimeType).toBe("audio/mp4");
  });

  it("picks up a track as soon as it stops downloading", async () => {
    const library = new LocalTrackLibrary(root);
    const folder = path.join(sources, "music");
    await fs.mkdir(folder);
    const song = path.join(folder, "Fresh---Track.mp3");
    await fs.writeFile(song, "just finished");
    // Older than the in-progress guard, far younger than the old five seconds
    // the sync used to wait, so a finished download appears right away.
    await settle(song, 1_500);

    const result = await library.importExternalFolder(folder);

    expect(result.added.map((record) => record.fileName)).toEqual([
      "Fresh---Track.mp3",
    ]);
  });

  it("leaves the container DowFlow converts to its own pass", async () => {
    const library = new LocalTrackLibrary(root);
    const folder = path.join(sources, "music");
    await fs.mkdir(folder);
    const fragment = path.join(folder, "Converting---Song.webm");
    await fs.writeFile(fragment, "webm bytes");
    await settle(fragment, 3_000);

    const during = await library.importExternalFolder(folder);
    expect(during.added).toEqual([]);

    await settle(fragment, 12_000);
    const after = await library.importExternalFolder(folder);
    expect(after.added.map((record) => record.fileName)).toEqual([
      "Converting---Song.webm",
    ]);
  });

  it("keeps a removed download out of the library until it is downloaded again", async () => {
    const library = new LocalTrackLibrary(root);
    const folder = path.join(sources, "music");
    await fs.mkdir(folder);
    const song = path.join(folder, "Kept---Out.mp3");
    await fs.writeFile(song, "audio bytes");
    await settle(song);

    const first = await library.importExternalFolder(folder);
    expect(first.added).toHaveLength(1);
    await library.remove([first.added[0].id]);

    const afterRemove = await library.importExternalFolder(folder);
    expect(afterRemove.added).toEqual([]);
    expect(await library.list()).toEqual([]);

    // Downloading the same track again replaces the file, so it comes back.
    await fs.writeFile(song, "audio bytes");
    await settle(song, 30_000);
    const afterDownload = await library.importExternalFolder(folder);
    expect(afterDownload.added.map((record) => record.fileName)).toEqual([
      "Kept---Out.mp3",
    ]);
  });

  it("keeps the whole folder out after clearing the library", async () => {
    const library = new LocalTrackLibrary(root);
    const folder = path.join(sources, "music");
    await fs.mkdir(folder);
    const song = path.join(folder, "Old---Track.mp3");
    await fs.writeFile(song, "old bytes");
    await settle(song);
    await library.importExternalFolder(folder);

    expect(await library.removeAll()).toBe(1);

    const again = await library.importExternalFolder(folder);
    expect(again.added).toEqual([]);
    expect(await library.list()).toEqual([]);
  });

  it("backfills a cover saved after the track was imported", async () => {
    const library = new LocalTrackLibrary(root);
    const folder = path.join(sources, "music");
    await fs.mkdir(folder);
    const late = path.join(folder, "Late---Cover.mp3");
    await fs.writeFile(late, "late bytes");
    await settle(late);

    const first = await library.importExternalFolder(folder);
    expect(first.added[0].coverFile).toBeUndefined();

    await fs.writeFile(path.join(folder, "Late---Cover.png"), "late cover");
    await library.importExternalFolder(folder);

    const [record] = await library.list();
    expect(record.coverFile).toBe(`${record.id}.png`);
  });

  it("refuses ids that could escape the library folder", async () => {
    const library = new LocalTrackLibrary(root);
    expect(await library.locate("audio", "../../etc/passwd")).toBeNull();
  });
});
