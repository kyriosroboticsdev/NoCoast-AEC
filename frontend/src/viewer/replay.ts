// Build replay: slice the loaded model into horizontal layers, like a 3D-printer slicer preview, and play the
// layers back — the model grows layer by layer while the current layer's toolpath is traced by a moving
// nozzle. The same layers export as preview G-code.
//
// It slices the meshes the viewer already has (web-ifc tessellation, world coordinates), so it works for any
// opened IFC, including files that never went through the backend. It mirrors backend/slicer: construction
// phases from schemas/phases.py, the G-code dialect of slicer/gcode.py (metres, travel + draw moves, no E axis).
// Visualization only: nothing here is tuned for a real printer or robot.

import * as THREE from "three";
import type { LegacyViewer } from "./LegacyViewer";

export const PHASES = ["foundation", "structure", "roof", "plumbing", "mechanical", "spaces", "electrical", "details", "site"] as const;
export type Phase = (typeof PHASES)[number];
/** "height": one layer at a time across the whole model, bottom to top, like a printer. "phase": the backend's
 *  construction order — every slab, then every wall and column, then roofs … — each phase bottom to top. */
export type Order = "height" | "phase";

export const PHASE_COLORS: Record<Phase, string> = {
  foundation: "#9aa1ab", structure: "#f0a53a", roof: "#e0643c", plumbing: "#3d93e8", mechanical: "#8a6ce0",
  spaces: "#58b7e8", electrical: "#e8cf3d", details: "#4fc6a4", site: "#6fbf4a",
};

// schemas/phases.py resolves a class through its IFC ancestors; the viewer only knows the concrete class name,
// so this lists the concrete classes those ancestors cover.
const RULES: [RegExp, Phase][] = [
  [/^IFC(FOOTING|PILE|SLAB)/, "foundation"],
  [/^IFC(WALL|COLUMN|BEAM|MEMBER|PLATE|STAIR|RAMP|CHIMNEY|TRANSPORTELEMENT|CURTAINWALL)/, "structure"],
  [/^IFCROOF/, "roof"],
  [/^IFCSPACE$/, "spaces"],
  [/^IFC(OUTLET|SWITCHINGDEVICE|ELECTRICDISTRIBUTIONBOARD|CABLESEGMENT|CABLEFITTING|SENSOR|ACTUATOR|ALARM|CONTROLLER|FLOWINSTRUMENT|UNITARYCONTROLELEMENT|ELECTRICFLOWSTORAGEDEVICE)/, "electrical"],
  [/^IFC(BOILER|CHILLER|COIL|COOLINGTOWER|HEATEXCHANGER|HUMIDIFIER|UNITARYEQUIPMENT|AIRTOAIRHEATRECOVERY|BURNER|ENGINE|EVAPORATOR|CONDENSER|FAN|PUMP|COMPRESSOR|TANK|VALVE|DAMPER|FLOWMETER|FILTER|INTERCEPTOR|DUCTSILENCER|ELECTRICGENERATOR|SOLARDEVICE|TRANSFORMER|MOTORCONNECTION|FLOWCONTROLLER|ENERGYCONVERSIONDEVICE|FLOWMOVINGDEVICE|FLOWSTORAGEDEVICE|FLOWTREATMENTDEVICE)/, "mechanical"],
  [/^IFC(PIPESEGMENT|PIPEFITTING|DUCTSEGMENT|DUCTFITTING|CABLECARRIERSEGMENT|CABLECARRIERFITTING|FLOWSEGMENT|FLOWFITTING)/, "plumbing"],
  [/^IFC(GEOGRAPHICELEMENT|CIVILELEMENT)/, "site"],
];
export const phaseOf = (ifcClass: string): Phase => RULES.find(([re]) => re.test(ifcClass))?.[1] ?? "details";

export interface Step {
  layer: number;
  z: number; // plane height in metres (three.js Y = IFC Z)
  phase: Phase | "mixed";
  start: number; // first segment in the toolpath buffer
  count: number; // segments in this step
}

export interface Sliced {
  steps: Step[];
  layers: number;
  layerHeight: number;
  segments: number;
  bottom: number;
  top: number;
  phases: Phase[]; // present in this model, in build order
}

interface Source { mesh: THREE.Mesh; phase: Phase; positions: Float32Array; index: ArrayLike<number>; y0: number; y1: number }

