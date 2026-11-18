import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const rendererRoot = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: rendererRoot,
  base: "/static/music-stream/",
  plugins: [react()],
  build: {
    outDir: resolve(rendererRoot, "../../../static/music-stream"),
    emptyOutDir: true,
    sourcemap: false,
  },
});
