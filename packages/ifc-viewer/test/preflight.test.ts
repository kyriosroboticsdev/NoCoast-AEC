import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { preflightIfc } from "../src/core/preflight";

const enc = (s: string) => new TextEncoder().encode(s);
const fixture = (name: string) =>
  new Uint8Array(readFileSync(new URL(`../playground/public/fixtures/${name}`, import.meta.url)));
const minimal = (schema = "IFC4", end = "END-ISO-10303-21;\n") =>
  enc(`ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('${schema}'));\nENDSEC;\nDATA;\nENDSEC;\n${end}`);

describe("preflightIfc", () => {
  it("accepts every generated turn fixture and reports the schema", () => {
    for (let i = 1; i <= 5; i++) {
      expect(preflightIfc(fixture(`turn-${i}.ifc`))).toEqual({ ok: true, schema: "IFC4" });
    }
  });

  it("rejects the truncated fixture that web-ifc would silently half-render", () => {
    const r = preflightIfc(fixture("broken.ifc"));
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/truncated/);
    expect(r.schema).toBe("IFC4");
  });

  it("accepts IFC2X3 and IFC4X3 variants", () => {
    expect(preflightIfc(minimal("IFC2X3")).ok).toBe(true);
    expect(preflightIfc(minimal("IFC4X3_ADD2")).ok).toBe(true);
  });

  it("rejects empty, non-STEP, zipped, schema-less, and unknown-schema input", () => {
    expect(preflightIfc(new Uint8Array()).error).toMatch(/empty/);
    expect(preflightIfc(enc("hello world")).error).toMatch(/ISO-10303-21/);
    expect(preflightIfc(enc("PK\u0003\u0004...")).error).toMatch(/zip/i);
    expect(preflightIfc(enc("ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;")).error).toMatch(/FILE_SCHEMA/);
    expect(preflightIfc(minimal("CIS2")).error).toMatch(/Unsupported/);
  });

  it("tolerates trailing whitespace after the terminator", () => {
    expect(preflightIfc(minimal("IFC4", "END-ISO-10303-21;\r\n\r\n  ")).ok).toBe(true);
  });
});
