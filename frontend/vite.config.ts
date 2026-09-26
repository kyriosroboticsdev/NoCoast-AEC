import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  clearScreen: false, // keep Rust compiler output visible under `tauri dev`
  server: { port: 5173, strictPort: true, watch: { ignored: ["**/src-tauri/**"] } },
  worker: { format: "es" },
  build: { target: "esnext", chunkSizeWarningLimit: 4000 },
});
