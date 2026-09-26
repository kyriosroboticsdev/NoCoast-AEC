/**
 * Cheap structural checks on IFC STEP text before handing it to web-ifc.
 *
 * web-ifc is lenient: a truncated file still opens and renders whatever
 * entities made it to disk. In an agent loop that is dangerous, because a
 * half-written file looks like a valid but incomplete building. These checks
 * turn that case into an explicit error the loop can react to.
 */
export interface PreflightResult {
  ok: boolean;
  schema?: string;
  error?: string;
}

const HEAD_BYTES = 4096;
const TAIL_BYTES = 512;

export function preflightIfc(bytes: Uint8Array): PreflightResult {
  if (bytes.byteLength === 0) return { ok: false, error: "File is empty." };

  const decoder = new TextDecoder("utf-8", { fatal: false });
  const head = decoder.decode(bytes.subarray(0, HEAD_BYTES));
  const tail = decoder.decode(bytes.subarray(Math.max(0, bytes.byteLength - TAIL_BYTES)));

  if (head.startsWith("PK")) {
    return { ok: false, error: "File is a zip archive (IFCZIP). Unzip it before loading." };
  }
  if (!/^\s*ISO-10303-21\s*;/.test(head)) {
    return { ok: false, error: "Not an IFC STEP file: missing ISO-10303-21 header." };
  }

  const schemaMatch = /FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'/i.exec(head);
  const schema = schemaMatch?.[1]?.toUpperCase();
  if (!schema) {
    return { ok: false, error: "Header has no FILE_SCHEMA declaration." };
  }
  if (!/^IFC(2X3|4|4X1|4X2|4X3)/.test(schema)) {
    return { ok: false, schema, error: `Unsupported IFC schema "${schema}".` };
  }
  if (!/END-ISO-10303-21\s*;\s*$/.test(tail)) {
    return {
      ok: false,
      schema,
      error: "File is truncated: missing END-ISO-10303-21 terminator. The writer may not have finished.",
    };
  }
  return { ok: true, schema };
}
