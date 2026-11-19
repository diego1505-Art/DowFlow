import { useCallback, useSyncExternalStore } from "react";
import { prepareCoverFallback } from "./coverSigner";

type CoverStatus = "loading" | "loaded" | "error";

interface CoverEntry {
  status: CoverStatus;
  effectiveUrl?: string;
  opaque?: boolean;
  promise: Promise<void>;
}

export const COVER_REGISTRY_LIMIT = 300;
export const DECODED_COVER_LIMIT = 8;

const entries = new Map<string, CoverEntry>();
const keyByEffectiveUrl = new Map<string, string>();
const decoded = new Map<string, HTMLImageElement>();
const decoding = new Map<string, Promise<void>>();
const listeners = new Map<string, Set<() => void>>();

function resolveKey(url: string): string {
  if (entries.has(url)) return url;
  return keyByEffectiveUrl.get(url) ?? url;
}

function touch(key: string, entry: CoverEntry): void {
  entries.delete(key);
  entries.set(key, entry);
}

function isObserved(key: string, entry: CoverEntry): boolean {
  return (
    listeners.has(key) ||
    (!!entry.effectiveUrl && listeners.has(entry.effectiveUrl))
  );
}

function forget(key: string, entry: CoverEntry): void {
  entries.delete(key);
  decoded.delete(key);
  if (entry.effectiveUrl && keyByEffectiveUrl.get(entry.effectiveUrl) === key) {
    keyByEffectiveUrl.delete(entry.effectiveUrl);
  }
}

function trimEntries(): void {
  if (entries.size <= COVER_REGISTRY_LIMIT) return;
  for (const [key, entry] of entries) {
    if (entries.size <= COVER_REGISTRY_LIMIT) return;
    if (entry.status === "loading" || isObserved(key, entry)) continue;
    forget(key, entry);
  }
}

function storeEntry(key: string, entry: CoverEntry): void {
  touch(key, entry);
  trimEntries();
}

function setEffectiveUrl(
  key: string,
  entry: CoverEntry,
  effectiveUrl: string,
): void {
  if (entry.effectiveUrl === effectiveUrl) return;
  if (entry.effectiveUrl && keyByEffectiveUrl.get(entry.effectiveUrl) === key) {
    keyByEffectiveUrl.delete(entry.effectiveUrl);
  }
  entry.effectiveUrl = effectiveUrl;
  if (effectiveUrl !== key) keyByEffectiveUrl.set(effectiveUrl, key);
}

function rememberDecoded(key: string, img: HTMLImageElement): void {
  decoded.delete(key);
  decoded.set(key, img);
  while (decoded.size > DECODED_COVER_LIMIT) {
    const oldest = decoded.keys().next().value as string;
    decoded.delete(oldest);
  }
}

function notify(key: string): void {
  const effectiveUrl = entries.get(key)?.effectiveUrl;
  for (const url of effectiveUrl && effectiveUrl !== key
    ? [key, effectiveUrl]
    : [key]) {
    const set = listeners.get(url);
    if (set) for (const listener of set) listener();
  }
}

function subscribe(url: string, listener: () => void): () => void {
  let set = listeners.get(url);
  if (!set) {
    set = new Set();
    listeners.set(url, set);
  }
  set.add(listener);
  return () => {
    set!.delete(listener);
    if (set!.size === 0) listeners.delete(url);
  };
}

function createCoverImage(cors = true): HTMLImageElement {
  const img = new window.Image();
  if (cors) img.crossOrigin = "anonymous";
  img.decoding = "async";
  return img;
}

export function isCoverReady(url: string | undefined): boolean {
  return !!url && entries.get(resolveKey(url))?.status === "loaded";
}

export function clearCoverRegistry(): void {
  entries.clear();
  keyByEffectiveUrl.clear();
  decoded.clear();
  decoding.clear();
  for (const set of listeners.values()) {
    for (const listener of set) listener();
  }
}

export function getCoverElement(
  url: string | undefined,
): HTMLImageElement | undefined {
  if (!url) return undefined;
  const key = resolveKey(url);
  const entry = entries.get(key);
  if (entry?.status !== "loaded" || entry.opaque) return undefined;
  return decoded.get(key);
}

export function getCoverCrossOrigin(
  url: string | undefined,
): "anonymous" | undefined {
  if (!url) return "anonymous";
  return entries.get(resolveKey(url))?.opaque ? undefined : "anonymous";
}

function isCoverSettled(url: string | undefined): boolean {
  if (!url) return true;
  const status = entries.get(resolveKey(url))?.status;
  return status === "loaded" || status === "error";
}

