import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const viewerPackage = fileURLToPath(new URL("../packages/ifc-viewer", import.meta.url));

export default defineConfig({
  base: "./",
  plugins: [react()],
  clearScreen: false, // keep Rust compiler output visible under `tauri dev`
  resolve: {
    // The turn-card viewer is consumed from source (no separate build step).
    alias: { "@nocoast/ifc-viewer": `${viewerPackage}/src/index.ts` },
    // One copy of each: two copies of three or That Open in one page break rendering.
    dedupe: ["three", "camera-controls", "web-ifc", "@thatopen/components", "@thatopen/fragments", "react", "react-dom"],
  },
  server: {
    port: 5173,
    strictPort: true,
    watch: { ignored: ["**/src-tauri/**"] },
    fs: { allow: [".", viewerPackage] },
  },
  worker: { format: "es" },
  build: { target: "esnext", chunkSizeWarningLimit: 4000 },
});
