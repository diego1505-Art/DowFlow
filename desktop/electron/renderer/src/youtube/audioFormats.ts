// Adapted for private DowFlow use from Liner commit 5bec3c7.
export interface AudioFormat {
  itag: number;
  mimeType: string;
  bitrate: number;
  contentLength?: number;
}

const PREFERRED_ITAGS = [251, 140, 250, 249, 139];

export function selectBestAudioFormat(formats: AudioFormat[]): AudioFormat | null {
  if (formats.length === 0) return null;
  for (const itag of PREFERRED_ITAGS) {
    const match = formats.find((format) => format.itag === itag);
    if (match) return match;
  }
  return [...formats].sort((a, b) => b.bitrate - a.bitrate)[0] ?? null;
}
