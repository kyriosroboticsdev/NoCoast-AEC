import * as THREE from "three";
import * as OBC from "@thatopen/components";
import type { FragmentsModel } from "@thatopen/fragments";
import { preferGridOverFloor } from "./coplanar";
import { requireWorkerUrl } from "./config";
import type { SnapshotView } from "./types";

/**
 * Resolve on the next animation frame, or after a short timeout if frames
 * are paused (minimised or hidden window). Without the fallback a snapshot
 * would hang, and with it every later turn in the serial queue.
 */
function nextFrame(fallbackMs = 50): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, fallbackMs);
    requestAnimationFrame(() => {
      clearTimeout(t);
      resolve();
    });
  });
}

export type World =OBC.SimpleWorld<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>;

// three.js is Y-up; the fragments importer maps IFC +Z to +Y and IFC +Y to -Z.
// So IFC "south" (low Y) faces +Z here.
const VIEW_DIRS: Record<SnapshotView, THREE.Vector3> = {
  iso: new THREE.Vector3(1, 0.85, 1.25),
  top: new THREE.Vector3(0, 1, 0.0001),
  front: new THREE.Vector3(0, 0.2, 1),
  side: new THREE.Vector3(1, 0.2, 0),
};

export interface ViewportOptions {
  /** Allow orbit/pan/zoom with the pointer. */
  interactive?: boolean;
  /** CSS background colour; null for transparent. */
  background?: string | null;
  /** Show the ground grid. */
  grid?: boolean;
}

/**
 * One That Open world (scene + camera + renderer + fragments manager) bound
 * to a persistent host <div>. The host is moved between DOM parents when a
 * pooled viewport is lent to a different turn card, so the WebGL context
 * survives the move.
 *
 * Renders on demand only: camera movement and fragment tile streaming mark
 * the renderer dirty, so idle viewports cost no GPU time.
 */
export class IfcViewport {
  readonly host: HTMLDivElement;
  readonly components: OBC.Components;
  readonly world: World;
  readonly fragments: OBC.FragmentsManager;

  private model: FragmentsModel | null = null;
  private shownKey: string | null = null;
  /** The exact bytes currently shown; a new version of a turn means new bytes. */
  private shownFrag: Uint8Array | null = null;
  private loadSeq = 0;
  private disposed = false;
  private background: THREE.Color | null;
  private grid: OBC.SimpleGrid | null = null;

  constructor(opts: ViewportOptions = {}) {
    this.host = document.createElement("div");
    this.host.className = "ncv-viewport";

    this.components = new OBC.Components();
    const worlds = this.components.get(OBC.Worlds);
    this.world = worlds.create<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>();

    this.world.scene = new OBC.SimpleScene(this.components);
    this.world.scene.setup();
    this.background = opts.background === null ? null : new THREE.Color(opts.background ?? "#f6f7f9");
    this.world.scene.three.background = this.background;

    this.world.renderer = new OBC.SimpleRenderer(this.components, this.host, {
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true,
    });
    this.world.renderer.showLogo = false;
    this.world.renderer.mode = OBC.RendererMode.MANUAL;

    this.world.camera = new OBC.OrthoPerspectiveCamera(this.components);
    this.components.init();

    if (opts.grid !== false) {
      this.grid = this.components.get(OBC.Grids).create(this.world);
      // Infinite shader plane. Lines win against a coplanar floor; discarded gaps show it.
      this.grid.three.renderOrder = 1;
      preferGridOverFloor(this.grid.material);
    }

    this.fragments = this.components.get(OBC.FragmentsManager);
    this.fragments.init(requireWorkerUrl());

    const controls = this.world.camera.controls;
    controls.addEventListener("update", () => {
      void this.fragments.core.update();
      this.invalidate();
    });
    this.setInteractive(opts.interactive ?? true);

    // Follow the host's size as it moves between cards or gains layout.
    // Renders are on demand, so a resize must also request a redraw.
    this.resizeObserver = new ResizeObserver(() => {
      const hadNoSize = !this.sized;
      this.sized = this.resize();
      // First real size: the camera was framed against a bogus aspect.
      if (this.sized && hadNoSize && this.model) void this.frame(this.lastView, false);
    });
    this.resizeObserver.observe(this.host);
  }

  private resizeObserver: ResizeObserver;
  private sized = false;
  private lastView: SnapshotView = "iso";

  get key(): string | null {
    return this.shownKey;
  }

  get currentModel(): FragmentsModel | null {
    return this.model;
  }

  get canvas(): HTMLCanvasElement {
    return this.world.renderer!.three.domElement;
  }

  /**
   * Toggle pointer orbit/pan/zoom. Only user input is switched off: disabling
   * the controls themselves would also stop programmatic camera moves, which
   * left the snapshot camera stuck at its default far-away position.
   */
  setInteractive(on: boolean): void {
    this.world.camera.setUserInput(on);
  }

  /** Request a redraw on the next animation frame. */
  invalidate(): void {
    if (!this.disposed && this.world.renderer) this.world.renderer.needsUpdate = true;
  }

  /**
   * Match the canvas and camera to the host's current size. Returns false
   * while the host has no layout size (detached or inside a hidden parent).
   * A zero size would give the camera a NaN aspect ratio and wreck framing.
   */
  resize(): boolean {
    const w = this.host.clientWidth;
    const h = this.host.clientHeight;
    if (!w || !h || this.disposed) return false;
    this.world.renderer?.resize(new THREE.Vector2(w, h));
    const cam = this.world.camera.three;
    if (cam instanceof THREE.PerspectiveCamera) {
      cam.aspect = w / h;
      cam.updateProjectionMatrix();
    } else {
      this.world.camera.updateAspect();
    }
    this.invalidate();
    return true;
  }

