import { defineConfig } from "vite";

// Tauri sets TAURI_ENV_* during `tauri dev`/`tauri build`; nothing here depends on it yet.
export default defineConfig({
  base: "./", // built files load from any path (tauri://localhost/ in the desktop app)
  clearScreen: false,
  server: { port: 5173, strictPort: true },
  optimizeDeps: { exclude: ["web-ifc"] }, // keep the wasm loader untouched by the pre-bundler
  build: { target: "esnext", chunkSizeWarningLimit: 4000 },
});