const TARGET_LAYERS = 220;
const NICE = [0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5];

function niceStep(raw: number) {
  return NICE.find((n) => n >= raw) ?? NICE[NICE.length - 1];
}

/** Grow-on-demand float buffer (toolpaths for a large model run to millions of segments). */
class Floats {
  data = new Float32Array(1 << 16);
  length = 0;
  push4(a: number, b: number, c: number, d: number) {
    if (this.length + 4 > this.data.length) {
      const next = new Float32Array(this.data.length * 2);
      next.set(this.data);
      this.data = next;
    }
    this.data[this.length++] = a; this.data[this.length++] = b; this.data[this.length++] = c; this.data[this.length++] = d;
  }
}

export interface ReplayState {
  ready: boolean;
  progress: number; // slicing progress 0..1
  playing: boolean;
  step: number; // index into steps (fractional while playing)
  total: number;
  label: string;
  order: Order;
  toolpathsOnly: boolean;
  speed: number;
  info: Sliced | null;
}

export class BuildReplay {
  private sources: Source[] = [];
  private originals = new Map<THREE.Mesh, { visible: boolean; planes: THREE.Plane[] | null }>();
  private plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
  private group = new THREE.Group();
  private history!: THREE.LineSegments;
  private current!: THREE.LineSegments;
  private nozzle!: THREE.Group;
  private laser!: THREE.Mesh;
  private sliced: Sliced | null = null;
  private buckets = new Map<string, Floats>(); // `${phase}:${layer}` → x1 z1 x2 z2 …
  private order: Order = "height";
  private toolpathsOnly = false;
  private playing = false;
  private t = 0; // position in steps
  private speed = 1;
  private cancelled = false;
  private offTick: (() => void) | null = null;
  private last = 0;
  private cutoff = 1e6; // the section slider's cut, put back on close

  constructor(private viewer: LegacyViewer, private notify: (s: ReplayState) => void) {}

  // --- slicing ----------------------------------------------------------------

