import { useEffect, type RefObject } from "react";
import { buildAmbientWorkerSource } from "@/shared/media/ambient";
import { log } from "@/shared/utils/logger";
import { playbackState, startAmbientFeed } from "./ambientFeed";

const DEFAULT_SCALE = 0.5;

export interface AmbientOptions {
  pixelated: boolean;
  blur: number;
}

interface WorkerMessage {
  type: string;
  message?: string;
  pixelated?: boolean;
  scale?: number;
  blur?: number;
}

function surfaceSize(canvas: HTMLCanvasElement, scale: number) {
  const rect = canvas.getBoundingClientRect();
  return {
    width: Math.max(1, Math.round(rect.width * scale)),
    height: Math.max(1, Math.round(rect.height * scale)),
  };
}

const DEFAULT_BLUR_PX = 1.5;

const clampBlur = (blur: number | undefined) =>
  typeof blur === "number" && Number.isFinite(blur)
    ? Math.min(24, Math.max(0, blur))
    : DEFAULT_BLUR_PX;

const clampScale = (scale: number | undefined) =>
  scale && scale > 0 ? Math.min(1, Math.max(0.05, scale)) : DEFAULT_SCALE;

export function useAmbientWorker(
  hostRef: RefObject<HTMLDivElement | null>,
  pixelated: boolean,
  script: string | null,
  onFailure: () => void,
  onOptions: (options: AmbientOptions) => void,
) {
  useEffect(() => {
    const host = hostRef.current;
    if (!host || !script) return;
    const canvas = document.createElement("canvas");
    canvas.className = "block h-full w-full";
    host.replaceChildren(canvas);

    const source = URL.createObjectURL(
      new Blob([buildAmbientWorkerSource(script)], {
        type: "text/javascript",
      }),
    );
    const worker = new Worker(source);
    let scale = DEFAULT_SCALE;
    const resize = () =>
      worker.postMessage({ type: "resize", ...surfaceSize(canvas, scale) });
    worker.onmessage = (event: MessageEvent<WorkerMessage>) => {
      if (event.data.type === "options") {
        scale = clampScale(event.data.scale);
        onOptions({
          pixelated: Boolean(event.data.pixelated),
          blur: clampBlur(event.data.blur),
        });
        resize();
        return;
      }
      if (event.data.type !== "error") return;
      log("yellow", "ambient", `effect stopped: ${event.data.message}`);
      worker.terminate();
      onFailure();
    };
    worker.onerror = () => {
      worker.terminate();
      onFailure();
    };

    const size = surfaceSize(canvas, scale);
    const offscreen = canvas.transferControlToOffscreen();
    offscreen.width = size.width;
    offscreen.height = size.height;
    worker.postMessage(
      {
        type: "init",
        canvas: offscreen,
        info: { ...size, state: playbackState() },
      },
      [offscreen],
    );

    const stopFeed = startAmbientFeed(worker);
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);

    return () => {
      stopFeed();
      resizeObserver.disconnect();
      worker.terminate();
      URL.revokeObjectURL(source);
      canvas.remove();
    };
  }, [hostRef, script, onFailure, onOptions]);

  useEffect(() => {
    const canvas = hostRef.current?.firstElementChild;
    if (canvas instanceof HTMLCanvasElement) {
      canvas.style.imageRendering = pixelated ? "pixelated" : "";
    }
  }, [hostRef, pixelated]);
}
