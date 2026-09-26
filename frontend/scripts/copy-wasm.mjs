// Copy the web-ifc WASM into public/ so the IFC loader works offline.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "wasm");
mkdirSync(out, { recursive: true });
for (const file of ["web-ifc.wasm", "web-ifc-mt.wasm"]) {
  copyFileSync(join(root, "node_modules", "web-ifc", file), join(out, file));
}
console.log("web-ifc wasm copied to public/wasm");
