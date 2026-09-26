// Rudimentary UI: a viewer and a prompt box. State = one project id (kept in localStorage) + its head version.

import * as api from "./api";
import { Viewer } from "./viewer";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
// Verbose console log: open DevTools (F12) and filter on [nocoast].
export const log = (...args: unknown[]) => console.log("[nocoast]", new Date().toISOString().slice(11, 23), ...args);
window.addEventListener("error", (e) => console.error("[nocoast] uncaught:", e.message, e.error));
window.addEventListener("unhandledrejection", (e) => console.error("[nocoast] unhandled rejection:", e.reason));
log("page loaded", location.href, "backend:", api.BACKEND, "userAgent:", navigator.userAgent);
const text = $<HTMLTextAreaElement>("text");
const send = $<HTMLButtonElement>("send");
const status = $<HTMLDivElement>("status");
const notes = $<HTMLPreElement>("notes");
const undo = $<HTMLButtonElement>("undo");
const download = $<HTMLAnchorElement>("download");
const projectLabel = $<HTMLSpanElement>("project");
const picked = $<HTMLSpanElement>("picked");
const showing = $<HTMLDivElement>("showing");
const stepsList = $<HTMLOListElement>("steps-list");
const stepsText = $<HTMLPreElement>("steps-text");
const stepsJson = $<HTMLInputElement>("steps-json");
const stepsVerbose = $<HTMLInputElement>("steps-verbose");
const layerSlider = $<HTMLInputElement>("layerSlider");
const layerLabel = $<HTMLSpanElement>("layerLabel");
const layerSnaps = $<HTMLDataListElement>("layerSnaps");
const followBuild = $<HTMLInputElement>("followBuild");
const focusChip = $<HTMLDivElement>("focus");
const focusLabel = $<HTMLSpanElement>("focus-label");
const inspector = $<HTMLDivElement>("inspector");
const inspectorTitle = $<HTMLSpanElement>("inspector-title");
const inspectorDesign = $<HTMLTableElement>("inspector-design");
const inspectorPsets = $<HTMLDivElement>("inspector-psets");

let projectId = "";
let head: api.Version | null = null;
let busy = false;

const viewer = new Viewer($<HTMLCanvasElement>("viewport"), (p) => onPick(p));
(window as unknown as { nocoast: unknown }).nocoast = { viewer }; // for DevTools and the headless smoke tests

function setStatus(msg: string, error = false) {
  status.textContent = msg;
  status.classList.toggle("error", error);
  (error ? console.error : console.log)("[nocoast] status:", msg);
}

function setBusy(b: boolean) {
  busy = b;
  updateControls();
}

function updateControls() {
  send.disabled = busy;
  undo.disabled = busy || !head || head.number < 2;
}

// Cross-section slider: a shared clipping plane in the viewer hides everything above a height. The
// range is the loaded model's own extent in 0.1 m steps (previews included), with sticky snap points at
// each storey's floor and just under its ceiling, read from the IFC in the browser.
let sectionCut: number | null = Number(new URLSearchParams(location.search).get("section")) || null; // metres; null = full height (?section=2.4 presets it for smoke tests)
let sectionSnaps: { z: number; label: string }[] = [];
let modelBottom = 0;
let modelTop = 0;

function refreshSection() {
  const b = viewer.bounds();
  if (!b) {
    layerSlider.disabled = true;
    layerLabel.textContent = "";
    sectionSnaps = [];
    return;
  }
  modelBottom = Math.floor(b.min * 10) / 10;
  modelTop = Math.ceil(b.max * 10) / 10;
  layerSlider.min = String(Math.round(modelBottom * 10));
  layerSlider.max = String(Math.round(modelTop * 10));
  layerSlider.step = "1";
  sectionSnaps = [];
  for (const s of viewer.storeys()) {
    sectionSnaps.push({ z: s.elevation, label: `${s.name} floor` });
    sectionSnaps.push({ z: Math.round((s.top - 0.3) * 10) / 10, label: `inside ${s.name}` });
  }
  layerSnaps.replaceChildren(...sectionSnaps.map((s) => Object.assign(document.createElement("option"), { value: String(Math.round(s.z * 10)), label: s.label })));
  layerSlider.disabled = false;
  applySection();
}

function applySection() {
  const full = sectionCut === null || sectionCut >= modelTop;
  const cut = full ? modelTop : (sectionCut as number);
  viewer.setLayerCutoff(full ? Infinity : cut);
  layerSlider.value = String(Math.round(cut * 10));
  const snap = full ? null : sectionSnaps.find((s) => Math.abs(s.z - cut) < 0.05);
  layerLabel.textContent = full ? "full height" : `cut at ${cut.toFixed(1)} m${snap ? " · " + snap.label : ""}`;
}

layerSlider.oninput = () => {
  let z = Number(layerSlider.value) / 10;
  const near = sectionSnaps.find((s) => Math.abs(s.z - z) <= 0.2);
  if (near) z = near.z;
  sectionCut = z >= modelTop ? null : z;
  following = false; // the user took over the cut for this build
  applySection();
};

