// Adapted for private DowFlow use from Liner commit 5bec3c7; WEB_REMIX only.
import { Innertube, Platform } from "youtubei.js/web";
import { getClientVisitorData } from "./visitorSession";
import { selectBestAudioFormat, type AudioFormat } from "./audioFormats";
import type { MusicTrack } from "../types";

let sessionPromise: Promise<{ visitorData: string; innertube: Innertube }> | null = null;
let evaluatorInstalled = false;

function installPlayerEvaluator(): void {
  if (evaluatorInstalled) return;
  Platform.shim.eval = async (data, env) => {
    const args = [env.n, env.sp, env.sig].map((value) => JSON.stringify(value ?? ""));
    return new Function(`${data.output}\nreturn process(${args.join(", ")});`)();
  };
  evaluatorInstalled = true;
}

async function createSession(visitorData: string) {
  const innertube = await Innertube.create({
    visitor_data: visitorData,
    user_agent: navigator.userAgent,
    generate_session_locally: true,
    retrieve_player: true,
    fetch: (input, init) => fetch(input, init),
  });
  return { visitorData, innertube };
}

async function getSession(visitorData: string) {
  const existing = sessionPromise ? await sessionPromise.catch(() => null) : null;
  if (existing && existing.visitorData === visitorData) return existing;
  sessionPromise = createSession(visitorData);
  sessionPromise.catch(() => { sessionPromise = null; });
  return sessionPromise;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw signal.reason ?? new DOMException("Aborted", "AbortError");
}

export async function resolveMusicStream(track: MusicTrack, signal?: AbortSignal): Promise<string> {
  const mintPoToken = window.dowflow?.youtube?.mintPoToken;
  if (!mintPoToken) throw new Error("Le lecteur direct nécessite le shell Electron DowFlow.");
  const [poToken, visitorData] = await Promise.all([
    mintPoToken(track.id),
    getClientVisitorData(),
  ]);
  throwIfAborted(signal);
  installPlayerEvaluator();
  const { innertube } = await getSession(visitorData);
  throwIfAborted(signal);
  const info = await innertube.getBasicInfo(track.id, {
    client: "YTMUSIC",
    po_token: poToken,
  });
  throwIfAborted(signal);
  const status = info.playability_status?.status;
  if (status !== "OK") {
    throw new Error(info.playability_status?.reason || `YouTube Music playback status: ${status}`);
  }

  const formats = (info.streaming_data?.adaptive_formats ?? []).filter(
    (format) => format.has_audio && !format.has_video && format.mime_type.startsWith("audio/"),
  );
  const candidates: AudioFormat[] = formats.map((format) => ({
    itag: format.itag,
    mimeType: format.mime_type,
    bitrate: format.bitrate || format.average_bitrate || 0,
    ...(Number(format.content_length) > 0 ? { contentLength: Number(format.content_length) } : {}),
  }));
  const best = selectBestAudioFormat(candidates);
  const source = best ? formats.find((format) => format.itag === best.itag) : undefined;
  const player = innertube.session.player;
  if (!best || !source || !player) throw new Error("YouTube Music returned no usable audio format.");

  const deciphered = await source.decipher(player);
  throwIfAborted(signal);
  const url = new URL(deciphered);
  url.searchParams.set("pot", poToken);
  return url.toString();
}
