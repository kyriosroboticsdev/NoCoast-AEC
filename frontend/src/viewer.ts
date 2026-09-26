// IFC → meshes with web-ifc (thatopen/engine_web-ifc), drawn with three.js.
// web-ifc only parses and tessellates; it does not render, hence three.js.

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import * as WebIFC from "web-ifc";

export interface Picked {
  expressID: number;
  type: string;
  name: string;
  tag: string;
  globalId: string;
}

export class Viewer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private root = new THREE.Group(); // web-ifc already converts IFC's Z-up placements to Y-up, so no rotation here
  private ifc = new WebIFC.IfcAPI();
  private modelID: number | null = null;
  private raycaster = new THREE.Raycaster();
  private ready: Promise<void>;
  // Slicer-preview walkthrough: one shared plane clips every material at once, so revealing another
  // layer is just moving `clipPlane.constant` — no per-mesh bookkeeping. web-ifc converts IFC's Z-up
  // to three.js Y-up by relabeling the axis (no sign flip, no origin shift with COORDINATE_TO_ORIGIN
  // false), so a slice height from the backend (`slicer/slice.py`, IFC Z) is used unchanged as a Y cutoff.
  private clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);

  constructor(canvas: HTMLCanvasElement, private onPick: (p: Picked | null) => void) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.localClippingEnabled = true;
    this.scene.background = new THREE.Color(0x0f1115);
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 2000);
    this.camera.position.set(25, 20, 25);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x444466, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(30, 50, 20);
    this.scene.add(sun);
    this.scene.add(new THREE.GridHelper(60, 60, 0x333844, 0x22252d));
    this.scene.add(this.root);

    // The wasm lives in public/wasm (copied by scripts/copy-wasm.mjs); resolve it against the page,
    // which works in `vite dev`, a static build and inside Tauri.
    const wasmPath = new URL("wasm/", document.baseURI).href;
    this.ifc.SetWasmPath(wasmPath, true);
    console.log("[nocoast:viewer] init web-ifc, wasm path", wasmPath, "| webgl:", this.renderer.capabilities.isWebGL2 ? "2" : "1");
    this.ready = this.ifc.Init().then(
      () => console.log("[nocoast:viewer] web-ifc ready", this.ifc.GetVersion?.() ?? ""),
      (err) => { console.error("[nocoast:viewer] web-ifc init FAILED (is public/wasm populated? run `npm install`):", err); throw err; },
    );

    window.addEventListener("resize", () => this.resize());
    this.resize();
    canvas.addEventListener("pointerdown", (e) => (this.downAt = [e.clientX, e.clientY]));
    canvas.addEventListener("pointerup", (e) => {
      const [x, y] = this.downAt;
      if (Math.hypot(e.clientX - x, e.clientY - y) < 4) this.pick(e);
    });
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    });
  }

  private downAt: [number, number] = [0, 0];

  private resize() {
    const { innerWidth: w, innerHeight: h } = window;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  /** Replace the whole model. Small models parse in milliseconds, so incremental mesh patching is deferred (see README).
   *  With `keepCamera` the current view is left alone, so previews and new versions grow in place. */
  async load(data: Uint8Array, keepCamera = false): Promise<void> {
    await this.ready;
    this.clear();
    const modelID = this.ifc.OpenModel(data, { COORDINATE_TO_ORIGIN: false });
    this.modelID = modelID;
    let products = 0, geometries = 0;
    this.ifc.StreamAllMeshes(modelID, (mesh: WebIFC.FlatMesh) => {
      products++;
      const placed = mesh.geometries;
      for (let i = 0; i < placed.size(); i++) {
        const pg = placed.get(i);
        const geom = this.ifc.GetGeometry(modelID, pg.geometryExpressID);
        const verts = this.ifc.GetVertexArray(geom.GetVertexData(), geom.GetVertexDataSize()); // xyz + normal, interleaved
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
        this.root.add(m);
        geom.delete();
        geometries++;
      }
    });
    console.log(`[nocoast:viewer] model ${modelID}: ${products} products, ${geometries} meshes`);
    if (!geometries) console.warn("[nocoast:viewer] no geometry produced — is the IFC empty or unsupported?");
    if (keepCamera) this.root.updateMatrixWorld(true);
    else this.frame();
  }

  /** Reveal the model built up to (and including) `z` — the layer-by-layer construction walkthrough. Pass `Infinity` for everything. */
  setLayerCutoff(z: number) {
    this.clipPlane.constant = z;
  }

  clear() {
    this.clipPlane.constant = 1e6; // previews and fresh loads start fully visible; showVersion() re-applies the slider position
    for (const child of [...this.root.children]) {
      this.root.remove(child);
      const m = child as THREE.Mesh;
      m.geometry.dispose();
      (m.material as THREE.Material).dispose();
    }
    if (this.modelID !== null) {
      this.ifc.CloseModel(this.modelID);
      this.modelID = null;
    }
    this.onPick(null);
  }

  private frame() {
    this.root.updateMatrixWorld(true); // meshes use manual matrices; make sure world matrices exist before measuring
    const box = new THREE.Box3().setFromObject(this.root);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length();
    this.controls.target.copy(center);
    this.camera.position.copy(center).add(new THREE.Vector3(size * 0.7, size * 0.55, size * 0.7));
    this.camera.near = size / 200;
    this.camera.far = size * 20;
    this.camera.updateProjectionMatrix();
  }

  private pick(e: PointerEvent) {
    if (this.modelID === null) return;
    const ndc = new THREE.Vector2((e.clientX / window.innerWidth) * 2 - 1, -(e.clientY / window.innerHeight) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    // Spaces are translucent volumes that would otherwise swallow every click.
    const hits = this.raycaster.intersectObjects(this.root.children).filter((h) => ((h.object as THREE.Mesh).material as THREE.Material).opacity > 0.5);
    const hit = hits[0];
    if (!hit) return this.onPick(null);
    const id = hit.object.userData.expressID as number;
    const line = this.ifc.GetLine(this.modelID, id) as Record<string, { value?: string } | undefined>;
    this.onPick({
      expressID: id,
      type: this.ifc.GetNameFromTypeCode(this.ifc.GetLineType(this.modelID, id)),
      name: line.Name?.value ?? line.LongName?.value ?? "",
      tag: line.Tag?.value ?? (line.LongName ? line.Name?.value ?? "" : ""),
      globalId: line.GlobalId?.value ?? "",
    });
  }
}
