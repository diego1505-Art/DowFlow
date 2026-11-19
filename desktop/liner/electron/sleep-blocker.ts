import type { PowerSaveBlocker } from "electron";

type Blocker = Pick<PowerSaveBlocker, "start" | "stop">;

// Keeps the display (and HDMI audio) awake while music is playing.
export function createSleepBlocker(blocker: Blocker) {
  let id: number | null = null;

  return (status: string) => {
    const playing =
      status === "playing" || status === "buffering" || status === "loading";
    if (playing && id === null) {
      id = blocker.start("prevent-display-sleep");
    } else if (!playing && id !== null) {
      blocker.stop(id);
      id = null;
    }
  };
}
