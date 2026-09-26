// Thin wrapper around That Open Engine. The rest of the app only talks to this class,
// so the viewer library can be swapped without touching the UI or the backend.
import * as OBC from "@thatopen/components";
import * as OBF from "@thatopen/components-front";
import * as FRAGS from "@thatopen/fragments";
import * as THREE from "three";
const workerUrl = new URL("fragments-worker.mjs", window.location.href).href;

export interface TreeNode {
  key: string;
  label: string;
  category: string;
  localId: number | null;
  children: TreeNode[];
  /** every element id at or below this node — used for hide/show */
  ids: number[];
}

export interface PropertyGroup {
  title: string;
  rows: [string, string][];
}

export type ViewName = "top" | "bottom" | "front" | "back" | "left" | "right" | "isometric";

export interface ModelStats {
  elements: number;
  levels: number;
  extent: [number, number, number];
  triangles: number;
}

export interface LevelItem {
  localId: number;
  name: string;
}

export interface LevelNode {
  localId: number;
  name: string;
  elevation: number;
  groups: { category: string; label: string; items: LevelItem[] }[];
}

export interface ElementRow {
  localId: number;
  ifcClass: string;
  name: string;
  tag: string;
  level: string;
  guid: string;
}

export interface ElementSummary {
  name: string;
  category: string;
  ifcClass: string;
  level: string;
  guid: string;
}

type World = OBC.SimpleWorld<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>;

const SELECT = "select";
const SPATIAL = /^IFC(PROJECT|SITE|BUILDING|BUILDINGSTOREY|SPACE|FACILITY|FACILITYPART)$/i;

export class BimViewer {
  private components = new OBC.Components();
  private world!: World;
  private fragments!: OBC.FragmentsManager;
  private loader!: OBC.IfcLoader;
  private highlighter!: OBF.Highlighter;
  private hider!: OBC.Hider;
  private selection: OBC.ModelIdMap = {};
  private hiddenCategories = new Set<string>();

  onSelect: (sel: { modelId: string; localId: number } | null) => void = () => {};
  /** Fires on every camera move — drives the axis gizmo. */
  onCamera: (camera: THREE.Camera) => void = () => {};

