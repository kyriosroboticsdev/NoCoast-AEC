// Smoke check: parse an IFC file with web-ifc (Node build) and count the meshes it produces.
// Usage: node scripts/check-ifc.mjs path/to/file.ifc
import { readFileSync } from "node:fs";
import { IfcAPI } from "web-ifc"; // the "node" export condition resolves to the Node build

const file = process.argv[2];
if (!file) throw new Error("usage: node scripts/check-ifc.mjs <file.ifc>");
const api = new IfcAPI();
await api.Init();
const modelID = api.OpenModel(new Uint8Array(readFileSync(file)));
let products = 0, geometries = 0, triangles = 0;
api.StreamAllMeshes(modelID, (mesh) => {
  products++;
  for (let i = 0; i < mesh.geometries.size(); i++) {
    const g = api.GetGeometry(modelID, mesh.geometries.get(i).geometryExpressID);
    geometries++;
    triangles += g.GetIndexDataSize() / 3;
    g.delete();
  }
});
console.log(JSON.stringify({ file, products, geometries, triangles }));
api.CloseModel(modelID);
