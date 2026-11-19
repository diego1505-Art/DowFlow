import { useEffect, useState } from "react";
import { isWindowVisible } from "@/shared/utils/windowVisibility";

const SAMPLE_MS = 3000;
const PAUSE_MS = 10000;
const LATE_FACTOR = 1.8;
const LATE_SHARE = 0.2;
const STRIKES_TO_FLAG = 2;

function isStrained(deltas: number[]): boolean {
  if (deltas.length < 30) return false;
  const sorted = [...deltas].sort((a, b) => a - b);
  const frame = sorted[Math.floor(sorted.length * 0.1)];
  const late = deltas.filter((delta) => delta > frame * LATE_FACTOR).length;
  return late / deltas.length > LATE_SHARE;
}

export function useFrameStrain(active: boolean): boolean {
  const [strained, setStrained] = useState(false);

  useEffect(() => {
    if (!active) return;
    let frameId = 0;
    let timer = 0;
    let strikes = 0;
    let deltas: number[] = [];
    let last = 0;
    let started = 0;

    const measure = (now: number) => {
      if (last) deltas.push(now - last);
      last = now;
      if (now - started < SAMPLE_MS) {
        frameId = requestAnimationFrame(measure);
        return;
      }
      strikes = isStrained(deltas) ? strikes + 1 : 0;
      setStrained(strikes >= STRIKES_TO_FLAG);
      timer = window.setTimeout(begin, PAUSE_MS);
    };

    const begin = () => {
      if (!isWindowVisible()) {
        timer = window.setTimeout(begin, PAUSE_MS);
        return;
      }
      deltas = [];
      last = 0;
      started = performance.now();
      frameId = requestAnimationFrame(measure);
    };

    timer = window.setTimeout(begin, 2000);
    return () => {
      cancelAnimationFrame(frameId);
      window.clearTimeout(timer);
    };
  }, [active]);

  return active && strained;
}