// "Follow build": while a request runs, the section cut sits just under the ceiling of the storey the
// current steps are working on (a dollhouse view, roof and upper storeys hidden), and releases to full
// height when the roof lands or the request finishes. Dragging the slider takes over for that build.
let following = false;
let followLevel: string | null = null; // level id the latest step worked on
const roomLevels: Record<string, string> = {}; // room id → level id, learned from room/layout steps
followBuild.checked = localStorage.getItem("nocoast.follow") !== "0";
followBuild.onchange = () => localStorage.setItem("nocoast.follow", followBuild.checked ? "1" : "0");

function applyFollow() {
  if (!following) return;
  if (followLevel === null) {
    sectionCut = null;
  } else {
    const storey = viewer.storeys().find((st) => st.id === followLevel);
    if (!storey) return; // not in the model yet; the next preview will have it
    sectionCut = Math.round((storey.top - 0.3) * 10) / 10;
  }
  applySection();
}

const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** Remember room names and levels from an accepted step, and which level the build is working on. */
function learnStep(step: Record<string, unknown>) {
  const k = step.step;
  if (k === "room" && typeof step.name === "string") {
    const id = typeof step.id === "string" ? step.id : slug(step.name);
    roomNames[id] = roomNames[slug(step.name)] = step.name;
    if (typeof step.level === "string") roomLevels[id] = step.level;
  }
  if (k === "layout" && Array.isArray(step.rooms)) {
    for (const r of step.rooms as { name?: string }[]) {
      if (typeof r.name !== "string") continue;
      roomNames[slug(r.name)] = r.name;
      if (typeof step.level === "string") roomLevels[slug(r.name)] = step.level;
    }
  }
  if (k === "roof") {
    followLevel = null;
    return;
  }
  const level = typeof step.level === "string" ? step.level : typeof step.room === "string" ? roomLevels[step.room] : undefined;
  if (level && k !== "building" && k !== "level") followLevel = level;
}

// --- selection --------------------------------------------------------------------------------------
// One element at a time. Clicking a wall, door, window, stair or piece of furniture selects it; clicking a
// floor selects the room under the click. The selection is shown as a chip above the prompt, sent with the
// next prompt as `focus` (the spec element id, which the backend describes to the model), and detailed in
// the inspector: design-level facts first, the IFC attributes and property sets underneath.

let design: api.Design | null = null; // the head version's design record (null before the first version, or for imports without one)
let spaces: { id: string; level: string; outline: [number, number][] }[] = []; // IfcSpace outlines of the head version, for floor clicks
let focus: { id: string; label: string } | null = null;

const SIDE_NAMES: Record<string, string> = { N: "north", S: "south", E: "east", W: "west" };
const roomLabel = (id: string) => { const r = design?.rooms.find((x) => x.id === id); return r ? `the ${r.name}` : `the ${id}`; };
const levelLabel = (id: string) => { const l = design?.levels.find((x) => x.id === id); return l?.name ?? levelName(id).replace(/^the /, ""); };

