// Copy the web-ifc WASM and the fragments worker into public/ so the viewer works offline.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pub = join(root, "public");
mkdirSync(join(pub, "wasm"), { recursive: true });
for (const file of ["web-ifc.wasm", "web-ifc-mt.wasm"]) {
  copyFileSync(join(root, "node_modules", "web-ifc", file), join(pub, "wasm", file));
}
// Not reachable via import: the package's "exports" field hides dist/Worker.
copyFileSync(join(root, "node_modules", "@thatopen", "fragments", "dist", "Worker", "worker.mjs"), join(pub, "fragments-worker.mjs"));
console.log("web-ifc wasm + fragments worker copied to public/");
