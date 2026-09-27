// IFC → meshes with web-ifc (thatopen/engine_web-ifc), drawn with three.js.
// web-ifc only parses and tessellates; it does not render, hence three.js.
//
// This is kyriolexy's original viewer from before the React/Tauri redesign, restored because the
// That Open/Fragments-based BimViewer's rendering and camera zoom felt worse in practice. It trades
// away BimViewer's model tree, property-set browser and per-category hide/isolate (all built on
// Fragments, which this engine doesn't have) for the rendering and camera feel this replaces.

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import * as WebIFC from "web-ifc";

export interface Picked {
  expressID: number;
  type: string;
  name: string;
  tag: string; // spec element id (the IFC Tag, or the Name for spaces)
  globalId: string;
  point: { x: number; y: number; z: number }; // hit point in IFC coordinates (metres, z up)
}

export interface PropertySet { name: string; props: [string, string][] }

export type ViewName = "top" | "bottom" | "front" | "back" | "left" | "right" | "isometric";

const HIGHLIGHT = new THREE.Color(0x2f6bff);
const tagOf = (line: Record<string, { value?: string } | undefined>) => line.Tag?.value ?? (line.LongName ? line.Name?.value ?? "" : "");

/** One building storey as read from the IFC: its elevation and the top of its walls (both in metres, three.js Y). */
export interface Storey { id: string; name: string; elevation: number; top: number }

interface Fade { mesh: THREE.Mesh; from: number; to: number; start: number; ms: number; drop: boolean }
const FADE_IN_MS = 300;
const FADE_OUT_MS = 200;