/** Design-level facts about a spec element id: a title and key/value rows, or null when the id is unknown. */
function describeElement(id: string): { title: string; rows: [string, string][]; roomId?: string } | null {
  if (!design) return null;
  let m = id.match(/^(\w+?)-wall-([\w-]+)\+([\w-]+)$/);
  if (m) return { title: `Wall between ${roomLabel(m[2])} and ${roomLabel(m[3])}`, rows: [["level", levelLabel(m[1])], ["type", "partition wall, 0.12 m"], ["rooms", `${roomLabel(m[2])}, ${roomLabel(m[3])}`]] };
  m = id.match(/^(\w+?)-wall-([\w-]+)-([NSEW])$/);
  if (m) return { title: `${SIDE_NAMES[m[3]]} wall of ${roomLabel(m[2])}`, rows: [["level", levelLabel(m[1])], ["type", `exterior wall, 0.3 m${design.wall_material ? ", " + design.wall_material : ""}`], ["room", roomLabel(m[2])], ["side", SIDE_NAMES[m[3]]]], roomId: m[2] };
  m = id.match(/^(\w+?)-space-([\w-]+)$/);
  const room = m ? design.rooms.find((r) => r.id === m![2]) : design.rooms.find((r) => r.id === id);
  if (room) {
    const rect = room.rect;
    const shape: [string, string][] = rect
      ? [["size", `${rect[2]} × ${rect[3]} m (${(rect[2] * rect[3]).toFixed(1)} m²)`], ["position", `x ${rect[0]}, y ${rect[1]}`]]
      : room.poly ? [["shape", `${room.poly.length} sides${room.poly.some((e) => e.through) ? ", curved" : ""}${room.poly.some((e) => e.open) ? `, ${room.poly.filter((e) => e.open).length} open` : ""} (${polyArea(room.poly).toFixed(1)} m²)`]] : [];
    const flags: [string, string][] = [...(room.roofed ? [] : [["roof", "none (open air)"]] as [string, string][]), ...(room.enclosed ? [] : [["walls", "none, columns carry the roof"]] as [string, string][])];
    return { title: `${room.name}`, rows: [["level", levelLabel(room.level)], ["kind", room.kind], ...shape, ...flags,
      ["doors", design.doors.filter((d) => d.room === room.id || d.to === room.id).map((d) => d.to === "outside" ? "entrance" : d.room === room.id ? roomLabel(d.to) : roomLabel(d.room ?? "")).join(", ") || "none"],
      ["windows", String(design.windows.filter((w) => w.room === room.id).length)],
      ["furniture", design.fixtures.filter((f) => f.room === room.id).map((f) => f.kind.replace(/_/g, " ")).join(", ") || "none"]], roomId: room.id };
  }
  m = id.match(/^(\w+?)-(floor|slab)$/);
  if (m) return { title: `Floor slab of ${levelLabel(m[1])}`, rows: [["level", levelLabel(m[1])]] };
  if (id === "roof" || id.endsWith("-roof")) return { title: id.startsWith("porch") ? "Porch roof" : "Roof", rows: [["kind", design.roof.kind], ...(design.roof.kind !== "flat" ? [["pitch", `${design.roof.pitch}°`]] as [string, string][] : []), ["overhang", `${design.roof.overhang} m`]] };
  const where = (it: { side?: string | null; near?: [number, number] | null }): [string, string][] =>
    it.near ? [["wall", `the one near x ${it.near[0]}, y ${it.near[1]}`]] : it.side ? [["side", SIDE_NAMES[it.side] ?? it.side]] : [];
  const door = design.doors.find((d) => d.id === id);
  if (door) return { title: door.wall ? `Door in ${door.wall}` : door.to === "outside" ? `Entrance door of ${roomLabel(door.room ?? "")}` : `Door between ${roomLabel(door.room ?? "")} and ${roomLabel(door.to)}`, rows: [["kind", door.kind], ...(door.width && door.height ? [["size", `${door.width} × ${door.height} m`]] as [string, string][] : []), ...where(door), ["position", `${Math.round(door.at * 100)}% along the wall`]], roomId: door.room ?? undefined };
  const win = design.windows.find((w) => w.id === id);
  if (win) return { title: win.wall ? `Window in ${win.wall}` : win.side ? `Window on the ${SIDE_NAMES[win.side]} wall of ${roomLabel(win.room ?? "")}` : `Window of ${roomLabel(win.room ?? "")}`, rows: [["kind", win.kind], ...(win.width && win.height ? [["size", `${win.width} × ${win.height} m`]] as [string, string][] : []), ...(win.sill !== null ? [["sill", `${win.sill} m`]] as [string, string][] : []), ...where(win), ["position", `${Math.round(win.at * 100)}% along the wall`]], roomId: win.room ?? undefined };
  const stair = design.stairs.find((s) => s.id === id);
  if (stair) return { title: `Stair in ${roomLabel(stair.room)}`, rows: [...(stair.side ? [["along", `${SIDE_NAMES[stair.side]} wall`]] as [string, string][] : where(stair)), ["width", `${stair.width} m`], ["to", stair.to_level ? levelLabel(stair.to_level) : "the level above"]], roomId: stair.room };
  const fx = design.fixtures.find((f) => f.id === id);
  if (fx) return { title: `${fx.kind.replace(/_/g, " ")} in ${roomLabel(fx.room)}`.replace(/^\w/, (c) => c.toUpperCase()), rows: [["kind", fx.kind.replace(/_/g, " ")], ["placement", fx.near ? `against the wall near x ${fx.near[0]}, y ${fx.near[1]}` : fx.side === "center" ? "middle of the room" : `against the ${SIDE_NAMES[fx.side]} wall`], ...(fx.width && fx.depth ? [["size", `${fx.width} × ${fx.depth}${fx.height ? " × " + fx.height : ""} m`]] as [string, string][] : [])], roomId: fx.room };
  const bal = design.balconies.find((b) => b.id === id);
  if (bal) return { title: `Balcony of ${roomLabel(bal.room)}`, rows: [...where(bal), ["depth", `${bal.depth} m`]], roomId: bal.room };
  if (id.startsWith("porch")) return { title: "Porch", rows: design.porch ? [["side", SIDE_NAMES[design.porch.side]], ["depth", `${design.porch.depth} m`]] : [] };
  const col = design.columns.find((c) => c.id === id);
  if (col) return { title: "Column", rows: [["level", levelLabel(col.level)], ["position", `x ${col.x}, y ${col.y}`]] };
  const free = design.elements.find((e) => e.id === id);
  if (free) return { title: free.name ?? `Free-standing ${free.kind}`, rows: [["type", `free-standing ${free.kind}`], ["level", levelLabel(free.level)], ...(free.height ? [["height", `${free.height} m`]] as [string, string][] : []), ...(free.thickness ? [["thickness", `${free.thickness} m`]] as [string, string][] : [])] };
  m = id.match(/^(\w+?)-col-([\w-]+)-([NSEW])(?:-\d+)?$/);
  if (m) return { title: `Column on the ${SIDE_NAMES[m[3]]} side of ${roomLabel(m[2])}`, rows: [["level", levelLabel(m[1])], ["type", "column along an open edge"]], roomId: m[2] };
  m = id.match(/^(\w+?)-rail-([\w-]+)-([NSEW])(?:-\d+)?$/);
  if (m) return { title: `Railing on the ${SIDE_NAMES[m[3]]} side of ${roomLabel(m[2])}`, rows: [["level", levelLabel(m[1])], ["type", "railing of an unroofed room"]], roomId: m[2] };
  return null;
}

