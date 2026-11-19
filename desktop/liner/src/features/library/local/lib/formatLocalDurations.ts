type Translate = (
  key: string,
  vars?: Record<string, string | number>,
) => string;

export function formatTrackDuration(durationMs: number): string | undefined {
  if (!durationMs) return undefined;
  const minutes = Math.floor(durationMs / 60000);
  const seconds = Math.floor((durationMs % 60000) / 1000);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function formatTotalDuration(totalMs: number, t: Translate): string {
  const totalMinutes = Math.floor(totalMs / 60000);
  if (totalMinutes > 60) {
    return `${Math.floor(totalMinutes / 60)} ${t("playlist.hr")} ${totalMinutes % 60} ${t("playlist.min")}`;
  }
  const seconds = Math.floor((totalMs % 60000) / 1000);
  return `${totalMinutes} ${t("playlist.min")} ${seconds} ${t("playlist.sec")}`;
}
