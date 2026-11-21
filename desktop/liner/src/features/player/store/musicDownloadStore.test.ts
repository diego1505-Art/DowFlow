import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMusicDownloadStore } from "./musicDownloadStore";

describe("music download store", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useMusicDownloadStore.setState({ downloads: {} });
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (window as unknown as { linerElectron?: unknown }).linerElectron;
  });

  it("polls in the background and reports progress then success", async () => {
    const downloadMusicStatus = vi
      .fn()
      .mockResolvedValueOnce({ status: "running", progress: 42 })
      .mockResolvedValueOnce({ status: "success", progress: 100 });
    (window as unknown as { linerElectron?: unknown }).linerElectron = {
      downloadMusicStatus,
    };

    useMusicDownloadStore.getState().start({
      trackId: "track-1",
      jobId: "job-1",
      title: "Track",
      artists: "Artist",
    });

    await vi.advanceTimersByTimeAsync(1_000);
    expect(useMusicDownloadStore.getState().downloads["track-1"]).toMatchObject(
      {
        percent: 42,
        status: "running",
      },
    );

    await vi.advanceTimersByTimeAsync(1_000);
    expect(useMusicDownloadStore.getState().downloads["track-1"]).toMatchObject(
      {
        percent: 100,
        status: "success",
      },
    );
    expect(downloadMusicStatus).toHaveBeenCalledTimes(2);
  });

  it("marks an already downloaded track as done without a job", () => {
    useMusicDownloadStore.getState().markExisting({
      trackId: "track-2",
      title: "Track",
      artists: "Artist",
    });

    expect(useMusicDownloadStore.getState().downloads["track-2"]).toMatchObject(
      {
        status: "success",
        percent: 100,
      },
    );
  });
});