function polyArea(poly: api.Edge[]): number {
  const pts = poly.map((e) => e.to);
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

function inPolygon(pts: [number, number][], x: number, y: number): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** The room whose space outline (from the compiled spec, so curved and L-shaped rooms work) contains plan point (x, y) on `level`. */
function roomAt(level: string, x: number, y: number) {
  const hit = spaces.find((s) => s.level === level && inPolygon(s.outline, x, y));
  if (hit) return design?.rooms.find((r) => `${level}-space-${r.id}` === hit.id) ?? null;
  return design?.rooms.find((r) => r.level === level && r.rect && x >= r.rect[0] && x <= r.rect[0] + r.rect[2] && y >= r.rect[1] && y <= r.rect[1] + r.rect[3]) ?? null;
}

function setFocus(id: string | null, label?: string) {
  focus = id ? { id, label: label ?? describeElement(id)?.title ?? id } : null;
  focusChip.hidden = !focus;
  focusLabel.textContent = focus?.label ?? "";
  viewer.highlight(id);
}

async function showInspector(p: import("./viewer").Picked, id: string) {
  const d = describeElement(id);
  inspectorTitle.textContent = d?.title ?? `${p.type.replace(/^Ifc/, "")} ${id}`;
  inspectorDesign.replaceChildren(...(d?.rows ?? []).map(([k, v]) => {
    const tr = document.createElement("tr");
    tr.append(Object.assign(document.createElement("td"), { textContent: k }), Object.assign(document.createElement("td"), { textContent: v }));
    return tr;
  }));
  inspector.hidden = false;
  const sets = await viewer.properties(p.expressID);
  inspectorPsets.replaceChildren(...sets.flatMap((ps) => {
    const h = Object.assign(document.createElement("h4"), { textContent: ps.name });
    const table = document.createElement("table");
    for (const [k, v] of ps.props) {
      const tr = document.createElement("tr");
      tr.append(Object.assign(document.createElement("td"), { textContent: k }), Object.assign(document.createElement("td"), { textContent: v }));
      table.append(tr);
    }
    return [h, table];
  }));
}

function onPick(p: import("./viewer").Picked | null) {
  picked.textContent = p ? `${p.type} ${p.tag || p.name} ${p.globalId}` : "";
  if (!p) {
    setFocus(null);
    inspector.hidden = true;
    return;
  }
  let id = p.tag || p.name;
  // A click on a floor slab selects the room under it.
  const slab = id.match(/^(\w+?)-(floor|slab)$/);
  if (slab) {
    const room = roomAt(slab[1], p.point.x, p.point.y);
    if (room) id = `${slab[1]}-space-${room.id}`;
  }
  log("picked", p.type, id, "at", p.point);
  setFocus(id);
  void showInspector(p, id);
}

$<HTMLButtonElement>("focus-clear").onclick = () => { setFocus(null); inspector.hidden = true; };
$<HTMLButtonElement>("inspector-close").onclick = () => (inspector.hidden = true);

// The camera is framed on the first model of a project and then left alone: previews and new
// versions load into the same view, so the building grows in place instead of jumping around.
let framed = false;

async function loadIntoViewer(bytes: Uint8Array) {
  await viewer.load(bytes, framed);
  // A first preview can be tiny (a riser and a panel before the rooms have streamed in); framing on that
  // would leave the camera inside the building that follows, so the frame only counts once there is one.
  const b = viewer.bounds();
  framed = !!b && viewer.extent() >= 3;
  refreshSection(); // the section cut survives reloads; the range follows the new model's extent
  applyFollow();
}

async function showVersion(v: api.Version | null) {
  head = v;
  projectLabel.textContent = v ? `project ${projectId} · v${v.number} (${v.mode}${v.llm ? ", " + v.llm : ""})` : `project ${projectId} · empty`;
  download.hidden = !v;
  if (v) {
    download.href = api.BACKEND + v.ifc_url;
    download.download = `nocoast-v${v.number}.ifc`;
    const checks = (v.checks ?? []).filter((c) => c.status !== "met").map((c) => `${c.status === "unmet" ? "✗" : "–"} ${c.text}: ${c.detail}`);
    notes.textContent = [...v.notes, ...checks, `elements: ${JSON.stringify(v.summary.counts)}`].join("\n");
    log("version", v.number, v.mode, "fetching", v.ifc_url);
    try {
      const s = await api.fetchSpec(projectId, v.number);
      design = s.design;
      spaces = s.spec.elements.filter((e) => e.type === "space").map((e) => ({ id: String(e.id), level: String(e.level), outline: e.outline as [number, number][] }));
    } catch (err) {
      log("design record unavailable:", String(err));
      design = null;
      spaces = [];
    }
    const bytes = await api.fetchIfc(v.ifc_url);
    log("ifc fetched:", bytes.length, "bytes; loading into web-ifc");
    const t = performance.now();
    await loadIntoViewer(bytes);
    log("viewer loaded in", Math.round(performance.now() - t), "ms");
    shownRow?.classList.remove("shown");
    shownRow = null;
    setShowing(`v${v.number} · final · ${v.summary.elements} elements`, false);
  } else {
    notes.textContent = "";
    design = null;
    viewer.clear();
    setShowing("", false);
    refreshSection();
  }
  setFocus(null);
  inspector.hidden = true;
  setBusy(false);
}

// --- step log ------------------------------------------------------------------------------------
// Every SSE event is kept; the list is rendered in one of two modes. "Friendly" reads like an
// assistant thinking aloud (what it understood, what it is adding, what it skipped and why, what it
// checked); "verbose" shows every event with stage, timing and raw details. Toggling re-renders.

let streamRow: HTMLLIElement | null = null;
let shownRow: HTMLLIElement | null = null;
let events: api.StageEvent[] = [];
const roomNames: Record<string, string> = {}; // room id → display name, learned from room steps
const rowsByEvent = new Map<api.StageEvent, HTMLLIElement>();
let verbose = localStorage.getItem("nocoast.verbose") === "1";
stepsVerbose.checked = verbose;

function setShowing(label: string, preview: boolean) {
  showing.textContent = label;
  showing.classList.toggle("preview", preview);
}

// --- friendly wording ---------------------------------------------------------------------------

function roomName(id: unknown): string {
  if (typeof id !== "string") return "the room";
  if (roomNames[id]) return "the " + roomNames[id];
  if (id === "outside") return "outside";
  return "the " + id.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function levelName(id: unknown): string {
  if (typeof id !== "string") return "the ground floor";
  if (/^B\d+$/i.test(id)) { const b = Number(id.slice(1)); return b === 1 ? "the basement" : `basement level ${b}`; }
  const n = Number(id.replace(/^L/i, ""));
  return n === 1 ? "the ground floor" : n === 2 ? "the first floor" : `level ${n}`;
}

const SIDES: Record<string, string> = { N: "north", S: "south", E: "east", W: "west", center: "middle" };
const side = (s: unknown) => SIDES[String(s)] ?? String(s ?? "");
const kindName = (k: unknown) => String(k ?? "").replace(/_/g, " ");
const pt = (p: unknown) => (Array.isArray(p) ? `(${p[0]}, ${p[1]})` : "");
/** "on the north wall" or "on the wall near (x, y)" for a step that names a wall by side or point. */
const wallOf = (step: Record<string, unknown>) => (step.near ? `on the wall near ${pt(step.near)}` : step.side ? `on the ${side(step.side)} wall` : "on the outer wall");

function friendlyStep(step: Record<string, unknown>, ok: boolean, message: string): string {
  const k = step.step;
  const rect = Array.isArray(step.rect) ? (step.rect as number[]) : null;
  const size = rect ? ` (${rect[2]} × ${rect[3]} m)` : "";
  const name = typeof step.name === "string" ? step.name : "";
  switch (k) {
    case "building": return name ? `Calling the building “${name}”` : "Describing the building";
    case "level": return `Adding ${levelName(step.id ?? step.level)}${step.height ? `, ${step.height} m high` : ""}`;
    case "room": {
      const verb = message.includes("updated") ? (step.poly ? "Reshaping" : "Moving") : "Adding";
      const poly = Array.isArray(step.poly) ? (step.poly as unknown[]) : null;
      const shape = poly ? ` (${poly.length}-sided${poly.some((e) => typeof e === "object" && e !== null && "through" in (e as object)) ? ", curved" : ""})` : size;
      const kind = String(step.kind ?? "");
      const air = kind === "courtyard" || kind === "terrace" || step.roofed === false ? ", open to the sky" : kind === "carport" || kind === "pergola" || step.enclosed === false ? ", on columns" : "";
      return `${verb} the ${name || roomName(step.id).replace(/^the /, "")} on ${levelName(step.level)}${shape}${air}`;
    }
    case "layout": {
      const names = Array.isArray(step.rooms) ? (step.rooms as { name?: string }[]).map((r) => r.name).filter(Boolean) : [];
      const verb = message.includes("; removed") || message.includes("updated") ? "Rearranging" : "Laying out";
      return `${verb} ${levelName(step.level)}${names.length ? ": " + names.join(", ") : ""}`;
    }
    case "door": {
      const to = String(step.to ?? "outside");
      if (step.wall && !step.room) return `Door in the ${String(step.wall).replace(/-/g, " ")}`;
      if (to === "outside" || to === "exterior") return `${step.kind === "garage" ? "Garage door" : "Entrance door"} ${wallOf(step)} of ${roomName(step.room)}`;
      return `Door between ${roomName(step.room)} and ${roomName(to)}${step.kind && step.kind !== "single" ? ` (${kindName(step.kind)})` : ""}`;
    }
    case "window": {
      if (step.wall && !step.room) return `Window in the ${String(step.wall).replace(/-/g, " ")}`;
      return `${step.kind && step.kind !== "standard" ? kindName(step.kind) + " window" : "Window"} ${wallOf(step)} of ${roomName(step.room)}`.replace(/^\w/, (c) => c.toUpperCase());
    }
    case "stair": return `Stairs in ${roomName(step.room)}, along the ${step.near ? "wall near " + pt(step.near) : side(step.side ?? "W") + " wall"}`;
    case "furniture": return `A ${kindName(step.kind)} in ${roomName(step.room)}${step.near ? `, against the wall near ${pt(step.near)}` : step.side && step.side !== "center" ? `, against the ${side(step.side)} wall` : ""}`;
    case "balcony": return `Balcony ${wallOf(step)} of ${roomName(step.room)}`;
    case "element": return `A free-standing ${kindName(step.kind)}${name ? ` “${name}”` : ""} on ${levelName(step.level)}`;
    case "porch": return `Porch along the ${side(step.side ?? "S")} side`;
    case "roof": return `${String(step.kind ?? "flat").replace(/^\w/, (c) => c.toUpperCase())} roof${step.pitch ? ` at ${step.pitch}°` : ""}`;
    case "material": return `${String(step.material ?? step.kind ?? "").replace(/^\w/, (c) => c.toUpperCase())} exterior walls`;
    case "column": return `A column on ${levelName(step.level)}`;
    case "remove": return `Removing ${roomName(step.id)}`;
    case "note": return String(step.text ?? "");
    default: return ok ? message : "A step";
  }
}

function friendlyReason(error: unknown): string {
  return String(error ?? "").replace(/^applying this step makes the design unbuildable: /, "").replace(/^(door|window|stair|balcony|furniture|room|layout|level|remove)\b[^:]*: /, "");
}

/** Friendly text for an event, or null when the event is noise in friendly mode. */
function friendly(e: api.StageEvent): { text: string; detail?: string; muted?: boolean } | null {
  const d = e.data ?? {};
  switch (e.stage) {
    case "requirements": {
      if (!Array.isArray(d.requirements)) return { text: (d.errors as string[])?.length ? "Re-reading your request…" : "Reading your request…", muted: true };
      const reqs = d.requirements as { text: string; supported?: boolean }[];
      const unsupported = reqs.filter((r) => r.supported === false);
      const detail = reqs.map((r) => `${r.supported === false ? "✗ can't do: " : "• "}${r.text}`).join("\n");
      return { text: `I understood ${reqs.length} thing${reqs.length === 1 ? "" : "s"} to build${unsupported.length ? `, ${unsupported.length} of which I can't do` : ""}`, detail };
    }
    case "build": {
      const p = (d.problems as string[]) ?? [];
      const u = (d.unmet as string[]) ?? [];
      if (p.length) return { text: `Fixing ${p.length} step${p.length === 1 ? "" : "s"} that didn't work…`, muted: true };
      if (u.length) return { text: `Going back for ${u.length} thing${u.length === 1 ? "" : "s"} still missing…`, detail: u.map((x) => "• " + x).join("\n"), muted: true };
      return { text: e.message.startsWith("editing") ? "Working out what to change…" : "Laying out the building…", muted: true };
    }
    case "step": {
      const step = (d.step as Record<string, unknown>) ?? {};
      const what = friendlyStep(step, d.ok !== false, e.message);
      if (d.ok === false) return { text: `Skipped: ${what.replace(/^\w/, (c) => c.toLowerCase())}`, detail: friendlyReason(d.error) };
      const pruned = e.message.includes("; removed ") ? e.message.split("; ").slice(1).map((s) => "• " + s.replace(/^removed (\w+) ([\w-]+): /, "dropped a $1 because ")).join("\n") : undefined;
      return { text: what, detail: pruned };
    }
    case "verify": {
      const rs = (d.results as { text: string; status: string; detail: string }[]) ?? [];
      const met = rs.filter((r) => r.status === "met").length;
      const checkable = rs.filter((r) => r.status === "met" || r.status === "unmet").length;
      const unmet = rs.filter((r) => r.status === "unmet");
      if (!rs.length) return { text: e.message };
      return { text: `Checked the result: ${met} of ${checkable} requirements met`, detail: unmet.length ? unmet.map((r) => `✗ ${r.text} — ${r.detail}`).join("\n") : undefined };
    }
    case "compile": return { text: "Finishing the model…", muted: true };
    case "focus": return { text: `Working on ${String(d.text ?? "the selection").replace(/ \((wall|room) id [^)]*\)/, "")}`, muted: true };
    case "done": {
      const v = d as unknown as api.Version;
      return { text: `Done — version ${v.number}, ${v.summary?.elements ?? "?"} elements` };
    }
    case "error": return { text: e.message };
    case "validate": case "apply": return { text: e.message, detail: (d.errors as string[])?.map((x) => "• " + x).join("\n") };
    default: return null; // llm, stream, partial: technical
  }
}

// --- verbose wording ----------------------------------------------------------------------------

function detailFor(e: api.StageEvent): string | undefined {
  const d = e.data ?? {};
  const errs = d.errors as string[] | undefined;
  if (errs?.length) return errs.map((x) => "• " + x).join("\n");
  if (e.stage === "llm" && d.model) return `${d.provider} ${d.model} · system ${d.system_chars} chars · user ${d.user_chars} chars`;
  if (e.stage === "requirements" && Array.isArray(d.requirements)) {
    const reqs = d.requirements as { text: string; kind: string; supported?: boolean }[];
    return reqs.map((r) => `${r.supported === false ? "✗" : "•"} ${r.text} [${r.kind}]`).join("\n");
  }
  if (e.stage === "build") {
    const p = (d.problems as string[]) ?? [];
    const u = (d.unmet as string[]) ?? [];
    return [...p, ...u].map((x) => "• " + x).join("\n") || undefined;
  }
  if (e.stage === "step") return d.ok === false ? `${JSON.stringify(d.step)}\n${d.error}` : undefined;
  if (e.stage === "verify" && Array.isArray(d.results)) {
    const rs = d.results as { text: string; status: string; detail: string }[];
    const mark: Record<string, string> = { met: "✓", unmet: "✗", unsupported: "–", skipped: "?" };
    return rs.map((r) => `${mark[r.status] ?? "?"} ${r.text} — ${r.detail}`).join("\n");
  }
  if (e.stage === "validate" && Array.isArray(d.rooms)) return (d.rooms as string[]).join(", ");
  if (e.stage === "apply" && Array.isArray(d.cascade)) return (d.cascade as string[]).map((x) => "• " + x).join("\n");
  if (e.stage === "partial" && typeof d.ifc_url === "string") {
    const rooms = d.rooms as Record<string, string[]>;
    const roomLine = Object.entries(rooms ?? {}).map(([l, n]) => `${l}: ${n.join(", ") || "–"}`).join(" | ");
    return `${JSON.stringify(d.counts)} · compiled in ${d.compile_ms} ms after ${d.steps} steps (${d.checked} re-checked)\n${roomLine}`;
  }
  if (e.stage === "done") {
    const v = d as unknown as api.Version;
    return `v${v.number} ${v.mode} · ${JSON.stringify(v.summary?.counts)}${v.notes?.length ? "\n" + v.notes.map((n) => "• " + n).join("\n") : ""}`;
  }
  return undefined;
}

// --- rendering --------------------------------------------------------------------------------------

function makeRow(e: api.StageEvent): HTMLLIElement | null {
  const li = document.createElement("li");
  li.className = e.stage;
  const errs = (e.data?.errors as string[] | undefined) ?? [];
  const bad = (e.stage === "validate" && errs.length > 0) || (e.stage === "step" && e.data?.ok === false)
    || (e.stage === "verify" && ((e.data?.unmet as string[]) ?? []).length > 0)
    || (e.stage === "requirements" && ((e.data?.unsupported as string[]) ?? []).length > 0);
  if (bad) li.classList.add("bad");
  let detail: string | undefined;
  if (verbose) {
    li.innerHTML = `<span class="t">${e.t.toFixed(1)}s</span><span class="stage">${e.stage}</span> `;
    li.append(document.createTextNode(e.message));
    detail = detailFor(e);
  } else {
    const f = friendly(e);
    if (!f) return null;
    if (f.muted) li.classList.add("muted");
    li.append(document.createTextNode(f.text));
    detail = f.detail;
  }
  if (detail) {
    const d = document.createElement("span");
    d.className = "detail";
    d.textContent = detail;
    li.append(d);
  }
  if (e.stage === "partial" && typeof e.data?.ifc_url === "string") {
    const url = e.data.ifc_url;
    const label = `preview ${e.data.preview} · ${e.data.elements} elements`;
    li.onclick = () => {
      if (!busy) previewChain = previewChain.then(() => showPreview({ url, label, row: li }));
    };
  }
  return li;
}

function appendRow(e: api.StageEvent): HTMLLIElement | null {
  const li = makeRow(e);
  if (!li) return null;
  rowsByEvent.set(e, li);
  stepsList.append(li);
  li.scrollIntoView({ block: "nearest" });
  return li;
}

function renderAll() {
  stepsList.replaceChildren();
  rowsByEvent.clear();
  streamRow = null;
  for (const e of events) {
    if (e.stage === "stream") {
      if (!verbose) continue;
      if (streamRow) streamRow.remove();
      streamRow = appendRow(e);
      continue;
    }
    appendRow(e);
  }
  stepsList.classList.toggle("friendly", !verbose);
}

function resetSteps() {
  events = [];
  stepsList.replaceChildren();
  rowsByEvent.clear();
  stepsText.textContent = "";
  streamRow = shownRow = null;
  stepsList.classList.toggle("friendly", !verbose);
}

stepsJson.onchange = () => (stepsText.hidden = !stepsJson.checked);
stepsVerbose.onchange = () => {
  verbose = stepsVerbose.checked;
  localStorage.setItem("nocoast.verbose", verbose ? "1" : "0");
  renderAll();
};
stepsList.classList.toggle("friendly", !verbose);

// --- previews --------------------------------------------------------------------------------------
// The backend emits `partial` events with a geometry-checked IFC of what the model has produced so far.
// Loads are serialised, only the newest pending preview is loaded, and nothing is loaded once the
// final version has arrived (unless the user clicks a preview row afterwards).
let previewChain = Promise.resolve();
let pendingPreview: { url: string; label: string; row: HTMLLIElement | null } | null = null;
let finalArrived = false;

function queuePreview(p: { url: string; label: string; row: HTMLLIElement | null }) {
  pendingPreview = p;
  previewChain = previewChain.then(async () => {
    const q = pendingPreview;
    if (!q || finalArrived) return;
    pendingPreview = null;
    await showPreview(q);
  });
}

async function showPreview(p: { url: string; label: string; row: HTMLLIElement | null }) {
  try {
    const bytes = await api.fetchIfc(p.url);
    if (finalArrived && busy) return;
    await loadIntoViewer(bytes);
    shownRow?.classList.remove("shown");
    shownRow = p.row;
    p.row?.classList.add("shown");
    setShowing(p.label, true);
    log("preview shown", p.url);
  } catch (err) {
    log("preview skipped:", String(err));
  }
}

const onEvent = (e: api.StageEvent) => {
  const errs = (e.data?.errors as string[] | undefined) ?? [];
  if (e.stage === "stream") {
    // Keep only the latest stream event of a round in the log (they update one row).
    if (events.length && events[events.length - 1].stage === "stream") events.pop();
    events.push(e);
    stepsText.textContent = String(e.data?.text ?? "");
    stepsText.scrollTop = stepsText.scrollHeight;
    if (verbose) {
      if (streamRow) streamRow.remove();
      streamRow = appendRow(e);
    }
    status.textContent = e.message.startsWith("waiting") ? e.message : `streaming: ${e.message}`;
    return;
  }
  events.push(e);
  streamRow = null;
  if (e.stage === "step" && e.data?.ok !== false && e.data?.step) {
    learnStep(e.data.step as Record<string, unknown>);
    applyFollow();
  }
  if (e.stage === "done") {
    followLevel = null;
    applyFollow();
  }
  const row = appendRow(e);
  if (e.stage === "partial" && typeof e.data?.ifc_url === "string") {
    queuePreview({ url: e.data.ifc_url, label: `preview ${e.data.preview} · ${e.data.elements} elements`, row });
  }
  const f = verbose ? null : friendly(e);
  setStatus(f ? f.text : `${e.stage}: ${e.message}${errs.length ? " — " + errs.join("; ") : ""}`, e.stage === "error");
};

async function run(work: () => Promise<api.Version>) {
  if (busy) return;
  setBusy(true);
  finalArrived = false;
  following = followBuild.checked;
  followLevel = null;
  resetSteps();
  try {
    const version = await work();
    finalArrived = true;
    await previewChain; // let an in-flight preview finish before the final model replaces it
    await showVersion(version);
    setStatus(`v${head!.number} loaded`);
  } catch (err) {
    finalArrived = true;
    console.error("[nocoast] request failed:", err);
    setStatus(String(err instanceof Error ? err.message : err), true);
    setBusy(false);
  }
}

send.onclick = () => {
  const prompt = text.value.trim();
  if (!prompt) return;
  run(() => api.sendPrompt(projectId, prompt, head?.number ?? null, onEvent, focus?.id ?? null)).then(() => (text.value = ""));
};
text.onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send.click();
  }
};
undo.onclick = () => head && run(() => api.revert(projectId, head!.number - 1, onEvent));
$<HTMLInputElement>("import").onchange = (e) => {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (file) run(() => api.importIfc(projectId, file, onEvent));
};
$<HTMLButtonElement>("new").onclick = () => openProject(null);

async function openProject(id: string | null) {
  if (!id) {
    id = (await api.createProject("Untitled")).id;
    localStorage.setItem("nocoast.project", id);
    log("created project", id);
  }
  projectId = id;
  framed = false; // a different project gets framed afresh
  const p = await api.getProject(id);
  log("opened project", id, "versions:", p.versions.length, "head:", p.head?.number ?? null);
  await showVersion(p.head);
}

async function boot() {
  setStatus("connecting to backend…");
  for (let attempt = 0; ; attempt++) {
    try {
      const h = await api.health();
      log("health:", h);
      setStatus(`backend ok · llm: ${h.llm.provider}${h.llm.model ? " " + h.llm.model : ""}`);
      break;
    } catch (err) {
      if (attempt % 10 === 0) log("backend not reachable yet:", String(err));
      if (attempt > 40) return setStatus(`backend not reachable at ${api.BACKEND} — start it with: cd backend && python main.py`, true);
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  const params = new URLSearchParams(location.search);
  try {
    // ?project=<id> deep-links a project (also how the headless smoke test opens one).
    await openProject(params.get("project") ?? localStorage.getItem("nocoast.project"));
  } catch (err) {
    log("stored project could not be opened, creating a new one:", String(err));
    await openProject(null); // stale id from an older database
  }
  const auto = params.get("prompt"); // ?prompt=… sends a prompt on load (smoke tests, demos)
  if (auto) {
    text.value = auto;
    send.click();
  }
}

boot();