  /**
   * Display fragments for `key`. A no-op only if the same key AND the same
   * bytes are already shown, so an overwritten turn always reloads. If a
   * newer show() call starts before this one finishes, this one is dropped.
   */
  async show(key: string, frag: Uint8Array, view: SnapshotView = "iso"): Promise<void> {
    if (this.disposed) return;
    if (this.shownKey === key && this.shownFrag === frag && this.model) return;
    const seq = ++this.loadSeq;
    await this.clear();
    // FragmentsModels transfers the buffer to its worker, detaching it. Pass
    // a copy so the caller's cached bytes stay usable for other viewports.
    const model = await this.fragments.core.load(frag.slice(), {
      modelId: `${key}::${seq}`,
      camera: this.world.camera.three,
    });
    if (seq !== this.loadSeq || this.disposed) {
      await this.fragments.core.disposeModel(model.modelId);
      return;
    }
    this.model = model;
    this.shownKey = key;
    this.shownFrag = frag;
    model.onViewUpdated.add(() => this.invalidate());
    this.world.scene.three.add(model.object);
    await this.fragments.core.update(true);
    await this.frame(view, false);
  }

  async clear(): Promise<void> {
    const m = this.model;
    this.model = null;
    this.shownKey = null;
    this.shownFrag = null;
    if (m) {
      m.object.removeFromParent();
      await this.fragments.core.disposeModel(m.modelId);
    }
    this.invalidate();
  }

  /** World-space bounding box of the shown model, or null if empty. */
  modelBox(): THREE.Box3 | null {
    const box = this.model?.box;
    if (!box || box.isEmpty()) return null;
    return box.clone();
  }

  /** Point the camera at the model from a canonical direction. */
  async frame(view: SnapshotView = "iso", animate = true): Promise<void> {
    this.lastView = view;
    // Measure synchronously: the ResizeObserver may not have fired yet.
    this.sized = this.resize();
    const box = this.modelBox();
    if (!box) return;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const cam = this.world.camera.three;
    let dist = sphere.radius * 2.5;
    if (cam instanceof THREE.PerspectiveCamera) {
      const vFov = THREE.MathUtils.degToRad(cam.fov);
      const hFov = 2 * Math.atan(Math.tan(vFov / 2) * cam.aspect);
      dist = sphere.radius / Math.sin(Math.min(vFov, hFov) / 2);
    }
    if (!Number.isFinite(dist) || dist <= 0) dist = sphere.radius * 2.5;
    dist *= 1.08;
    const pos = VIEW_DIRS[view].clone().normalize().multiplyScalar(dist).add(sphere.center);
    const c = sphere.center;
    await this.world.camera.controls.setLookAt(pos.x, pos.y, pos.z, c.x, c.y, c.z, animate);
    if (this.grid) {
      // On the model's base, not the world origin. Depth bias keeps the lines in front;
      // a Y drop flickers as the camera moves and reads as a gap under the floor.
      this.grid.three.position.set(c.x, box.min.y, c.z);
    }
    await this.fragments.core.update(true);
    this.invalidate();
  }

  /**
   * Wait until fragment tiles for the current camera are resident, then
   * render once and encode the canvas as PNG.
   */
  async capturePng(background?: string): Promise<Uint8Array> {
    const renderer = this.world.renderer!;
    await this.settle();
    const prevBg = this.world.scene.three.background;
    if (background) this.world.scene.three.background = new THREE.Color(background);
    renderer.three.render(this.world.scene.three, this.world.camera.three);
    // toBlob copies the bitmap synchronously at call time, so restoring the
    // background right after is safe.
    const blobPromise = new Promise<Blob | null>((res) => this.canvas.toBlob(res, "image/png"));
    this.world.scene.three.background = prevBg;
    this.invalidate();
    const blob = await blobPromise;
    if (!blob) throw new Error("Canvas could not be encoded as PNG");
    return new Uint8Array(await blob.arrayBuffer());
  }

  /**
   * Resolve once the fragments worker has finished streaming geometry for
   * the current camera. `isBusy` alone is not enough: tiles keep arriving
   * after it clears, which produced snapshots missing most elements. So wait
   * until the scene's total vertex count is unchanged for several
   * consecutive checks.
   */
  async settle(timeoutMs = 6000): Promise<void> {
    const start = performance.now();
    let last = -1;
    let stable = 0;
    while (performance.now() - start < timeoutMs) {
      await this.fragments.core.update(true);
      await nextFrame();
      const vertices = this.vertexCount();
      const busy = this.model?.isBusy ?? false;
      if (!busy && vertices > 0 && vertices === last) {
        if (++stable >= 6) break;
      } else {
        stable = 0;
      }
      last = vertices;
    }
    await nextFrame();
  }

  /** Total vertices currently attached under the model's scene object. */
  private vertexCount(): number {
    let n = 0;
    this.model?.object.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh && mesh.visible) n += mesh.geometry?.attributes?.position?.count ?? 0;
    });
    return n;
  }

  /** Attach the persistent host into `parent`, filling it. */
  mount(parent: HTMLElement): void {
    if (this.host.parentElement !== parent) parent.appendChild(this.host);
    this.resize();
  }

  unmount(): void {
    this.host.remove();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.resizeObserver.disconnect();
    this.host.remove();
    this.components.dispose();
  }
}
