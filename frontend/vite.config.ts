import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./", // built files are served from app://bundle/
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  worker: { format: "es" },
  build: { target: "esnext", chunkSizeWarningLimit: 4000 },
});
