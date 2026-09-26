#!/usr/bin/env node
// Generates small, valid IFC4 files that mimic a multi-turn agent session:
// each turn adds elements to a simple two-storey building. Also writes a
// deliberately truncated file to exercise the error path.
//
// Usage: node scripts/make-fixtures.mjs [outDir]

import { mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = process.argv[2] ?? join(here, "..", "playground", "public", "fixtures");

// ---------------------------------------------------------------- helpers

const B64 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$";

/** Deterministic 22-char IFC GlobalId derived from a seed string. */
function guid(seed) {
  const bytes = createHash("md5").update(seed).digest();
  // IFC compresses 128 bits into 22 chars: first char holds 2 bits, rest 6 bits each.
  let n = 0n;
  for (const b of bytes) n = (n << 8n) | BigInt(b);
  const chars = [];
  for (let i = 0; i < 22; i++) {
    chars.unshift(B64[Number(n & 63n)]);
    n >>= 6n;
  }
  chars[0] = B64[B64.indexOf(chars[0]) & 3];
  return chars.join("");
}

const num = (v) => {
  const s = Number(v).toString();
  return s.includes(".") || s.includes("e") ? s : `${s}.`;
};
const str = (s) => (s == null ? "$" : `'${String(s).replace(/'/g, "''")}'`);
const ref = (id) => `#${id}`;
const list = (xs) => `(${xs.join(",")})`;

class IfcWriter {
  lines = [];
  next = 1;
  add(entity) {
    const id = this.next++;
    this.lines.push(`#${id}=${entity};`);
    return id;
  }
  text(name) {
    const header = [
      "ISO-10303-21;",
      "HEADER;",
      "FILE_DESCRIPTION(('ViewDefinition [DesignTransferView]'),'2;1');",
      `FILE_NAME(${str(name)},'2026-09-26T00:00:00',('NoCoast agent'),('NoCoast-AEC'),'make-fixtures','make-fixtures','');`,
      "FILE_SCHEMA(('IFC4'));",
      "ENDSEC;",
      "DATA;",
    ];
    return [...header, ...this.lines, "ENDSEC;", "END-ISO-10303-21;", ""].join("\n");
  }
}

// ---------------------------------------------------------------- model

const COLORS = {
  slab: [0.72, 0.72, 0.7],
  wall: [0.93, 0.89, 0.8],
  column: [0.55, 0.6, 0.66],
  beam: [0.55, 0.6, 0.66],
  roof: [0.62, 0.3, 0.24],
  window: [0.55, 0.78, 0.92],
};

/**
 * Builds an IFC4 model containing the given element specs.
 * Each spec is a box: { kind, name, storey, x, y, z, dx, dy, dz, props }
 * where (x, y, z) is the min corner in metres relative to the storey.
 */
function buildModel(title, specs) {
  const w = new IfcWriter();
  const origin = w.add(`IFCCARTESIANPOINT((0.,0.,0.))`);
  const zDir = w.add(`IFCDIRECTION((0.,0.,1.))`);
  const xDir = w.add(`IFCDIRECTION((1.,0.,0.))`);
  const worldAxis = w.add(`IFCAXIS2PLACEMENT3D(${ref(origin)},${ref(zDir)},${ref(xDir)})`);
  const ctx = w.add(
    `IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,${ref(worldAxis)},$)`,
  );
  const bodyCtx = w.add(
    `IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,${ref(ctx)},$,.MODEL_VIEW.,$)`,
  );
  const lenUnit = w.add(`IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)`);
  const areaUnit = w.add(`IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)`);
  const volUnit = w.add(`IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)`);
  const angUnit = w.add(`IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)`);
  const units = w.add(`IFCUNITASSIGNMENT(${list([lenUnit, areaUnit, volUnit, angUnit].map(ref))})`);
  const project = w.add(
    `IFCPROJECT(${str(guid(title + "project"))},$,${str(title)},$,$,$,$,(${ref(ctx)}),${ref(units)})`,
  );

  const placement = (parent, x, y, z) => {
    const p = w.add(`IFCCARTESIANPOINT((${num(x)},${num(y)},${num(z)}))`);
    const ax = w.add(`IFCAXIS2PLACEMENT3D(${ref(p)},$,$)`);
    return w.add(`IFCLOCALPLACEMENT(${parent ? ref(parent) : "$"},${ref(ax)})`);
  };

  const sitePl = placement(null, 0, 0, 0);
  const site = w.add(
    `IFCSITE(${str(guid(title + "site"))},$,'Site',$,$,${ref(sitePl)},$,$,.ELEMENT.,$,$,$,$,$)`,
  );
  const bldgPl = placement(sitePl, 0, 0, 0);
  const building = w.add(
    `IFCBUILDING(${str(guid(title + "bldg"))},$,'Building',$,$,${ref(bldgPl)},$,$,.ELEMENT.,$,$,$)`,
  );
  w.add(`IFCRELAGGREGATES(${str(guid(title + "agg1"))},$,$,$,${ref(project)},(${ref(site)}))`);
  w.add(`IFCRELAGGREGATES(${str(guid(title + "agg2"))},$,$,$,${ref(site)},(${ref(building)}))`);

  const storeyNames = [...new Set(specs.map((s) => s.storey))].sort((a, b) => a - b);
  const storeys = new Map();
  for (const level of storeyNames) {
    const elev = level * 3.2;
    const pl = placement(bldgPl, 0, 0, elev);
    const id = w.add(
      `IFCBUILDINGSTOREY(${str(guid(title + "storey" + level))},$,${str(`Level ${level}`)},$,$,${ref(pl)},$,$,.ELEMENT.,${num(elev)})`,
    );
    storeys.set(level, { id, pl, elements: [] });
  }
  if (storeys.size) {
    w.add(
      `IFCRELAGGREGATES(${str(guid(title + "agg3"))},$,$,$,${ref(building)},${list([...storeys.values()].map((s) => ref(s.id)))})`,
    );
  }

  const styles = new Map();
  const styleFor = (kind) => {
    if (styles.has(kind)) return styles.get(kind);
    const [r, g, b] = COLORS[kind];
    const col = w.add(`IFCCOLOURRGB($,${num(r)},${num(g)},${num(b)})`);
    const transparency = kind === "window" ? 0.5 : 0;
    const shading = w.add(`IFCSURFACESTYLESHADING(${ref(col)},${num(transparency)})`);
    const style = w.add(`IFCSURFACESTYLE(${str(kind)},.BOTH.,(${ref(shading)}))`);
    styles.set(kind, style);
    return style;
  };

  const ENTITY = {
    slab: (g, n, pl, shape) => `IFCSLAB(${g},$,${n},$,$,${pl},${shape},$,.FLOOR.)`,
    roof: (g, n, pl, shape) => `IFCSLAB(${g},$,${n},$,$,${pl},${shape},$,.ROOF.)`,
    wall: (g, n, pl, shape) => `IFCWALL(${g},$,${n},$,$,${pl},${shape},$,.STANDARD.)`,
    column: (g, n, pl, shape) => `IFCCOLUMN(${g},$,${n},$,$,${pl},${shape},$,.COLUMN.)`,
    beam: (g, n, pl, shape) => `IFCBEAM(${g},$,${n},$,$,${pl},${shape},$,.BEAM.)`,
    window: (g, n, pl, shape) => `IFCWINDOW(${g},$,${n},$,$,${pl},${shape},$,$,$,.WINDOW.,$,$)`,
  };

  for (const spec of specs) {
    const storey = storeys.get(spec.storey);
    const pl = placement(storey.pl, spec.x, spec.y, spec.z);
    // Rectangle profile is centred on its position, so offset by half extents.
    const c = w.add(`IFCCARTESIANPOINT((${num(spec.dx / 2)},${num(spec.dy / 2)}))`);
    const ax2 = w.add(`IFCAXIS2PLACEMENT2D(${ref(c)},$)`);
    const profile = w.add(
      `IFCRECTANGLEPROFILEDEF(.AREA.,$,${ref(ax2)},${num(spec.dx)},${num(spec.dy)})`,
    );
    const solid = w.add(
      `IFCEXTRUDEDAREASOLID(${ref(profile)},${ref(worldAxis)},${ref(zDir)},${num(spec.dz)})`,
    );
    w.add(`IFCSTYLEDITEM(${ref(solid)},(${ref(styleFor(spec.kind))}),$)`);
    const rep = w.add(
      `IFCSHAPEREPRESENTATION(${ref(bodyCtx)},'Body','SweptSolid',(${ref(solid)}))`,
    );
    const shape = w.add(`IFCPRODUCTDEFINITIONSHAPE($,$,(${ref(rep)}))`);
    const g = str(guid(title + spec.name));
    const el = w.add(ENTITY[spec.kind](g, str(spec.name), ref(pl), ref(shape)));
    storey.elements.push(el);

    const props = { ...spec.props, AgentTurn: spec.turn };
    const propIds = Object.entries(props).map(([k, v]) =>
      w.add(
        `IFCPROPERTYSINGLEVALUE(${str(k)},$,${
          typeof v === "number" ? `IFCINTEGER(${Math.round(v)})` : `IFCLABEL(${str(v)})`
        },$)`,
      ),
    );
    const pset = w.add(
      `IFCPROPERTYSET(${str(guid(title + spec.name + "pset"))},$,'NoCoast_Agent',$,${list(propIds.map(ref))})`,
    );
    w.add(
      `IFCRELDEFINESBYPROPERTIES(${str(guid(title + spec.name + "rel"))},$,$,$,(${ref(el)}),${ref(pset)})`,
    );
  }

  for (const [level, s] of storeys) {
    if (!s.elements.length) continue;
    w.add(
      `IFCRELCONTAINEDINSPATIALSTRUCTURE(${str(guid(title + "contain" + level))},$,$,$,${list(s.elements.map(ref))},${ref(s.id)})`,
    );
  }
  return w.text(title);
}

// ---------------------------------------------------------------- turns

const W = 12; // building width (x)
const D = 8; // building depth (y)
const H = 3.2; // storey height
const T = 0.25; // wall thickness

const turns = [
  {
    prompt: "Start a 12 x 8 m two-storey building. Add the ground and first floor slabs.",
    add: (turn) => [
      { kind: "slab", name: "Ground slab", storey: 0, x: 0, y: 0, z: -0.3, dx: W, dy: D, dz: 0.3, props: { Material: "Concrete C30" }, turn },
      { kind: "slab", name: "Level 1 slab", storey: 1, x: 0, y: 0, z: -0.25, dx: W, dy: D, dz: 0.25, props: { Material: "Concrete C30" }, turn },
    ],
  },
  {
    prompt: "Add a column grid at the corners and midspan.",
    add: (turn) =>
      [0, W / 2, W].flatMap((x, i) =>
        [0, D].map((y, j) => ({
          kind: "column",
          name: `Column ${String.fromCharCode(65 + i)}${j + 1}`,
          storey: 0,
          x: Math.min(x, W - 0.3),
          y: Math.min(y, D - 0.3),
          z: 0,
          dx: 0.3,
          dy: 0.3,
          dz: H - 0.25,
          props: { Material: "Steel S355", Profile: "SHS 300" },
          turn,
        })),
      ),
  },
  {
    prompt: "Enclose the ground floor with exterior walls.",
    add: (turn) => [
      { kind: "wall", name: "Wall South", storey: 0, x: 0, y: 0, z: 0, dx: W, dy: T, dz: H - 0.25, props: { Material: "Brick", FireRating: "REI 60" }, turn },
      { kind: "wall", name: "Wall North", storey: 0, x: 0, y: D - T, z: 0, dx: W, dy: T, dz: H - 0.25, props: { Material: "Brick", FireRating: "REI 60" }, turn },
      { kind: "wall", name: "Wall West", storey: 0, x: 0, y: T, z: 0, dx: T, dy: D - 2 * T, dz: H - 0.25, props: { Material: "Brick", FireRating: "REI 60" }, turn },
      { kind: "wall", name: "Wall East", storey: 0, x: W - T, y: T, z: 0, dx: T, dy: D - 2 * T, dz: H - 0.25, props: { Material: "Brick", FireRating: "REI 60" }, turn },
    ],
  },
  {
    prompt: "Add first-floor walls and a row of windows on the south face.",
    add: (turn) => [
      { kind: "wall", name: "L1 Wall South", storey: 1, x: 0, y: 0, z: 0, dx: W, dy: T, dz: H - 0.25, props: { Material: "Timber frame" }, turn },
      { kind: "wall", name: "L1 Wall North", storey: 1, x: 0, y: D - T, z: 0, dx: W, dy: T, dz: H - 0.25, props: { Material: "Timber frame" }, turn },
      { kind: "wall", name: "L1 Wall West", storey: 1, x: 0, y: T, z: 0, dx: T, dy: D - 2 * T, dz: H - 0.25, props: { Material: "Timber frame" }, turn },
      { kind: "wall", name: "L1 Wall East", storey: 1, x: W - T, y: T, z: 0, dx: T, dy: D - 2 * T, dz: H - 0.25, props: { Material: "Timber frame" }, turn },
      ...[1.5, 4.5, 7.5, 10.5].map((x, i) => ({
        kind: "window",
        name: `Window S${i + 1}`,
        storey: 1,
        x: x - 0.6,
        y: -0.05,
        z: 0.9,
        dx: 1.2,
        dy: T + 0.1,
        dz: 1.4,
        props: { Glazing: "Triple", UValue: 1 },
        turn,
      })),
    ],
  },
  {
    prompt: "Cap it with a roof slab and a perimeter beam.",
    add: (turn) => [
      { kind: "roof", name: "Roof slab", storey: 2, x: -0.3, y: -0.3, z: 0, dx: W + 0.6, dy: D + 0.6, dz: 0.3, props: { Material: "CLT", Finish: "Standing seam" }, turn },
      { kind: "beam", name: "Ring beam", storey: 2, x: 0, y: 0, z: -0.4, dx: W, dy: 0.3, dz: 0.4, props: { Material: "Glulam GL28h" }, turn },
    ],
  },
];

mkdirSync(outDir, { recursive: true });
const manifest = [];
let specs = [];
turns.forEach((t, i) => {
  const n = i + 1;
  specs = [...specs, ...t.add(n)];
  const file = `turn-${n}.ifc`;
  const text = buildModel(`NoCoast demo turn ${n}`, specs);
  writeFileSync(join(outDir, file), text);
  manifest.push({ id: `turn-${n}`, file, prompt: t.prompt, elements: specs.length });
  console.log(`${file}: ${specs.length} elements, ${text.length} bytes`);
});

// Truncated copy of the last turn: a realistic "agent wrote half a file" failure.
const last = buildModel("NoCoast demo broken", specs);
writeFileSync(join(outDir, "broken.ifc"), last.slice(0, Math.floor(last.length * 0.4)));
manifest.push({ id: "broken", file: "broken.ifc", prompt: "Simulated failure: the agent wrote a truncated IFC file.", elements: 0 });
console.log("broken.ifc: truncated");

writeFileSync(join(outDir, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(`wrote ${manifest.length} fixtures to ${outDir}`);