  async slice() {
    const meshes = this.viewer.modelMeshes().filter((m) => this.viewer.className(m) !== "IFCSPACE");
    let bottom = Infinity, top = -Infinity;
    const v = new THREE.Vector3();
    for (const mesh of meshes) {
      const pos = mesh.geometry.getAttribute("position") as THREE.BufferAttribute;
      const idx = mesh.geometry.getIndex();
      if (!idx) continue;
      const world = new Float32Array(pos.count * 3);
      let y0 = Infinity, y1 = -Infinity;
      for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld);
        world[i * 3] = v.x; world[i * 3 + 1] = v.y; world[i * 3 + 2] = v.z;
        if (v.y < y0) y0 = v.y;
        if (v.y > y1) y1 = v.y;
      }
      this.sources.push({ mesh, phase: phaseOf(this.viewer.className(mesh)), positions: world, index: idx.array, y0, y1 });
      bottom = Math.min(bottom, y0);
      top = Math.max(top, y1);
      this.originals.set(mesh, { visible: mesh.visible, planes: (mesh.material as THREE.Material).clippingPlanes });
    }
    if (!this.sources.length) throw new Error("nothing to slice");
    const h = niceStep((top - bottom) / TARGET_LAYERS);
    const layers = Math.max(1, Math.ceil((top - bottom) / h));
    const planeY = (k: number) => bottom + (k + 0.5) * h;

    let segments = 0;
    let lastYield = performance.now();
    for (let s = 0; s < this.sources.length; s++) {
      if (this.cancelled) return;
      const src = this.sources[s];
      const { positions: p, index } = src;
      // Thinner than a layer (a road, a lintel): give it one slice through its middle so it still prints.
      const k0 = Math.max(0, Math.ceil((src.y0 - bottom) / h - 0.5));
      const k1 = Math.min(layers - 1, Math.floor((src.y1 - bottom) / h - 0.5));
      const forced = k1 < k0 ? Math.min(layers - 1, Math.max(0, Math.round((src.y0 + src.y1) / 2 / h - bottom / h - 0.5))) : -1;
      const midY = (src.y0 + src.y1) / 2;
      for (let t = 0; t < index.length; t += 3) {
        const a = index[t] * 3, b = index[t + 1] * 3, c = index[t + 2] * 3;
        const ya = p[a + 1], yb = p[b + 1], yc = p[c + 1];
        const lo = Math.min(ya, yb, yc), hi = Math.max(ya, yb, yc);
        const from = forced >= 0 ? forced : Math.max(k0, Math.ceil((lo - bottom) / h - 0.5));
        const to = forced >= 0 ? forced : Math.min(k1, Math.floor((hi - bottom) / h - 0.5));
        for (let k = from; k <= to; k++) {
          const y = (forced >= 0 ? midY : planeY(k)) + 1e-5;
          const pts: number[] = [];
          for (const [i, j] of [[a, b], [b, c], [c, a]]) {
            const yi = p[i + 1] - y, yj = p[j + 1] - y;
            if ((yi < 0) !== (yj < 0)) {
              const f = yi / (yi - yj);
              pts.push(p[i] + (p[j] - p[i]) * f, p[i + 2] + (p[j + 2] - p[i + 2]) * f);
            }
          }
          if (pts.length === 4 && Math.hypot(pts[2] - pts[0], pts[3] - pts[1]) > 0.005) {
            const key = `${src.phase}:${k}`;
            let bucket = this.buckets.get(key);
            if (!bucket) this.buckets.set(key, (bucket = new Floats()));
            bucket.push4(pts[0], pts[1], pts[2], pts[3]);
            segments++;
          }
        }
      }
      if (performance.now() - lastYield > 24) { // keep the UI responsive while slicing
        this.emit({ progress: s / this.sources.length });
        await new Promise((r) => setTimeout(r, 0));
        lastYield = performance.now();
      }
    }
    const present = new Set([...this.buckets.keys()].map((k) => k.split(":")[0]));
    this.sliced = { steps: [], layers, layerHeight: h, segments, bottom, top, phases: PHASES.filter((p) => present.has(p)) };
    this.buildScene();
    this.setOrder("height");
  }

  // --- toolpath buffers for the chosen order ----------------------------------

  private buildScene() {
    const box = new THREE.Box3();
    for (const s of this.sources) box.expandByObject(s.mesh);
    const size = box.getSize(new THREE.Vector3());
    const span = Math.max(size.x, size.z, 1);

    const material = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9, depthWrite: false });
    this.history = new THREE.LineSegments(new THREE.BufferGeometry(), material);
    this.current = new THREE.LineSegments(new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: 0xffd27a, transparent: true, opacity: 1, depthTest: false }));
    this.current.renderOrder = 10;
    this.history.frustumCulled = this.current.frustumCulled = false;

    // The print head: a nozzle with a short carriage above it.
    const r = span / 260;
    this.nozzle = new THREE.Group();
    const tip = new THREE.Mesh(new THREE.ConeGeometry(r * 1.6, r * 4, 16), new THREE.MeshBasicMaterial({ color: 0xff9a2e, depthTest: false }));
    tip.rotation.x = Math.PI;
    tip.position.y = r * 2;
    const body = new THREE.Mesh(new THREE.BoxGeometry(r * 5, r * 3, r * 5), new THREE.MeshBasicMaterial({ color: 0x3b3f46, depthTest: false }));
    body.position.y = r * 5.5;
    const glow = new THREE.Mesh(new THREE.SphereGeometry(r * 1.1, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffe2a8, depthTest: false }));
    for (const m of [tip, body, glow]) m.renderOrder = 11;
    this.nozzle.add(tip, body, glow);

    // A faint sheet at the current layer, the width of the model.
    this.laser = new THREE.Mesh(new THREE.PlaneGeometry(size.x * 1.04, size.z * 1.04),
      new THREE.MeshBasicMaterial({ color: 0xffb347, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false }));
    this.laser.rotation.x = -Math.PI / 2;
    const c = box.getCenter(new THREE.Vector3());
    this.laser.position.set(c.x, 0, c.z);

    this.group.add(this.history, this.current, this.laser, this.nozzle);
    this.viewer.addOverlay(this.group);
    this.cutoff = this.viewer.layerCutoff();
    this.viewer.setLayerCutoff(1e6); // the section slider's cut would hide the upper layers
    this.offTick = this.viewer.onFrame(() => this.tick());
  }

  private layout(order: Order) {
    const s = this.sliced!;
    const steps: Step[] = [];
    const chunks: { floats: Floats; phase: Phase; layer: number }[] = [];
    let start = 0;
    const push = (layer: number, phase: Phase | "mixed", parts: { floats: Floats; phase: Phase }[]) => {
      const count = parts.reduce((n, q) => n + q.floats.length / 4, 0);
      if (!count) return;
      steps.push({ layer, z: s.bottom + (layer + 0.5) * s.layerHeight, phase, start, count });
      chunks.push(...parts.map((q) => ({ ...q, layer })));
      start += count;
    };
    if (order === "height") {
      for (let k = 0; k < s.layers; k++) {
        const parts = PHASES.flatMap((ph) => (this.buckets.has(`${ph}:${k}`) ? [{ floats: this.buckets.get(`${ph}:${k}`)!, phase: ph }] : []));
        push(k, parts.length === 1 ? parts[0].phase : "mixed", parts);
      }
    } else {
      for (const ph of PHASES) {
        for (let k = 0; k < s.layers; k++) {
          const f = this.buckets.get(`${ph}:${k}`);
          if (f) push(k, ph, [{ floats: f, phase: ph }]);
        }
      }
    }
    const positions = new Float32Array(start * 6);
    const colors = new Float32Array(start * 6);
    const tmp = new THREE.Color();
    let o = 0;
    for (const { floats, phase, layer } of chunks) {
      tmp.set(PHASE_COLORS[phase]);
      const y = s.bottom + (layer + 0.5) * s.layerHeight;
      for (let i = 0; i < floats.length; i += 4) {
        positions[o] = floats.data[i]; positions[o + 1] = y; positions[o + 2] = floats.data[i + 1];
        positions[o + 3] = floats.data[i + 2]; positions[o + 4] = y; positions[o + 5] = floats.data[i + 3];
        colors.set([tmp.r, tmp.g, tmp.b, tmp.r, tmp.g, tmp.b], o);
        o += 6;
      }
    }
    return { steps, positions, colors };
  }

  // --- controls -----------------------------------------------------------------

  setOrder(order: Order) {
    if (!this.sliced) return;
    this.order = order;
    const { steps, positions, colors } = this.layout(order);
    this.sliced.steps = steps;
    const pos = new THREE.BufferAttribute(positions, 3);
    const col = new THREE.BufferAttribute(colors, 3);
    for (const line of [this.history, this.current]) {
      line.geometry.dispose();
      line.geometry = new THREE.BufferGeometry();
      line.geometry.setAttribute("position", pos);
      line.geometry.setAttribute("color", col);
    }
    this.seek(0);
    this.play();
  }

  play() {
    if (!this.sliced) return;
    if (this.t >= this.sliced.steps.length) this.t = 0;
    this.playing = true;
    this.last = performance.now();
    this.render();
  }

  pause() {
    this.playing = false;
    this.render();
  }

  toggle() {
    if (this.playing) this.pause(); else this.play();
  }

  seek(step: number) {
    if (!this.sliced) return;
    this.t = Math.max(0, Math.min(step, this.sliced.steps.length));
    this.render();
  }

  setSpeed(speed: number) {
    this.speed = speed;
    this.render();
  }

  setToolpathsOnly(on: boolean) {
    this.toolpathsOnly = on;
    this.render();
  }

  /** Seconds per step at 1×: long models play faster so a replay takes 30–75 s. */
  private stepSeconds() {
    const n = this.sliced?.steps.length ?? 1;
    return Math.min(75, Math.max(30, n * 0.14)) / n;
  }

  private tick() {
    if (!this.playing || !this.sliced) return;
    const now = performance.now();
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    this.t += (dt * this.speed) / this.stepSeconds();
    if (this.t >= this.sliced.steps.length) {
      this.t = this.sliced.steps.length;
      this.playing = false;
    }
    this.render();
  }

  // --- drawing ------------------------------------------------------------------

  private render() {
    const s = this.sliced;
    if (!s) return;
    const steps = s.steps;
    const done = this.t >= steps.length;
    const i = Math.min(Math.floor(this.t), steps.length - 1);
    const step = steps[i];
    const frac = done ? 1 : this.t - i;
    const drawn = Math.floor(step.count * frac);

    // Toolpath history: every finished step, plus the part of this one the nozzle has passed.
    this.history.geometry.setDrawRange(0, (step.start + drawn) * 2);
    // Only in toolpath view: drawn over the solid model it would tint every finished wall.
    this.history.visible = this.toolpathsOnly;
    this.current.geometry.setDrawRange(step.start * 2, drawn * 2);
    this.current.visible = !done;
    this.laser.visible = !done;
    this.laser.position.y = step.z;
    this.nozzle.visible = !done;
    const pos = this.current.geometry.getAttribute("position") as THREE.BufferAttribute | undefined;
    if (pos && drawn > 0) {
      const v = (step.start + drawn) * 2 - 1;
      this.nozzle.position.set(pos.getX(v), pos.getY(v), pos.getZ(v));
    } else if (pos) {
      this.nozzle.position.set(pos.getX(step.start * 2), step.z, pos.getZ(step.start * 2));
    }

    // The solid model: finished below the current layer (per phase in construction order), hidden above.
    const phaseIndex = this.order === "phase" && step.phase !== "mixed" ? PHASES.indexOf(step.phase) : -1;
    this.plane.constant = done ? 1e6 : step.z - s.layerHeight / 2;
    for (const src of this.sources) {
      const mat = src.mesh.material as THREE.Material;
      const base = this.originals.get(src.mesh)!;
      if (this.toolpathsOnly) {
        src.mesh.visible = false;
        continue;
      }
      if (done) {
        src.mesh.visible = base.visible;
        mat.clippingPlanes = base.planes;
        continue;
      }
      const pi = PHASES.indexOf(src.phase);
      if (phaseIndex >= 0 && pi < phaseIndex) {
        src.mesh.visible = base.visible;
        mat.clippingPlanes = base.planes;
      } else if (phaseIndex >= 0 && pi > phaseIndex) {
        src.mesh.visible = false;
      } else {
        src.mesh.visible = base.visible && src.y0 < step.z;
        mat.clippingPlanes = [...(base.planes ?? []), this.plane];
      }
    }

    const phase = step.phase === "mixed" ? "" : ` · ${step.phase}`;
    this.emit({
      label: done ? `Built · ${s.layers} layers of ${s.layerHeight} m` : `Layer ${step.layer + 1} / ${s.layers} · z ${step.z.toFixed(2)} m${phase}`,
    });
  }

  private emit(extra: Partial<ReplayState>) {
    const s = this.sliced;
    this.notify({
      ready: !!s, progress: s ? 1 : 0, playing: this.playing, step: this.t, total: s?.steps.length ?? 0, label: "",
      order: this.order, toolpathsOnly: this.toolpathsOnly, speed: this.speed, info: s, ...extra,
    });
  }

  // --- G-code -------------------------------------------------------------------

  /** Preview G-code in the backend's dialect (slicer/gcode.py): metres, IFC axes (z up), one block per layer. */
  gcode(title: string): string {
    const s = this.sliced;
    if (!s) return "";
    const pos = this.history.geometry.getAttribute("position") as THREE.BufferAttribute;
    const out = [
      "; NoCoast-AEC slice preview -- visualization only, not tuned for any printer or robot",
      "; coordinates are metres (BuildingSpec's unit), not the usual G-code millimetres",
      `; model: ${title}`,
      `; ${s.layers} layers of ${s.layerHeight} m, order: ${this.order === "height" ? "by height" : "by construction phase"}`,
      "G90 ; absolute positioning",
    ];
    let phase: string | null = null;
    const f = (n: number) => n.toFixed(3);
    s.steps.forEach((st, i) => {
      if (st.phase !== phase) {
        phase = st.phase;
        out.push(`; --- phase: ${phase} ---`);
      }
      out.push(`; layer ${i} z=${f(st.z)}`, `G0 Z${f(st.z)}`);
      for (let k = st.start; k < st.start + st.count; k++) {
        // three.js (x, y, z) → IFC (x, -z, y)
        out.push(`G0 X${f(pos.getX(k * 2))} Y${f(-pos.getZ(k * 2))}`, `G1 X${f(pos.getX(k * 2 + 1))} Y${f(-pos.getZ(k * 2 + 1))}`);
      }
    });
    return out.join("\n") + "\n";
  }

  // --- teardown -----------------------------------------------------------------

  dispose() {
    this.cancelled = true;
    this.playing = false;
    this.offTick?.();
    for (const [mesh, base] of this.originals) {
      mesh.visible = base.visible;
      (mesh.material as THREE.Material).clippingPlanes = base.planes;
    }
    this.viewer.removeOverlay(this.group);
    if (this.sliced) this.viewer.setLayerCutoff(this.cutoff);
    this.group.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose();
      (m.material as THREE.Material | undefined)?.dispose();
    });
  }
}
