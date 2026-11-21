import { beforeEach, describe, expect, it } from "vitest";
import type { Track } from "@/shared/types";
import {
  clearListeningHistory,
  getListeningHistory,
  recordListeningHistory,
} from "./listeningHistory";

const mk = (id: string): Track => ({
  id,
  title: `Track ${id}`,
  artists: `Artist ${id}`,
  durationMs: 180000,
  coverUrl: "",
  playCount: 0,
});

describe("local listening history", () => {
  beforeEach(() => {
    clearListeningHistory();
    localStorage.clear();
    clearListeningHistory();
  });

  it("keeps the newest tracks first and never duplicates a replay", () => {
    recordListeningHistory(mk("a"));
    recordListeningHistory(mk("b"));
    recordListeningHistory(mk("a"));

    expect(getListeningHistory().map((entry) => entry.track.id)).toEqual([
      "a",
      "b",
    ]);
  });

  it("ignores local files and persists the row across reads", () => {
    recordListeningHistory(mk("local:file.mp3"));
    recordListeningHistory(mk("remote"));

    expect(getListeningHistory()).toHaveLength(1);
    expect(getListeningHistory()[0].track.id).toBe("remote");
    expect(localStorage.getItem("liner_listening_history_v1")).toContain(
      "remote",
    );
  });
});
