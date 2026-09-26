import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Library build. Peer dependencies stay external so the host app owns exactly
// one copy of three / That Open / web-ifc (duplicate copies break That Open).
const external = [
  "react",
  "react-dom",
  "react/jsx-runtime",
  "three",
  "camera-controls",
  "web-ifc",
  "@thatopen/components",
  "@thatopen/fragments",
];

export default defineConfig({
  plugins: [react()],
  build: {
    lib: { entry: "src/index.ts", formats: ["es"], fileName: "index" },
    cssCodeSplit: false,
    sourcemap: true,
    rollupOptions: {
      external: (id) => external.some((e) => id === e || id.startsWith(`${e}/`)),
      output: { assetFileNames: (a) => (a.names?.[0]?.endsWith(".css") ? "style.css" : "assets/[name]-[hash][extname]") },
    },
  },
  worker: { format: "es" },
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});
