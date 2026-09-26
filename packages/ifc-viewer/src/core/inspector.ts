import * as THREE from "three";
import * as OBC from "@thatopen/components";
import { RenderedFaces, type ItemData, type ItemAttribute } from "@thatopen/fragments";
import type { IfcViewport } from "./viewport";

export interface ElementInfo {
  localId: number;
  category: string;
  name?: string;
  guid?: string;
  attributes: Record<string, string>;
  /** Property set name -> property name -> value. */
  psets: Record<string, Record<string, string>>;
}

export interface VisibilityGroup {
  classification: "Levels" | "Categories";
  name: string;
  count: number;
  visible: boolean;
}

const HIGHLIGHT = {
  color: new THREE.Color("#ff7a1a"),
  renderedFaces: RenderedFaces.TWO,
  opacity: 1,
  transparent: false,
};

const isAttr = (v: unknown): v is ItemAttribute =>
  !!v && typeof v === "object" && !Array.isArray(v) && "value" in (v as object);

const fmt = (v: unknown): string => {
  if (v == null) return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  return String(v);
};

/**
 * Inspection tools layered on a viewport: click-to-select with properties,
 * storey/category visibility, and section planes. Framework agnostic.
 */
export class InspectorController {
  readonly onSelect = new Set<(info: ElementInfo | null) => void>();
  private selected: number | null = null;
  private clipper: OBC.Clipper;
  private classifier: OBC.Classifier;
  private hider: OBC.Hider;
  private hidden = new Set<string>();
  /** "Levels/<name>" or "Categories/<name>" -> the items in that group. */
  private groupMaps = new Map<string, OBC.ModelIdMap>();
  private sectionId: string | null = null;
  private downAt: { x: number; y: number } | null = null;
  private readonly abort = new AbortController();

