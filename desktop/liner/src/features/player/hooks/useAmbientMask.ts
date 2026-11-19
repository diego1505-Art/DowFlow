import { useEffect, useState, type RefObject } from "react";

const LYRICS_FADE =
  "linear-gradient(to right, black 30%, rgba(0, 0, 0, 0.12) 62%)";
const HOLE_SELECTOR = "[data-ambient-hole]";
const SETTLE_DELAYS_MS = [120, 450];

function coverHole(host: HTMLElement): string | null {
  const hole = document.querySelector<HTMLElement>(HOLE_SELECTOR);
  if (!hole) return null;
  const hostRect = host.getBoundingClientRect();
  const rect = hole.getBoundingClientRect();
  const x = rect.left - hostRect.left + rect.width / 2;
  const y = rect.top - hostRect.top + rect.height / 2;
  const radius = Math.max(rect.width, rect.height) / 2;
  return `radial-gradient(circle at ${x}px ${y}px, transparent ${radius * 1.1}px, black ${radius * 1.75}px)`;
}

export interface AmbientMask {
  maskImage: string;
  maskComposite: string;
}

export function useAmbientMask(
  hostRef: RefObject<HTMLElement | null>,
): AmbientMask {
  const [hole, setHole] = useState<string | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const update = () => setHole(coverHole(host));
    update();
    const timers = SETTLE_DELAYS_MS.map((delay) =>
      window.setTimeout(update, delay),
    );
    const observer = new ResizeObserver(update);
    observer.observe(host);
    const target = document.querySelector(HOLE_SELECTOR);
    if (target) observer.observe(target);
    window.addEventListener("resize", update);
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [hostRef]);

  return hole
    ? { maskImage: `${hole}, ${LYRICS_FADE}`, maskComposite: "intersect" }
    : { maskImage: LYRICS_FADE, maskComposite: "add" };
}
