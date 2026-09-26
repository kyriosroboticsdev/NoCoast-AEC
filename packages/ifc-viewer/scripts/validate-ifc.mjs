#!/usr/bin/env node
// Node-side sanity check for IFC files: opens each with web-ifc, counts
// meshes, and converts to fragments with the same IfcImporter the viewer uses.
// Exit code 1 if any file fails. Usage: node scripts/validate-ifc.mjs a.ifc b.ifc ...
import * as FRAGS from "@thatopen/fragments";
import * as WEBIFC from "web-ifc";
import { readFileSync } from "node:fs";
import { dirname } from "node:path";
import { createRequire } from "node:module";

const wasmDir =
  dirname(createRequire(import.meta.url).resolve("web-ifc")).split("\\").join("/") + "/";
const api = new WEBIFC.IfcAPI();
api.SetWasmPath(wasmDir, true);
await api.Init();

let failed = 0;
for (const file of process.argv.slice(2)) {
  const bytes = new Uint8Array(readFileSync(file));
  const row = { file };
  try {
    const id = api.OpenModel(bytes);
    let meshes = 0;
    api.StreamAllMeshes(id, () => meshes++);
    row.schema = api.GetModelSchema(id);
    row.meshes = meshes;
    api.CloseModel(id);
    if (meshes === 0) throw new Error("no geometry");
    const importer = new FRAGS.IfcImporter();
    importer.wasm = { absolute: true, path: wasmDir };
    const frag = await importer.process({ bytes });
    row.fragBytes = frag.byteLength;
    row.ok = true;
  } catch (e) {
    row.ok = false;
    row.error = String(e?.message ?? e);
    failed++;
  }
  console.log(JSON.stringify(row));
}
process.exit(failed ? 1 : 0);