export function markCoverReady(
  url: string | undefined,
  effectiveUrl?: string,
  opaque = false,
): void {
  if (!url) return;
  const key = resolveKey(url);
  const resolved = effectiveUrl ?? url;
  const entry = entries.get(key);
  if (entry) {
    if (entry.status === "loaded" && !entry.opaque && opaque) return;
    const changed =
      entry.status !== "loaded" ||
      entry.effectiveUrl !== resolved ||
      Boolean(entry.opaque) !== opaque;
    if (entry.effectiveUrl !== resolved || Boolean(entry.opaque) !== opaque) {
      decoded.delete(key);
    }
    setEffectiveUrl(key, entry, resolved);
    entry.status = "loaded";
    entry.opaque = opaque;
    touch(key, entry);
    if (changed) notify(key);
    return;
  }
  const created: CoverEntry = {
    status: "loaded",
    opaque,
    promise: Promise.resolve(),
  };
  setEffectiveUrl(key, created, resolved);
  storeEntry(key, created);
  notify(key);
}

function decodeLoadedCover(key: string, entry: CoverEntry): Promise<void> {
  if (decoded.has(key)) {
    rememberDecoded(key, decoded.get(key)!);
    return Promise.resolve();
  }
  const inflight = decoding.get(key);
  if (inflight) return inflight;
  const src = entry.effectiveUrl ?? key;
  const img = createCoverImage(!entry.opaque);
  const promise = new Promise<void>((resolve) => {
    const finish = (ok: boolean) => {
      if (decoding.get(key) === promise) decoding.delete(key);
      const current = entries.get(key);
      if (
        ok &&
        current?.status === "loaded" &&
        (current.effectiveUrl ?? key) === src
      ) {
        rememberDecoded(key, img);
        notify(key);
      }
      resolve();
    };
    img.onload = () => finish(true);
    img.onerror = () => finish(false);
  });
  decoding.set(key, promise);
  img.src = src;
  return promise;
}

export function preloadCoverArt(url: string | undefined): Promise<void> {
  if (!url || typeof window === "undefined") return Promise.resolve();

  const key = resolveKey(url);
  const existing = entries.get(key);
  if (existing) {
    if (existing.status === "loaded") {
      touch(key, existing);
      return decodeLoadedCover(key, existing);
    }
    if (existing.status === "loading") return existing.promise;
    forget(key, existing);
  }

  const img = createCoverImage();

  void prepareCoverFallback(key);

  let entry: CoverEntry;
  const promise = new Promise<void>((resolve) => {
    let triedFallback = false;
    const settle = (
      status: CoverStatus,
      loadedImg?: HTMLImageElement,
      opaque = false,
    ) => {
      if (
        entries.get(key) === entry &&
        !(status === "error" && entry.status === "loaded")
      ) {
        entry.status = status;
        entry.opaque = opaque;
        if (loadedImg) {
          setEffectiveUrl(key, entry, loadedImg.src);
          rememberDecoded(key, loadedImg);
        }
        trimEntries();
      }
      notify(key);
      resolve();
    };
    const loadOpaque = () => {
      const opaqueImg = createCoverImage(false);
      opaqueImg.onload = () => settle("loaded", opaqueImg, true);
      opaqueImg.onerror = () => settle("error");
      opaqueImg.src = key;
    };
    img.onload = () => settle("loaded", img);
    img.onerror = () => {
      if (!triedFallback) {
        triedFallback = true;
        void prepareCoverFallback(key).then((fallback) => {
          if (fallback) img.src = fallback;
          else loadOpaque();
        });
        return;
      }
      loadOpaque();
    };
  });

  entry = { status: "loading", promise };
  storeEntry(key, entry);
  img.src = key;
  return promise;
}

function useCoverSubscription(url: string | undefined, preload: boolean) {
  return useCallback(
    (onChange: () => void) => {
      if (!url) return () => {};
      if (preload) void preloadCoverArt(url);
      return subscribe(url, onChange);
    },
    [url, preload],
  );
}

export function useCoverReady(url: string | undefined): boolean {
  return useSyncExternalStore(
    useCoverSubscription(url, true),
    () => isCoverSettled(url),
    () => false,
  );
}

function effectiveCoverSrc(url: string | undefined): string | undefined {
  if (!url) return undefined;
  return entries.get(resolveKey(url))?.effectiveUrl ?? url;
}

export function useCoverSrc(url: string | undefined): string | undefined {
  return useSyncExternalStore(
    useCoverSubscription(url, true),
    () => effectiveCoverSrc(url),
    () => url,
  );
}

export function useRenderedCoverSrc(
  url: string | undefined,
): string | undefined {
  return useSyncExternalStore(
    useCoverSubscription(url, false),
    () => effectiveCoverSrc(url),
    () => url,
  );
}

export function useCoverCrossOrigin(
  url: string | undefined,
): "anonymous" | undefined {
  return useSyncExternalStore(
    useCoverSubscription(url, false),
    () => getCoverCrossOrigin(url),
    () => "anonymous",
  );
}

export function loadCoverElement(
  url: string | undefined,
): Promise<HTMLImageElement | undefined> {
  return preloadCoverArt(url).then(() => getCoverElement(url));
}

export function useCoverElement(
  url: string | undefined,
): HTMLImageElement | undefined {
  return useSyncExternalStore(
    useCoverSubscription(url, true),
    () => getCoverElement(url),
    () => undefined,
  );
}