export class LegacyViewer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera3: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private root = new THREE.Group(); // web-ifc already converts IFC's Z-up placements to Y-up, so no rotation here
  private ifc = new WebIFC.IfcAPI();
  private modelID: number | null = null;
  private raycaster = new THREE.Raycaster();
  private ready: Promise<void>;
  private clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
  private box = new THREE.Box3();
  private storeyList: Storey[] = [];
  private byGuid = new Map<string, THREE.Mesh[]>();
  private fades: Fade[] = [];
  private roomsVisible = false;

  onSelect: (p: Picked | null) => void = () => {};

  constructor(private container: HTMLElement) {
    const canvas = document.createElement("canvas");
    container.appendChild(canvas);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.localClippingEnabled = true;
    this.scene.background = new THREE.Color(0x0f1115);
    this.camera3 = new THREE.PerspectiveCamera(50, 1, 0.01, 2000);
    this.camera3.position.set(25, 20, 25);
    this.controls = new OrbitControls(this.camera3, canvas);
    this.controls.enableDamping = true;
    this.controls.minDistance = 0.05; // let you get right up against a wall or a piece of furniture

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x444466, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(30, 50, 20);
    this.scene.add(sun);
    const grid = new THREE.GridHelper(60, 60, 0x333844, 0x22252d);
    (grid.material as THREE.Material).clippingPlanes = [this.clipPlane];
    this.scene.add(grid);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(200, 200),
      new THREE.MeshBasicMaterial({ color: 0x0b0d12, transparent: true, opacity: 0.75, depthWrite: false, clippingPlanes: [this.clipPlane] }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    this.scene.add(ground);
    this.scene.add(this.root);

    const wasmPath = new URL("wasm/", document.baseURI).href;
    this.ifc.SetWasmPath(wasmPath, true);
    this.ready = this.ifc.Init().then(
      () => console.log("[nocoast:viewer] web-ifc ready", this.ifc.GetVersion?.() ?? ""),
      (err) => { console.error("[nocoast:viewer] web-ifc init FAILED (is public/wasm populated? run `npm install`):", err); throw err; },
    );

    const ro = new ResizeObserver(() => this.resize());
    ro.observe(container);
    this.resize();
    canvas.addEventListener("pointerdown", (e) => (this.downAt = [e.clientX, e.clientY]));
    canvas.addEventListener("pointerup", (e) => {
      const [x, y] = this.downAt;
      if (Math.hypot(e.clientX - x, e.clientY - y) < 4) this.pick(e);
    });
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.tickFades();
      this.renderer.render(this.scene, this.camera3);
    });
  }

  private downAt: [number, number] = [0, 0];

  private resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera3.aspect = w / h;
    this.camera3.updateProjectionMatrix();
  }

  /** Replace the whole model. `onProgress` is called once at the end (web-ifc has no incremental progress). */
  async loadIfc(data: Uint8Array, _name?: string, onProgress?: (p: number) => void, keepCamera = false): Promise<void> {
    await this.ready;
    const animate = keepCamera && this.byGuid.size > 0;
    const previous = this.byGuid;
    const old = this.live();
    if (this.modelID !== null) this.ifc.CloseModel(this.modelID);
    const modelID = this.ifc.OpenModel(data, { COORDINATE_TO_ORIGIN: false });
    this.modelID = modelID;
    this.byGuid = new Map();
    let products = 0, geometries = 0;
    this.ifc.StreamAllMeshes(modelID, (mesh: WebIFC.FlatMesh) => {
      products++;
      const line = this.ifc.GetLine(modelID, mesh.expressID) as Record<string, { value?: string } | undefined>;
      const guid = line.GlobalId?.value ?? String(mesh.expressID);
      const typeCode = this.ifc.GetLineType(modelID, mesh.expressID);
      const fresh = animate && !previous.has(guid);
      const placed = mesh.geometries;
      for (let i = 0; i < placed.size(); i++) {
        const pg = placed.get(i);
        const geom = this.ifc.GetGeometry(modelID, pg.geometryExpressID);
        const verts = this.ifc.GetVertexArray(geom.GetVertexData(), geom.GetVertexDataSize());
        const index = this.ifc.GetIndexArray(geom.GetIndexData(), geom.GetIndexDataSize());
        const positions = new Float32Array(verts.length / 2);
        const normals = new Float32Array(verts.length / 2);
        for (let v = 0, o = 0; v < verts.length; v += 6, o += 3) {
          positions[o] = verts[v]; positions[o + 1] = verts[v + 1]; positions[o + 2] = verts[v + 2];
          normals[o] = verts[v + 3]; normals[o + 1] = verts[v + 4]; normals[o + 2] = verts[v + 5];
        }
        const bg = new THREE.BufferGeometry();
        bg.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        bg.setAttribute("normal", new THREE.BufferAttribute(normals, 3));
        bg.setIndex(new THREE.BufferAttribute(new Uint32Array(index), 1));
        const { x, y, z, w } = pg.color;
        const mat = new THREE.MeshLambertMaterial({
          color: new THREE.Color(x, y, z), transparent: w < 1, opacity: w, side: THREE.DoubleSide,
          clippingPlanes: [this.clipPlane],
        });
        const m = new THREE.Mesh(bg, mat);
        m.matrix.fromArray(pg.flatTransformation);
        m.matrixAutoUpdate = false;
        m.userData.expressID = mesh.expressID;
        m.userData.typeCode = typeCode;
        m.userData.guid = guid;
        m.userData.tag = tagOf(line);
        m.userData.opacity = w;
        m.visible = typeCode !== WebIFC.IFCSPACE || this.roomsVisible;
        if (this.highlighted && m.userData.tag === this.highlighted) this.applyHighlight(m, true);
        this.root.add(m);
        const list = this.byGuid.get(guid);
        if (list) list.push(m); else this.byGuid.set(guid, [m]);
        if (fresh) this.fade(m, 0, w, FADE_IN_MS, false);
        geom.delete();
        geometries++;
      }
    });
    for (const m of old) {
      if (animate && !this.byGuid.has(m.userData.guid as string)) {
        m.userData.dying = true;
        this.fade(m, (m.material as THREE.Material).opacity, 0, FADE_OUT_MS, true);
      } else {
        this.drop(m);
      }
    }
    console.log(`[nocoast:viewer] model ${modelID}: ${products} products, ${geometries} meshes`);
    this.root.updateMatrixWorld(true);
    this.measure();
    this.storeyList = this.readStoreys(modelID);
    onProgress?.(1);
    if (!keepCamera) this.frame();
  }

  private fade(mesh: THREE.Mesh, from: number, to: number, ms: number, drop: boolean) {
    const mat = mesh.material as THREE.MeshLambertMaterial;
    mat.transparent = true;
    mat.opacity = from;
    mat.needsUpdate = true;
    this.fades = this.fades.filter((f) => f.mesh !== mesh);
    this.fades.push({ mesh, from, to, start: performance.now(), ms, drop });
  }

  private tickFades() {
    if (!this.fades.length) return;
    const now = performance.now();
    this.fades = this.fades.filter((f) => {
      const k = Math.min(1, (now - f.start) / f.ms);
      const mat = f.mesh.material as THREE.MeshLambertMaterial;
      mat.opacity = f.from + (f.to - f.from) * k;
      if (k < 1) return true;
      if (f.drop) {
        this.drop(f.mesh);
      } else {
        mat.transparent = f.to < 1;
        mat.needsUpdate = true;
      }
      return false;
    });
  }

  private drop(m: THREE.Mesh) {
    this.root.remove(m);
    m.geometry.dispose();
    (m.material as THREE.Material).dispose();
  }

  private live(): THREE.Mesh[] {
    return this.root.children.filter((c) => !c.userData.dying) as THREE.Mesh[];
  }

  private measure() {
    this.box.makeEmpty();
    const bb = new THREE.Box3();
    for (const m of this.live()) if (m.userData.typeCode !== WebIFC.IFCSPACE) this.box.union(bb.setFromObject(m));
  }

  private highlighted: string | null = null;

  highlight(tag: string | null) {
    if (this.highlighted) for (const m of this.live()) if (m.userData.tag === this.highlighted) this.applyHighlight(m, false);
    this.highlighted = tag;
    if (tag) for (const m of this.live()) if (m.userData.tag === tag) this.applyHighlight(m, true);
  }

  private applyHighlight(m: THREE.Mesh, on: boolean) {
    const mat = m.material as THREE.MeshLambertMaterial;
    const base = m.userData.opacity as number;
    if (on) {
      mat.emissive.copy(HIGHLIGHT);
      mat.emissiveIntensity = base < 0.5 ? 0.9 : 0.45;
      if (base < 0.5) { mat.opacity = 0.45; mat.transparent = true; }
    } else {
      mat.emissive.setHex(0);
      mat.emissiveIntensity = 1;
      if (base < 0.5) mat.opacity = base;
    }
    mat.needsUpdate = true;
  }

  /** Drop the selection: its highlight goes and onSelect hears null. */
  clearSelection() {
    this.highlight(null);
    this.onSelect(null);
  }

  hasModel() {
    return this.modelID !== null;
  }

  /** Show or hide IfcSpace room volumes. */
  setRoomsVisible(visible: boolean) {
    this.roomsVisible = visible;
    for (const m of this.live()) if (m.userData.typeCode === WebIFC.IFCSPACE) m.visible = visible;
  }

  areRoomsVisible() {
    return this.roomsVisible;
  }

  /** Property sets of an element (IfcPropertySet → [name, value] pairs), plus its direct attributes as a first set. */
  async properties(expressID: number): Promise<PropertySet[]> {
    if (this.modelID === null) return [];
    const val = (v: unknown): string => {
      if (v === null || v === undefined) return "";
      if (typeof v === "object" && v !== null && "value" in (v as Record<string, unknown>)) return val((v as { value: unknown }).value);
      if (Array.isArray(v)) return v.map(val).join(", ");
      return String(v);
    };
    const out: PropertySet[] = [];
    const line = this.ifc.GetLine(this.modelID, expressID) as Record<string, unknown>;
    const attrs: [string, string][] = [];
    for (const k of ["GlobalId", "Name", "Tag", "ObjectType", "PredefinedType", "Description", "LongName"]) {
      const v = val(line[k]);
      if (v) attrs.push([k, v]);
    }
    out.push({ name: this.ifc.GetNameFromTypeCode(this.ifc.GetLineType(this.modelID, expressID)), props: attrs });
    try {
      const sets = (await this.ifc.properties.getPropertySets(this.modelID, expressID, true)) as Record<string, unknown>[];
      for (const ps of sets) {
        const props: [string, string][] = [];
        for (const p of (ps.HasProperties as Record<string, unknown>[] | undefined) ?? []) {
          const name = val(p.Name);
          if (name) props.push([name, val(p.NominalValue ?? p.Value ?? p.EnumerationValues)]);
        }
        if (props.length) out.push({ name: val(ps.Name) || "properties", props });
      }
    } catch (err) {
      console.warn("[nocoast:viewer] property sets unavailable:", err);
    }
    return out;
  }

  bounds(): { min: number; max: number } | null {
    return this.box.isEmpty() ? null : { min: this.box.min.y, max: this.box.max.y };
  }

  extent(): number {
    if (this.box.isEmpty()) return 0;
    const s = this.box.getSize(new THREE.Vector3());
    return Math.hypot(s.x, s.z);
  }

  storeys(): Storey[] {
    return this.storeyList;
  }

  private readStoreys(modelID: number): Storey[] {
    const ids = this.ifc.GetLineIDsWithType(modelID, WebIFC.IFCBUILDINGSTOREY);
    const storeys: Storey[] = [];
    for (let i = 0; i < ids.size(); i++) {
      const line = this.ifc.GetLine(modelID, ids.get(i)) as Record<string, { value?: string | number } | undefined>;
      const elevation = Number(line.Elevation?.value ?? 0);
      storeys.push({ id: String(line.Description?.value ?? ""), name: String(line.Name?.value ?? `storey ${i + 1}`), elevation, top: elevation });
    }
    storeys.sort((a, b) => a.elevation - b.elevation);
    const bb = new THREE.Box3();
    for (const child of this.live()) {
      const t = child.userData.typeCode as number;
      if (t !== WebIFC.IFCWALL && t !== WebIFC.IFCWALLSTANDARDCASE) continue;
      bb.setFromObject(child);
      let s: Storey | undefined;
      for (const c of storeys) if (c.elevation <= bb.min.y + 0.1) s = c;
      if (s) s.top = Math.max(s.top, bb.max.y);
    }
    for (const s of storeys) if (s.top <= s.elevation) s.top = s.elevation + 3;
    return storeys;
  }

  setLayerCutoff(z: number) {
    this.clipPlane.constant = z;
  }

  clear() {
    this.clipPlane.constant = 1e6;
    this.box.makeEmpty();
    this.storeyList = [];
    this.byGuid = new Map();
    this.fades = [];
    for (const child of [...this.root.children]) this.drop(child as THREE.Mesh);
    if (this.modelID !== null) {
      this.ifc.CloseModel(this.modelID);
      this.modelID = null;
    }
    this.onSelect(null);
  }

  // --- camera ---------------------------------------------------------------

  get camera(): THREE.Camera {
    return this.camera3;
  }

  private frame() {
    const box = this.box;
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length();
    this.controls.target.copy(center);
    this.camera3.position.copy(center).add(new THREE.Vector3(size * 0.7, size * 0.55, size * 0.7));
    this.camera3.near = Math.max(size / 1000, 0.01);
    this.camera3.far = size * 20;
    this.camera3.updateProjectionMatrix();
  }

  /** Re-fit the camera to the whole model. */
  fit() {
    this.frame();
  }

  /** Standard views, in IFC terms (Z up). Three.js is Y-up: IFC (x, y, z) → three (x, z, -y). */
  async view(name: ViewName) {
    const box = this.box.isEmpty() ? new THREE.Box3(new THREE.Vector3(-10, 0, -10), new THREE.Vector3(10, 10, 10)) : this.box;
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1);
    const dirs: Record<ViewName, [number, number, number]> = {
      top: [0, 1, 0.0001], bottom: [0, -1, 0.0001],
      front: [0, 0, 1], back: [0, 0, -1],
      left: [-1, 0, 0], right: [1, 0, 0],
      isometric: [1, 0.8, 1],
    };
    const d = new THREE.Vector3(...dirs[name]).normalize().multiplyScalar(radius * 2.2);
    this.controls.target.copy(center);
    this.camera3.position.copy(center).add(d);
    this.camera3.updateProjectionMatrix();
  }

  reset() {
    this.frame();
  }

  /** Select the first element whose IFC class matches, e.g. "IFCWALL". Used by the smoke test. */
  selectFirstOf(category: string) {
    const target = category.toUpperCase();
    for (const m of this.live()) {
      const type = this.ifc.GetNameFromTypeCode(m.userData.typeCode as number).toUpperCase();
      if (type === target) {
        const id = m.userData.expressID as number;
        const line = this.ifc.GetLine(this.modelID!, id) as Record<string, { value?: string } | undefined>;
        this.onSelect({
          expressID: id, type, name: line.Name?.value ?? line.LongName?.value ?? "",
          tag: tagOf(line), globalId: line.GlobalId?.value ?? "", point: { x: 0, y: 0, z: 0 },
        });
        return;
      }
    }
  }

  private pick(e: PointerEvent) {
    if (this.modelID === null) return;
    const rect = this.container.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera3);
    const hits = this.raycaster.intersectObjects(this.live())
      .filter((h) => h.object.visible && (h.object.userData.opacity as number) > 0.5 && h.point.y <= this.clipPlane.constant);
    const hit = hits[0];
    if (!hit) return this.onSelect(null);
    const id = hit.object.userData.expressID as number;
    const line = this.ifc.GetLine(this.modelID, id) as Record<string, { value?: string } | undefined>;
    const p = hit.point;
    this.onSelect({
      expressID: id,
      type: this.ifc.GetNameFromTypeCode(this.ifc.GetLineType(this.modelID, id)),
      name: line.Name?.value ?? line.LongName?.value ?? "",
      tag: tagOf(line),
      globalId: line.GlobalId?.value ?? "",
      point: { x: p.x, y: -p.z, z: p.y },
    });
  }
}
