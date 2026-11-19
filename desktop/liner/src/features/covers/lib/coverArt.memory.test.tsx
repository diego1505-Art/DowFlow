import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import CoverImage from "../ui/CoverImage";
import {
  clearCoverRegistry,
  getCoverElement,
  isCoverReady,
  markCoverReady,
  preloadCoverArt,
} from "./coverArt";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const NativeImage = window.Image;
let constructed: HTMLImageElement[] = [];

class CountingImage extends NativeImage {
  constructor(width?: number, height?: number) {
    super(width, height);
    constructed.push(this);
  }
}

const TOTAL_COVERS = 2000;
const PAGE_SIZE = 100;
const coverUrl = (index: number) => `https://example.com/covers/${index}.jpg`;

async function renderPage(urls: string[]) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <div>
        {urls.map((url) => (
          <CoverImage key={url} src={url} width={48} height={48} />
        ))}
      </div>,
    );
  });
  const rendered = Array.from(container.querySelectorAll("img"));
  await act(async () => {
    for (const img of rendered) img.dispatchEvent(new Event("load"));
  });
  return {
    rendered,
    async unmount() {
      await act(async () => {
        root.unmount();
      });
      container.remove();
    },
  };
}

async function browse() {
  const rendered = new Set<HTMLImageElement>();
  for (let start = 0; start < TOTAL_COVERS; start += PAGE_SIZE) {
    const urls = Array.from({ length: PAGE_SIZE }, (_, offset) =>
      coverUrl(start + offset),
    );
    const page = await renderPage(urls);
    for (const img of page.rendered) rendered.add(img);
    await page.unmount();
  }
  const urls = Array.from({ length: TOTAL_COVERS }, (_, index) =>
    coverUrl(index),
  );
  const retainedEntries = urls.filter((url) => isCoverReady(url)).length;
  const referenced = urls
    .map((url) => getCoverElement(url))
    .filter((el): el is HTMLImageElement => !!el);
  const retainedRenderedElements = referenced.filter((el) =>
    rendered.has(el),
  ).length;
  const retainedDetachedSubtrees = referenced.filter(
    (el) => !el.isConnected && el.parentNode,
  ).length;
  return {
    retainedEntries,
    retainedRenderedElements,
    retainedDetachedSubtrees,
    referencedElements: referenced.length,
    imagesPerCover: constructed.length / TOTAL_COVERS,
  };
}

describe("cover registry memory", () => {
  beforeEach(() => {
    constructed = [];
    window.Image = CountingImage as typeof Image;
    clearCoverRegistry();
  });

  afterEach(() => {
    window.Image = NativeImage;
    clearCoverRegistry();
  });

  it("stays bounded and holds no rendered dom after browsing 2000 covers", async () => {
    const stats = await browse();
    console.info("cover registry after browsing", JSON.stringify(stats));
    expect(stats.retainedRenderedElements).toBe(0);
    expect(stats.retainedDetachedSubtrees).toBe(0);
    expect(stats.imagesPerCover).toBe(0);
    expect(stats.retainedEntries).toBeLessThanOrEqual(300);
    expect(stats.retainedEntries).toBeGreaterThan(0);
  }, 60_000);

  it("revisits a recent page without a new fetch and keeps the working fallback url", async () => {
    const url = "https://example.com/covers/revisit.jpg";
    const proxy = "https://covers.example.com/revisit.jpg";
    markCoverReady(url, proxy);
    const page = await renderPage([url]);
    expect(page.rendered[0].getAttribute("src")).toBe(proxy);
    expect(constructed.length).toBe(0);
    await page.unmount();
    expect(isCoverReady(url)).toBe(true);
  });

  it("serves decoded images to pixel consumers from a small owned cache", async () => {
    const urls = Array.from({ length: 12 }, (_, index) => coverUrl(index));
    const page = await renderPage(urls);
    await page.unmount();
    for (const url of urls) {
      const pending = preloadCoverArt(url);
      const img = constructed[constructed.length - 1];
      img.dispatchEvent(new Event("load"));
      await pending;
      const element = getCoverElement(url);
      expect(element).toBe(img);
      expect(element?.isConnected).toBe(false);
      expect(element?.parentNode).toBeNull();
    }
    expect(constructed.length).toBe(12);
    const held = urls.filter((url) => getCoverElement(url)).length;
    expect(held).toBe(8);
    expect(getCoverElement(urls[11])).toBe(constructed[11]);
    expect(getCoverElement(urls[0])).toBeUndefined();
  });

  it("resolves the decoded image by its effective url", async () => {
    const url = "https://example.com/covers/proxied.jpg";
    const proxy = "https://covers.example.com/proxied.jpg";
    markCoverReady(url, proxy);
    const pending = preloadCoverArt(proxy);
    const img = constructed[constructed.length - 1];
    expect(img.src).toBe(proxy);
    img.dispatchEvent(new Event("load"));
    await pending;
    expect(getCoverElement(proxy)).toBe(img);
    expect(getCoverElement(url)).toBe(img);
    expect(constructed.length).toBe(1);
  });

  it("fails over to the proxy and still retries a cover that failed entirely", async () => {
    const proxyable = "https://i1.sndcdn.com/artworks-abc-t500x500.jpg";
    const pending = preloadCoverArt(proxyable);
    const img = constructed[0];
    img.dispatchEvent(new Event("error"));
    await vi.waitFor(() => expect(img.src).toContain("covers.tryliner.fun"));
    img.dispatchEvent(new Event("load"));
    await pending;
    expect(isCoverReady(proxyable)).toBe(true);
    expect(getCoverElement(proxyable)).toBe(img);
    expect(getCoverElement(img.src)).toBe(img);

    const broken = "https://example.com/covers/broken.jpg";
    const failed = preloadCoverArt(broken);
    constructed[1].dispatchEvent(new Event("error"));
    await vi.waitFor(() => expect(constructed.length).toBe(3));
    expect(constructed[2].crossOrigin).toBeFalsy();
    expect(constructed[2].src).toBe(broken);
    constructed[2].dispatchEvent(new Event("error"));
    await failed;
    expect(isCoverReady(broken)).toBe(false);
    void preloadCoverArt(broken);
    expect(constructed.length).toBe(4);
    expect(constructed[3].src).toBe(broken);
  });
});