  constructor(readonly viewport: IfcViewport) {
    const { components, world } = viewport;
    components.get(OBC.Raycasters).get(world);
    this.clipper = components.get(OBC.Clipper);
    this.clipper.setup();
    this.clipper.enabled = true;
    this.clipper.visible = false;
    this.classifier = components.get(OBC.Classifier);
    this.hider = components.get(OBC.Hider);

    const canvas = viewport.canvas;
    const signal = this.abort.signal;
    canvas.addEventListener("pointerdown", (e) => (this.downAt = { x: e.clientX, y: e.clientY }), { signal });
    canvas.addEventListener(
      "pointerup",
      (e) => {
        // Treat as a click only if the pointer did not drag (orbit).
        const d = this.downAt;
        this.downAt = null;
        if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) return;
        void this.pickAt(e.clientX, e.clientY);
      },
      { signal },
    );
  }

  /** Call after the viewport shows a new model. */
  async reset(): Promise<void> {
    this.selected = null;
    this.hidden.clear();
    this.groupMaps.clear();
    this.clearSection();
    this.classifier.list.delete("Levels");
    const model = this.viewport.currentModel;
    if (!model) return;

    // Levels: That Open's storey classifier fills static item maps.
    await this.classifier.byIfcBuildingStorey({ classificationName: "Levels" });
    for (const [name, data] of this.classifier.list.get("Levels") ?? []) {
      this.groupMaps.set(`Levels/${name}`, data.map);
    }

    // Categories: built directly from the model. The classifier's byCategory
    // registers lazy queries with empty maps and shares finder state across
    // models, which listed stale or empty groups.
    const withGeometry = new Set(await model.getItemsIdsWithGeometry());
    const categories = [...new Set((await model.getItemsWithGeometryCategories()).filter((c): c is string => !!c))].sort();
    if (categories.length) {
      const byCategory = await model.getItemsOfCategories(categories.map((c) => new RegExp(`^${c}$`)));
      for (const category of categories) {
        const ids = (byCategory[category] ?? []).filter((id) => withGeometry.has(id));
        if (ids.length) this.groupMaps.set(`Categories/${category}`, { [model.modelId]: new Set(ids) });
      }
    }
    this.emit(null);
  }

  // ------------------------------------------------------------ selection

  async pickAt(clientX: number, clientY: number): Promise<ElementInfo | null> {
    const hit = await this.viewport.fragments.raycast({
      camera: this.viewport.world.camera.three,
      mouse: new THREE.Vector2(clientX, clientY),
      dom: this.viewport.canvas,
    });
    return this.select(hit ? hit.localId : null);
  }

  async select(localId: number | null): Promise<ElementInfo | null> {
    const model = this.viewport.currentModel;
    if (!model) return null;
    await model.resetHighlight();
    this.selected = localId;
    if (localId == null) {
      await this.viewport.fragments.core.update(true);
      this.emit(null);
      return null;
    }
    await model.highlight([localId], HIGHLIGHT);
    await this.viewport.fragments.core.update(true);
    const info = await this.describe(localId);
    this.emit(info);
    return info;
  }

  get selectedId(): number | null {
    return this.selected;
  }

  async describe(localId: number): Promise<ElementInfo> {
    const model = this.viewport.currentModel!;
    const [data] = await model.getItemsData([localId], {
      attributesDefault: true,
      relations: {
        IsDefinedBy: { attributes: true, relations: true },
        HasProperties: { attributes: true, relations: false },
      },
      relationsDefault: { attributes: false, relations: false },
    });
    return toElementInfo(localId, data ?? {});
  }

  private emit(info: ElementInfo | null): void {
    for (const fn of this.onSelect) fn(info);
    this.viewport.invalidate();
  }

  // ------------------------------------------------------------ visibility

  groups(): VisibilityGroup[] {
    const out: VisibilityGroup[] = [];
    for (const [key, map] of this.groupMaps) {
      const slash = key.indexOf("/");
      const classification = key.slice(0, slash) as VisibilityGroup["classification"];
      const count = Object.values(map).reduce((n, ids) => n + ids.size, 0);
      out.push({ classification, name: key.slice(slash + 1), count, visible: !this.hidden.has(key) });
    }
    return out;
  }

  async setGroupVisible(classification: string, name: string, visible: boolean): Promise<void> {
    const key = `${classification}/${name}`;
    if (!this.groupMaps.has(key)) return;
    if (visible) this.hidden.delete(key);
    else this.hidden.add(key);
    await this.applyVisibility();
  }

  /**
   * Levels and categories overlap, so toggling one group incrementally can
   * resurrect elements another unchecked group should hide. Recompute from
   * scratch instead: an element is visible only if none of its groups is
   * hidden.
   */
  private async applyVisibility(): Promise<void> {
    await this.hider.set(true);
    for (const key of this.hidden) {
      const map = this.groupMaps.get(key);
      if (map) await this.hider.set(false, map);
    }
    await this.viewport.fragments.core.update(true);
    this.viewport.invalidate();
  }

  async showAll(): Promise<void> {
    this.hidden.clear();
    await this.applyVisibility();
  }

  // ------------------------------------------------------------ sections

  /** Horizontal section at a fraction (0..1) of the model height. */
  setSection(fraction: number | null): void {
    this.clearSection();
    const box = this.viewport.modelBox();
    if (fraction == null || !box) return;
    const y = THREE.MathUtils.lerp(box.min.y, box.max.y, THREE.MathUtils.clamp(fraction, 0, 1));
    const center = box.getCenter(new THREE.Vector3());
    this.sectionId = this.clipper.createFromNormalAndCoplanarPoint(
      this.viewport.world,
      new THREE.Vector3(0, -1, 0),
      new THREE.Vector3(center.x, y, center.z),
    );
    // New planes are created with their handle visible; hide it so only the
    // cut shows. (The setter applies to every plane in the clipper.)
    this.clipper.visible = false;
    void this.viewport.fragments.core.update(true);
    this.viewport.invalidate();
  }

  clearSection(): void {
    if (this.sectionId) {
      void this.clipper.delete(this.viewport.world, this.sectionId);
      this.sectionId = null;
      void this.viewport.fragments.core.update(true);
      this.viewport.invalidate();
    }
  }

  get hasSection(): boolean {
    return this.sectionId !== null;
  }

  dispose(): void {
    this.abort.abort();
    this.clearSection();
    this.onSelect.clear();
  }
}

/** Flatten fragments ItemData into a display-friendly shape. */
export function toElementInfo(localId: number, data: ItemData): ElementInfo {
  const attributes: Record<string, string> = {};
  const psets: Record<string, Record<string, string>> = {};
  let category = "";
  for (const [key, val] of Object.entries(data)) {
    if (isAttr(val)) {
      if (key === "_category") category = fmt(val.value);
      else if (!key.startsWith("_")) attributes[key] = fmt(val.value);
    }
  }
  const defs = data.IsDefinedBy;
  if (Array.isArray(defs)) {
    for (const pset of defs) {
      const psetName = isAttr(pset.Name) ? fmt(pset.Name.value) : "Properties";
      const props = pset.HasProperties;
      if (!Array.isArray(props)) continue;
      const bag: Record<string, string> = (psets[psetName] ??= {});
      for (const p of props) {
        const name = isAttr(p.Name) ? fmt(p.Name.value) : "?";
        const value = isAttr(p.NominalValue) ? fmt(p.NominalValue.value) : "";
        bag[name] = value;
      }
    }
  }
  return {
    localId,
    category: category || "Element",
    name: attributes.Name,
    guid: attributes.GlobalId,
    attributes,
    psets,
  };
}
