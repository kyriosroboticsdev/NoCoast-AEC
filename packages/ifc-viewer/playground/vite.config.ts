import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

/** Copy web-ifc.wasm into public/wasm so it is served locally, never from a CDN. */
function copyWebIfcWasm(): Plugin {
  return {
    name: "copy-web-ifc-wasm",
    buildStart() {
      const src = resolve(dirname(require.resolve("web-ifc")), "web-ifc.wasm");
      const outDir = resolve(here, "public", "wasm");
      mkdirSync(outDir, { recursive: true });
      copyFileSync(src, resolve(outDir, "web-ifc.wasm"));
    },
  };
}

// Browser-only playground for iterating on the viewer. Not part of the app build.
export default defineConfig({
  root: here,
  plugins: [react(), copyWebIfcWasm()],
  resolve: {
    alias: { "@nocoast/ifc-viewer": resolve(here, "../src/index.ts") },
    dedupe: ["three", "@thatopen/components", "@thatopen/fragments", "web-ifc"],
  },
  worker: { format: "es" },
  optimizeDeps: { exclude: ["web-ifc"] },
  server: { port: 5178, strictPort: true },
  preview: { port: 5179, strictPort: true },
  // Unminified so browser-test stack traces name the real functions.
  build: { outDir: resolve(here, "dist"), emptyOutDir: true, target: "es2022", minify: false, sourcemap: true },
});
