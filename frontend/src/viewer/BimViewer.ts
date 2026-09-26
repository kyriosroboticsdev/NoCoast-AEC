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

  async init(container: HTMLElement) {
    const worlds = this.components.get(OBC.Worlds);
    const world = worlds.create<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>();
    world.scene = new OBC.SimpleScene(this.components);
    world.scene.setup();
    world.scene.three.background = new THREE.Color("#14171d");
    world.renderer = new OBC.SimpleRenderer(this.components, container);
    world.camera = new OBC.OrthoPerspectiveCamera(this.components);
    await world.camera.controls.setLookAt(25, 18, 25, 0, 2, 0);
    this.components.init();
    this.world = world;

    const grid = this.components.get(OBC.Grids).create(world);
    grid.material.uniforms.uColor.value = new THREE.Color("#2a2f3a");

    this.fragments = this.components.get(OBC.FragmentsManager);
    this.fragments.init(workerUrl);
    world.camera.controls.addEventListener("update", () => this.fragments.core.update());
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
