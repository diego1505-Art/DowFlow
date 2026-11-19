export type BundleUpdateState =
  | { kind: "latest" }
  | { kind: "available"; version: string }
  | { kind: "needs-app-update" }
  | { kind: "unknown" }
  | { kind: "inactive" };

export interface BundleVersionInfo {
  version: string;
  isOta: boolean;
  sha256: string | null;
}

export interface BundleStampSource {
  getVersionInfo: () => BundleVersionInfo;
  peekUpdate: () => Promise<BundleUpdateState>;
}

export interface BundleStampOptions {
  emit: (line: string) => void;
  quietMs?: number;
  minIntervalMs?: number;
  updateCacheMs?: number;
  unknownCacheMs?: number;
  now?: () => number;
}

const DEFAULT_QUIET_MS = 1000;
const DEFAULT_MIN_INTERVAL_MS = 8000;
const DEFAULT_UPDATE_CACHE_MS = 10 * 60 * 1000;
const DEFAULT_UNKNOWN_CACHE_MS = 60 * 1000;

function describeUpdate(update: BundleUpdateState): string {
  switch (update.kind) {
    case "latest":
      return "update available: no";
    case "available":
      return `update available: yes (${update.version})`;
    case "needs-app-update":
      return "update available: no (needs a newer app)";
    case "inactive":
      return "update available: n/a (dev)";
    default:
      return "update available: unknown (check failed)";
  }
}

export function formatBundleStamp(
  info: BundleVersionInfo,
  update: BundleUpdateState,
): string {
  const build =
    info.isOta && info.sha256 ? ` ota ${info.sha256.slice(0, 7)}` : "";
  return `${info.version}${build} · ${describeUpdate(update)}`;
}

export function createBundleErrorStamp(
  source: BundleStampSource,
  options: BundleStampOptions,
) {
  const quietMs = options.quietMs ?? DEFAULT_QUIET_MS;
  const minIntervalMs = options.minIntervalMs ?? DEFAULT_MIN_INTERVAL_MS;
  const updateCacheMs = options.updateCacheMs ?? DEFAULT_UPDATE_CACHE_MS;
  const unknownCacheMs = options.unknownCacheMs ?? DEFAULT_UNKNOWN_CACHE_MS;
  const now = options.now ?? Date.now;

  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastEmitAt = Number.NEGATIVE_INFINITY;
  let cachedUpdate: { state: BundleUpdateState; at: number } | null = null;

  const readUpdate = async (): Promise<BundleUpdateState> => {
    const cacheMs =
      cachedUpdate?.state.kind === "unknown" ? unknownCacheMs : updateCacheMs;
    if (cachedUpdate && now() - cachedUpdate.at < cacheMs)
      return cachedUpdate.state;
    const state = await source
      .peekUpdate()
      .catch((): BundleUpdateState => ({ kind: "unknown" }));
    cachedUpdate = { state, at: now() };
    return state;
  };

  const emitStamp = async () => {
    timer = null;
    lastEmitAt = now();
    options.emit(
      formatBundleStamp(source.getVersionInfo(), await readUpdate()),
    );
  };

  const onRendererError = () => {
    if (timer) clearTimeout(timer);
    const sinceLastEmit = now() - lastEmitAt;
    const wait = Math.max(quietMs, minIntervalMs - sinceLastEmit);
    timer = setTimeout(() => void emitStamp(), wait);
  };

  const dispose = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };

  return { onRendererError, dispose };
}