  async init(container: HTMLElement) {
    const worlds = this.components.get(OBC.Worlds);
    const world = worlds.create<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>();
    world.scene = new OBC.SimpleScene(this.components);
    world.scene.setup();
    // kyriolexy's lighting rig from the old viewer (frontend/src/viewer.ts, pre-redesign): a dark
    // background and hemisphere + directional lights read the IFC's own per-element surface colours much
    // better than That Open's default single ambient + directional pair on a light background.
    world.scene.three.background = new THREE.Color("#0f1115");
    world.scene.deleteAllLights();
    world.scene.three.add(new THREE.HemisphereLight(0xffffff, 0x444466, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(30, 50, 20);
    world.scene.three.add(sun);
    world.renderer = new OBC.SimpleRenderer(this.components, container);
    world.camera = new OBC.OrthoPerspectiveCamera(this.components);
    await world.camera.controls.setLookAt(25, 18, 25, 0, 2, 0);
    this.components.init();
    this.world = world;
    // That Open defaults to infinityDolly, which pushes the orbit target forward instead of
    // stopping at minDistance, so the wheel flies through walls forever.
    world.camera.controls.infinityDolly = false;
    this.applyZoomLimits();

    const grid = this.components.get(OBC.Grids).create(world);
    grid.material.uniforms.uColor.value = new THREE.Color("#333844");
    // A faint ground plane so basements read as below grade, matching the old viewer.
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.MeshBasicMaterial({ color: "#0b0d12", transparent: true, opacity: 0.75, depthWrite: false }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    world.scene.three.add(ground);

    this.fragments = this.components.get(OBC.FragmentsManager);
    this.fragments.init(workerUrl);
    world.camera.controls.addEventListener("update", () => {
      this.fragments.core.update();
      this.onCamera(world.camera.three);
    });
    this.fragments.list.onItemSet.add(({ value: model }) => {
      model.useCamera(world.camera.three);
      world.scene.three.add(model.object);
      this.fragments.core.update(true);
    });
    // Avoid z-fighting between coplanar faces (e.g. door linings flush with walls).
    this.fragments.core.models.materials.list.onItemSet.add(({ value: material }) => {
      if (!("isLodMaterial" in material && material.isLodMaterial)) {
        material.polygonOffset = true;
        material.polygonOffsetUnits = 1;
        material.polygonOffsetFactor = Math.random();
      }
    });

    this.loader = this.components.get(OBC.IfcLoader);
    await this.loader.setup({
      autoSetWasm: false,
      wasm: { path: new URL("wasm/", window.location.href).href, absolute: true },
    });

    this.components.get(OBC.Raycasters).get(world);
    this.hider = this.components.get(OBC.Hider);
    this.highlighter = this.components.get(OBF.Highlighter);
    this.highlighter.setup({
      world,
      selectName: SELECT,
      selectMaterialDefinition: {
        color: new THREE.Color("#ffb020"),
        opacity: 1,
        transparent: false,
        renderedFaces: FRAGS.RenderedFaces.TWO,
      },
    });
    this.highlighter.events[SELECT].onHighlight.add((map) => {
      this.selection = map;
      const [modelId, ids] = Object.entries(map)[0] ?? [];
      const localId = ids ? [...ids][0] : undefined;
      this.onSelect(modelId && localId !== undefined ? { modelId, localId } : null);
    });
    this.highlighter.events[SELECT].onClear.add(() => {
      this.selection = {};
      this.onSelect(null);
    });
  }

  /** Replace whatever is loaded with this IFC. */
  async loadIfc(data: Uint8Array, name: string, onProgress?: (p: number) => void) {
    await this.clear();
    const model = await this.loader.load(data, true, name, {
      processData: { progressCallback: (p: number) => onProgress?.(p) },
    });
    await this.fragments.core.update(true);
    for (const cat of this.hiddenCategories) await this.setCategoryVisible(cat, false);
    this.applyZoomLimits();
    await this.fit();
    return model.modelId;
  }

  async clear() {
    await this.highlighter.clear(SELECT);
    for (const id of [...this.fragments.list.keys()]) await this.fragments.core.disposeModel(id);
  }

  get modelId(): string | null {
    if (!this.fragments) return null; // called before init() (e.g. default hidden categories)
    return [...this.fragments.list.keys()][0] ?? null;
  }

  private get model() {
    const id = this.modelId;
    return id ? this.fragments.list.get(id)! : null;
  }

  async fit() {
    await this.world.camera.fitToItems();
  }

  // --- hierarchy & properties ---------------------------------------------

  async spatialTree(): Promise<TreeNode | null> {
    const model = this.model;
    if (!model) return null;
    const root = await model.getSpatialStructure();
    const ids: number[] = [];
    const walk = (n: FRAGS.SpatialTreeItem) => {
      if (n.localId !== null) ids.push(n.localId);
      n.children?.forEach(walk);
    };
    walk(root);
    const data = await model.getItemsData(ids, { attributesDefault: false, attributes: ["Name", "LongName"] });
    const names = new Map<number, string>();
    ids.forEach((id, i) => {
      const d = data[i] as Record<string, FRAGS.ItemAttribute>;
      const label = d?.LongName?.value || d?.Name?.value;
      if (label) names.set(id, String(label));
    });

    let k = 0;
    // Fragments inserts a class-grouping node (localId null) above each spatial element.
    // Hoist the children of groups directly under spatial elements; keep groups of
    // building elements (e.g. "Wall 14") under a storey, since those are useful.
    const build = (n: FRAGS.SpatialTreeItem, parentIsSpatial: boolean): TreeNode[] => {
      const spatial = SPATIAL.test(n.category ?? "");
      const children = (n.children ?? []).flatMap((c) => build(c, n.localId !== null && spatial));
      if (n.localId === null && (children.every((c) => SPATIAL.test(c.category)) || !parentIsSpatial) && n.children?.length) {
        return children;
      }
      const own = n.localId !== null ? [n.localId] : [];
      const cat = n.category ?? children[0]?.category ?? "";
      return [{
        key: `n${k++}`,
        category: cat,
        localId: n.localId,
        label: n.localId !== null ? names.get(n.localId) ?? `${pretty(cat)} #${n.localId}` : `${pretty(cat)}s`,
        children,
        ids: own.concat(...children.map((c) => c.ids)),
      }];
    };
    return build(root, false)[0] ?? null;
  }

  async properties(localId: number): Promise<PropertyGroup[]> {
    const model = this.model;
    if (!model) return [];
    const [item] = await model.getItemsData([localId], {
      attributesDefault: true,
      relations: {
        IsDefinedBy: { attributes: true, relations: true },
        HasAssociations: { attributes: true, relations: false },
        ContainedInStructure: { attributes: true, relations: false },
      },
    });
    if (!item) return [];
    const groups: PropertyGroup[] = [];
    const attrs: [string, string][] = [];
    for (const [key, val] of Object.entries(item)) {
      if (!Array.isArray(val) && val && "value" in val && val.value !== null && val.value !== undefined) {
        const label = { _category: "Class", _localId: "Local ID", _guid: "GlobalId" }[key] ?? key;
        attrs.push([label, fmt(val.value)]);
      }
    }
    groups.push({ title: "Attributes", rows: attrs });

    const rel = (name: string) => (Array.isArray(item[name]) ? (item[name] as FRAGS.ItemData[]) : []);
    const where = rel("ContainedInStructure").map((s) => attr(s, "Name")).filter(Boolean);
    const materials = rel("HasAssociations").map((m) => attr(m, "Name")).filter(Boolean);
    if (where.length || materials.length) {
      groups.push({
        title: "Relations",
        rows: [
          ...(where.length ? [["Storey", where.join(", ")] as [string, string]] : []),
          ...(materials.length ? [["Material", materials.join(", ")] as [string, string]] : []),
        ],
      });
    }
    for (const pset of rel("IsDefinedBy")) {
      const props = Array.isArray(pset.HasProperties) ? (pset.HasProperties as FRAGS.ItemData[]) : [];
      const rows = props.map((p) => [attr(p, "Name"), attr(p, "NominalValue")] as [string, string]);
      if (rows.length) groups.push({ title: attr(pset, "Name") || "Property Set", rows });
    }
    return groups;
  }

  // --- stats, levels & element table ---------------------------------------

  async stats(): Promise<ModelStats | null> {
    const model = this.model;
    if (!model) return null;
    const cats = await this.categories();
    const box = model.box;
    const size = box.getSize(new THREE.Vector3());
    let triangles = 0;
    const geo = await model.getItemsWithGeometry();
    const ids = (await Promise.all(geo.map((i) => i.getLocalId()))).filter((x): x is number => x !== null);
    for (const meshes of await model.getItemsGeometry(ids)) {
      for (const m of meshes) triangles += (m.indices?.length ?? 0) / 3;
    }
    return {
      elements: ids.length, // items with geometry (excludes property sets, materials, openings' voids…)
      levels: cats.find((c) => c.name === "IFCBUILDINGSTOREY")?.count ?? 0,
      // Three.js is Y-up; report IFC-style X × Y × Z (plan width × depth × height).
      extent: [size.x, size.z, size.y],
      triangles: Math.round(triangles),
    };
  }

  /** Storeys (highest first) → class groups → elements, like a level-by-level schedule. */
  async levels(): Promise<LevelNode[]> {
    const model = this.model;
    if (!model) return [];
    const root = await model.getSpatialStructure();
    const storeys: { id: number; members: { id: number; cat: string }[] }[] = [];
    // Fragments puts the class on a grouping node (localId null) above the items it holds.
    const walk = (n: FRAGS.SpatialTreeItem, current: (typeof storeys)[number] | null, inherited: string | null) => {
      const cat = (n.category ?? inherited ?? "ITEM").toUpperCase();
      let here = current;
      if (n.localId !== null && cat === "IFCBUILDINGSTOREY") {
        here = { id: n.localId, members: [] };
        storeys.push(here);
      } else if (n.localId !== null && here) {
        here.members.push({ id: n.localId, cat });
      }
      n.children?.forEach((c) => walk(c, here, n.localId === null ? cat : null));
    };
    walk(root, null, null);

    const all = storeys.flatMap((s) => [s.id, ...s.members.map((m) => m.id)]);
    const data = await model.getItemsData(all, { attributesDefault: false, attributes: ["Name", "LongName", "Elevation"] });
    const info = new Map<number, Record<string, FRAGS.ItemAttribute>>();
    all.forEach((id, i) => info.set(id, data[i] as Record<string, FRAGS.ItemAttribute>));
    const name = (id: number) => String(info.get(id)?.LongName?.value ?? info.get(id)?.Name?.value ?? `#${id}`);

    this.levelOf.clear();
    return storeys
      .map((s) => {
        const groups = new Map<string, LevelItem[]>();
        for (const m of s.members) {
          this.levelOf.set(m.id, name(s.id));
          if (!groups.has(m.cat)) groups.set(m.cat, []);
          groups.get(m.cat)!.push({ localId: m.id, name: name(m.id) });
        }
        return {
          localId: s.id,
          name: name(s.id),
          elevation: Number(info.get(s.id)?.Elevation?.value ?? 0),
          groups: [...groups.entries()]
            .map(([category, items]) => ({ category, label: pretty(category), items }))
            .sort((a, b) => a.label.localeCompare(b.label)),
        };
      })
      .sort((a, b) => b.elevation - a.elevation);
  }

  private levelOf = new Map<number, string>();

  levelName(localId: number) {
    return this.levelOf.get(localId) ?? "";
  }

  /** One row per element (spatial containers excluded) for the Data tab. */
  async elementRows(): Promise<ElementRow[]> {
    const model = this.model;
    if (!model) return [];
    const cats = (await this.categories()).filter((c) => !SPATIAL.test(c.name) || c.name === "IFCSPACE");
    const byCat = await model.getItemsOfCategories(cats.map((c) => new RegExp(`^${c.name}$`)));
    // Only physical things: skip property sets, materials, types and other non-geometric items.
    const geo = await model.getItemsWithGeometry();
    const physical = new Set((await Promise.all(geo.map((i) => i.getLocalId()))).filter((x): x is number => x !== null));
    const rows: ElementRow[] = [];
    for (const [cat, all] of Object.entries(byCat)) {
      const ids = all.filter((id) => physical.has(id));
      if (!ids.length) continue;
      const data = await model.getItemsData(ids, { attributesDefault: false, attributes: ["Name", "LongName", "Tag"] });
      ids.forEach((id, i) => {
        const d = data[i] as Record<string, FRAGS.ItemAttribute>;
        rows.push({
          localId: id,
          ifcClass: ifcClass(cat),
          name: String(d?.LongName?.value ?? d?.Name?.value ?? ""),
          tag: String(d?.Tag?.value ?? ""),
          level: this.levelName(id),
          guid: String(d?._guid?.value ?? ""),
        });
      });
    }
    return rows.sort((a, b) => a.level.localeCompare(b.level) || a.ifcClass.localeCompare(b.ifcClass) || a.name.localeCompare(b.name));
  }

  /** Short summary of one element for the info card. */
  async elementSummary(localId: number): Promise<ElementSummary | null> {
    const model = this.model;
    if (!model) return null;
    const [d] = (await model.getItemsData([localId], { attributesDefault: true })) as Record<string, FRAGS.ItemAttribute>[];
    if (!d) return null;
    const cat = String(d._category?.value ?? "");
    return {
      name: String(d.LongName?.value ?? d.Name?.value ?? `#${localId}`),
      category: pretty(cat),
      ifcClass: ifcClass(cat),
      level: this.levelName(localId),
      guid: String(d._guid?.value ?? ""),
    };
  }

  // --- camera --------------------------------------------------------------

  /** Standard views, in IFC terms (Z up). Three.js is Y-up: IFC (x, y, z) → three (x, z, -y). */
  async view(name: ViewName) {
    const model = this.model;
    const box = model ? model.box : new THREE.Box3(new THREE.Vector3(-10, 0, -10), new THREE.Vector3(10, 10, 10));
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1);
    const dirs: Record<ViewName, [number, number, number]> = {
      top: [0, 1, 0.0001], bottom: [0, -1, 0.0001],
      front: [0, 0, 1], back: [0, 0, -1],
      left: [-1, 0, 0], right: [1, 0, 0],
      isometric: [1, 0.8, 1],
    };
    const d = new THREE.Vector3(...dirs[name]).normalize().multiplyScalar(radius * 2.2);
    await this.world.camera.controls.setLookAt(center.x + d.x, center.y + d.y, center.z + d.z, center.x, center.y, center.z, true);
  }

  get projection(): "Perspective" | "Orthographic" {
    return this.world.camera.projection.current;
  }

  async toggleProjection() {
    await this.world.camera.projection.set(this.projection === "Perspective" ? "Orthographic" : "Perspective");
    this.applyZoomLimits();
    this.onCamera(this.world.camera.three);
    return this.projection;
  }

  /** Zoom to the selection, or the whole model when nothing is selected. */
  async focusSelection() {
    await this.world.camera.fitToItems(Object.keys(this.selection).length ? this.selection : undefined);
  }

  async reset() {
    await this.world.camera.projection.set("Perspective");
    this.applyZoomLimits();
    await this.view("isometric");
  }

  /**
   * Keep the camera between ~1 m from the target and a few model-sizes away, so you can't
   * dive through walls or lose the building as a dot. Orthographic zoom is relative to the
   * frustum That Open sets up when switching (zoom 1 = the view at that moment), so it is
   * recomputed after every projection change and always allows zoom 1.
   */
  private applyZoomLimits() {
    const { controls, threeOrtho } = this.world.camera;
    const box = this.model?.box;
    const radius = box && !box.isEmpty() ? Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1) : 15;
    controls.minDistance = 1;
    controls.maxDistance = Math.max(radius * 6, 20); // fitToItems lands at ~4.2 radii
    const height = threeOrtho.top - threeOrtho.bottom; // visible height at zoom 1
    controls.maxZoom = Math.max(height / 2, 1); // closest: ~2 m on screen
    controls.minZoom = Math.min(height / (radius * 8), 1); // farthest: ~4 model-diameters
  }

  get camera(): THREE.Camera | null {
    return this.world?.camera.three ?? null;
  }

  // --- visibility ----------------------------------------------------------

  async categories(): Promise<{ name: string; count: number }[]> {
    const model = this.model;
    if (!model) return [];
    const cats = await model.getCategories();
    const items = await model.getItemsOfCategories(cats.map((c) => new RegExp(`^${c}$`)));
    return cats
      .map((name) => ({ name, count: items[name]?.length ?? 0 }))
      .filter((c) => c.count > 0 && c.name !== "IFCOPENINGELEMENT")
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  async setCategoryVisible(category: string, visible: boolean) {
    visible ? this.hiddenCategories.delete(category) : this.hiddenCategories.add(category);
    const model = this.model;
    if (!model) return;
    const items = await model.getItemsOfCategories([new RegExp(`^${category}$`)]);
    const ids = items[category] ?? [];
    if (ids.length) await this.hider.set(visible, { [model.modelId]: new Set(ids) });
  }

  isCategoryHidden(category: string) {
    return this.hiddenCategories.has(category);
  }

  async setItemsVisible(ids: number[], visible: boolean) {
    const id = this.modelId;
    if (id && ids.length) await this.hider.set(visible, { [id]: new Set(ids) });
  }

  async select(localId: number) {
    const id = this.modelId;
    if (id) await this.highlighter.highlightByID(SELECT, { [id]: new Set([localId]) }, true, true);
  }

  /** Select the first element of an IFC class, e.g. "IFCWALL". Used by the smoke test. */
  async selectFirstOf(category: string) {
    const model = this.model;
    if (!model) return;
    const items = await model.getItemsOfCategories([new RegExp(`^${category}$`)]);
    const first = items[category]?.[0];
    if (first !== undefined) await this.select(first);
  }

  async hideSelection() {
    if (Object.keys(this.selection).length) {
      const sel = this.selection;
      await this.highlighter.clear(SELECT);
      await this.hider.set(false, sel);
    }
  }

  async isolateSelection() {
    if (Object.keys(this.selection).length) await this.hider.isolate(this.selection);
  }

  async showAll() {
    this.hiddenCategories.clear();
    await this.hider.set(true);
  }
}

function pretty(category: string | null) {
  if (!category) return "Item";
  const c = category.replace(/^IFC/i, "");
  return c.charAt(0) + c.slice(1).toLowerCase();
}

function fmt(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === "boolean") return v ? "True" : "False";
  return String(v);
}

function attr(item: FRAGS.ItemData, key: string): string {
  const v = item[key];
  return v && !Array.isArray(v) && v.value !== undefined && v.value !== null ? fmt(v.value) : "";
}

/** "IFCWALLSTANDARDCASE" → "IfcWallStandardCase" (best effort from the upper-case category). */
const KNOWN = ["Standard", "Case", "Element", "Opening", "Building", "Storey", "Proxy", "Covering", "Railing", "Curtain", "Flow", "Terminal", "Segment", "Fitting", "Member", "Plate", "Stair", "Flight", "Ramp", "Beam", "Column", "Wall", "Slab", "Roof", "Door", "Window", "Space", "Site", "Project", "Furnishing", "Footing", "Pile", "Distribution", "Port", "Annotation", "Grid", "Zone", "Group", "System", "Type", "Assembly"];
function ifcClass(category: string): string {
  let rest = category.replace(/^IFC/i, "").toLowerCase();
  let out = "Ifc";
  while (rest.length) {
    const word = KNOWN.find((w) => rest.startsWith(w.toLowerCase()));
    if (word) {
      out += word;
      rest = rest.slice(word.length);
    } else {
      out += rest.charAt(0).toUpperCase() + rest.slice(1);
      break;
    }
  }
  return out;
}
