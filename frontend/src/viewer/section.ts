// Cross-section cut and "follow build", as in the original UI.
//
// The cut is a shared clipping plane in the viewer that hides everything above a height. Its range is the
// loaded model's own vertical extent in 0.1 m steps (previews included), with sticky snap points at each
// storey's floor and just under its ceiling, read from the IFC in the browser.
//
// While a request runs and "follow build" is on, the cut sits just under the ceiling of the storey the
// current steps are working on (a dollhouse view: roof and upper storeys hidden), and releases to full
// height when the roof lands or the request finishes. Dragging the slider takes over for that build.
import type { LegacyViewer } from "./LegacyViewer";

export interface Snap { z: number; label: string }

export interface SectionView {
  enabled: boolean;
  /** Slider range and value in tenths of a metre (integers, so the native range input snaps cleanly). */
  min: number;
  max: number;
  value: number;
  snaps: Snap[];
  label: string;
  follow: boolean;
}

const FOLLOW_KEY = "nocoast.follow";

export class SectionControl {
  private cut: number | null = null; // metres; null = full height
  private bottom = 0;
  private top = 0;
  private snaps: Snap[] = [];
  private following = false;
  private followLevel: string | null = null;
  private roomLevels: Record<string, string> = {};
  follow = localStorage.getItem(FOLLOW_KEY) !== "0";

  constructor(private viewer: LegacyViewer, private notify: (v: SectionView) => void) {}

  /** After every load: the range follows the new model's extent, the cut survives. */
  refresh() {
    const b = this.viewer.bounds();
    if (!b) {
      this.snaps = [];
      this.bottom = this.top = 0;
      this.viewer.setLayerCutoff(Infinity);
      this.notify(this.view());
      return;
    }
    this.bottom = Math.floor(b.min * 10) / 10;
    this.top = Math.ceil(b.max * 10) / 10;
    this.snaps = [];
    for (const s of this.viewer.storeys()) {
      this.snaps.push({ z: s.elevation, label: `${s.name} floor` });
      this.snaps.push({ z: Math.round((s.top - 0.3) * 10) / 10, label: `inside ${s.name}` });
    }
    this.apply();
  }

  private apply() {
    const full = this.cut === null || this.cut >= this.top;
    this.viewer.setLayerCutoff(full ? Infinity : (this.cut as number));
    this.notify(this.view());
  }

  view(): SectionView {
    const enabled = this.top > this.bottom;
    const full = this.cut === null || this.cut >= this.top;
    const cut = full ? this.top : (this.cut as number);
    const snap = full ? null : this.snaps.find((s) => Math.abs(s.z - cut) < 0.05);
    return {
      enabled,
      min: Math.round(this.bottom * 10),
      max: Math.round(this.top * 10),
      value: Math.round(cut * 10),
      snaps: this.snaps,
      label: !enabled ? "" : full ? "full height" : `cut at ${cut.toFixed(1)} m${snap ? ` · ${snap.label}` : ""}`,
      follow: this.follow,
    };
  }

  /** The user dragged the slider (value in tenths of a metre): snap to a storey mark within 0.2 m, take over from follow-build. */
  setValue(tenths: number) {
    let z = tenths / 10;
    const near = this.snaps.find((s) => Math.abs(s.z - z) <= 0.2);
    if (near) z = near.z;
    this.cut = z >= this.top ? null : z;
    this.following = false;
    this.apply();
  }

  setFollow(on: boolean) {
    this.follow = on;
    localStorage.setItem(FOLLOW_KEY, on ? "1" : "0");
    this.notify(this.view());
  }

  startRun() {
    this.following = this.follow;
    this.followLevel = null;
  }

  /** An accepted step: remember which level the build is working on (rooms map to their level). */
  learnStep(step: Record<string, unknown>) {
    const k = step.step;
    const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (k === "room" && typeof step.name === "string" && typeof step.level === "string") {
      this.roomLevels[typeof step.id === "string" ? step.id : slug(step.name)] = step.level;
      this.roomLevels[slug(step.name)] = step.level;
    }
    if (k === "layout" && Array.isArray(step.rooms) && typeof step.level === "string") {
      for (const r of step.rooms as { id?: string; name?: string }[]) {
        if (typeof r.name === "string") this.roomLevels[slug(r.name)] = step.level;
        if (typeof r.id === "string") this.roomLevels[r.id] = step.level;
      }
    }
    if (k === "roof") {
      this.followLevel = null;
      this.applyFollow();
      return;
    }
    const level = typeof step.level === "string" ? step.level : typeof step.room === "string" ? this.roomLevels[step.room] : undefined;
    if (level && k !== "building" && k !== "level") this.followLevel = level;
    this.applyFollow();
  }

  finishRun() {
    this.followLevel = null;
    this.applyFollow();
    this.following = false;
  }

  /** Move the cut to the storey being worked on (called after each step and after each preview load). */
  applyFollow() {
    if (!this.following) return;
    if (this.followLevel === null) {
      this.cut = null;
    } else {
      const storey = this.viewer.storeys().find((st) => st.id === this.followLevel);
      if (!storey) return; // not in the model yet; the next preview will have it
      this.cut = Math.round((storey.top - 0.3) * 10) / 10;
    }
    this.apply();
  }

  /** Forget everything model-specific (new session). */
  reset() {
    this.cut = null;
    this.followLevel = null;
    this.roomLevels = {};
    this.refresh();
  }
}
