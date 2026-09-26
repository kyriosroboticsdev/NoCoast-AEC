// Integration: the real That Open importer converts every fixture turn, and
// the resulting fragments grow as the agent adds elements.
import { readFileSync } from "node:fs";
import { dirname } from "node:path";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";
import { IfcImporter } from "@thatopen/fragments";

const wasmDir = dirname(createRequire(import.meta.url).resolve("web-ifc")).split("\\").join("/") + "/";
const fixture = (name: string) =>
  new Uint8Array(readFileSync(new URL(`../playground/public/fixtures/${name}`, import.meta.url)));

describe("IFC fixtures convert to fragments", () => {
  it("converts turns 1-5 with monotonically growing output", async () => {
    const sizes: number[] = [];
    for (let i = 1; i <= 5; i++) {
      const importer = new IfcImporter();
      importer.wasm = { absolute: true, path: wasmDir };
      const frag = await importer.process({ bytes: fixture(`turn-${i}.ifc`) });
      expect(frag.byteLength).toBeGreaterThan(1000);
      sizes.push(frag.byteLength);
    }
    for (let i = 1; i < sizes.length; i++) expect(sizes[i]).toBeGreaterThan(sizes[i - 1]);
  }, 60_000);
});
