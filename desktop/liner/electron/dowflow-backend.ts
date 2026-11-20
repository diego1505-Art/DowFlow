/**
 * Locates the local DowFlow Flask backend so DowFlow Music can talk to it
 * without sharing a process or fighting browser CORS rules.
 */

let lastGoodOrigin: string | null = null;

export async function findDowflowBackend(): Promise<string | null> {
  const configured = process.env.DOWFLOW_BACKEND_URL?.trim();
  const candidates = configured
    ? [configured.replace(/\/$/, "")]
    : Array.from(
        { length: 10 },
        (_, index) => `http://127.0.0.1:${5001 + index}`,
      );
  // Probe the port that answered last time first: on a machine where DowFlow
  // runs on 5002+ every sync tick used to wait through ten 700 ms timeouts.
  const ordered = lastGoodOrigin
    ? [lastGoodOrigin, ...candidates.filter((c) => c !== lastGoodOrigin)]
    : candidates;
  for (const origin of ordered) {
    try {
      const response = await fetch(`${origin}/api/status`, {
        signal: AbortSignal.timeout(700),
      });
      if (!response.ok) continue;
      const status = (await response.json()) as {
        service?: string;
        ready?: boolean;
      };
      if (status?.service === "DowFlow" && status.ready === true) {
        lastGoodOrigin = origin;
        return origin;
      }
    } catch {
      // try the next loopback port
    }
    if (lastGoodOrigin === origin) lastGoodOrigin = null;
  }
  return null;
}

/** Ask DowFlow to write the missing cover art in its Music folder. */
export async function requestDowflowCoverBackfill(): Promise<number> {
  const backend = await findDowflowBackend();
  if (!backend) return 0;
  try {
    const response = await fetch(`${backend}/api/music/covers`, {
      method: "POST",
      signal: AbortSignal.timeout(120_000),
    });
    if (!response.ok) return 0;
    const data = (await response.json()) as { created?: unknown };
    return typeof data.created === "number" ? data.created : 0;
  } catch {
    return 0;
  }
}

/** Absolute path of DowFlow's Music folder, or null when DowFlow is offline. */
export async function findDowflowMusicFolder(): Promise<string | null> {
  const backend = await findDowflowBackend();
  if (!backend) return null;
  try {
    const response = await fetch(`${backend}/api/music/folder`, {
      signal: AbortSignal.timeout(1500),
    });
    if (!response.ok) return null;
    const data = (await response.json()) as { success?: boolean; path?: unknown };
    return data.success === true &&
      typeof data.path === "string" &&
      data.path.trim().length > 0
      ? data.path
      : null;
  } catch {
    return null;
  }
}
