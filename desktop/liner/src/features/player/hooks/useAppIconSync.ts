import { useEffect } from "react";
import { useTheme } from "next-themes";
import logo from "@/assets/logo.svg";

interface IconLayout {
  canvas: number;
  inset: number;
  radius: number;
  logo: { x: number; y: number; width: number; height: number };
  shadow: boolean;
}

const FULL_BLEED: IconLayout = {
  canvas: 512,
  inset: 0,
  radius: 112,
  logo: { x: 112, y: 144, width: 288, height: 224 },
  shadow: false,
};

const MAC_DOCK: IconLayout = {
  canvas: 1024,
  inset: 100,
  radius: 185,
  logo: { x: 280.25, y: 331.75, width: 463.5, height: 360.5 },
  shadow: true,
};

function loadLogo(): Promise<HTMLImageElement> {
  const img = new Image();
  img.crossOrigin = "anonymous";
  return new Promise((resolve, reject) => {
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load logo for icon"));
    img.src = logo;
  });
}

async function renderIconDataUrl(
  isLight: boolean,
  layout: IconLayout,
): Promise<string> {
  const canvas = document.createElement("canvas");
  canvas.width = layout.canvas;
  canvas.height = layout.canvas;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";

  const size = layout.canvas - layout.inset * 2;
  ctx.beginPath();
  if (typeof ctx.roundRect === "function") {
    ctx.roundRect(layout.inset, layout.inset, size, size, layout.radius);
  } else {
    ctx.rect(layout.inset, layout.inset, size, size);
  }
  if (layout.shadow) {
    ctx.shadowColor = "rgba(0, 0, 0, 0.3)";
    ctx.shadowBlur = 24;
    ctx.shadowOffsetY = 10;
  }
  ctx.fillStyle = isLight ? "#f5f5f7" : "#0d0d10";
  ctx.fill();
  ctx.shadowColor = "transparent";

  ctx.lineWidth = 2;
  ctx.strokeStyle = isLight
    ? "rgba(0, 0, 0, 0.08)"
    : "rgba(255, 255, 255, 0.08)";
  ctx.stroke();

  const img = await loadLogo();
  if (isLight) {
    ctx.filter = "invert(1)";
  }
  const { x, y, width, height } = layout.logo;
  ctx.drawImage(img, x, y, width, height);
  return canvas.toDataURL("image/png");
}

export function useAppIconSync() {
  const { theme, resolvedTheme } = useTheme();

  useEffect(() => {
    const isLight = (resolvedTheme || theme) === "light";
    let active = true;

    const layout =
      window.linerElectron?.platform === "darwin" ? MAC_DOCK : FULL_BLEED;

    void renderIconDataUrl(isLight, layout).then((dataUrl) => {
      if (!active || !dataUrl) return;

      if (window.linerElectron?.setAppIcon) {
        window.linerElectron.setAppIcon(dataUrl, {
          isDefault: true,
        });
      }

      let favicon =
        document.querySelector<HTMLLinkElement>("link[rel~='icon']");
      if (!favicon) {
        favicon = document.createElement("link");
        favicon.rel = "icon";
        document.head.appendChild(favicon);
      }
      favicon.href = dataUrl;
    });

    return () => {
      active = false;
    };
  }, [theme, resolvedTheme]);
}
