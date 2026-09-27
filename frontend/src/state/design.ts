// The design record behind a version (backend `schemas/design.py`, served by GET …/versions/{n}/spec), and
// how the viewer explains a clicked element in design terms: "west wall of the Kitchen", "Door between
// the Hall and the Kitchen", the room under a clicked floor. Spec element ids are what the IFC carries in
// Tag (spaces: Name), so a pick in the viewer maps straight back to the design.

export type Pt = [number, number];
export interface Edge { to: Pt; through?: Pt | null; open?: boolean }

export interface Design {
  name: string;
  levels: { id: string; name: string | null; height: number; below_ground: boolean }[];
  rooms: { id: string; name: string; level: string; kind: string; rect: [number, number, number, number] | null; poly: Edge[] | null; area: number | null; roofed?: boolean | null; enclosed?: boolean | null }[];
  doors: { id: string; room: string; to: string; side: string | null; at: number; kind: string; width: number; height: number }[];
  windows: { id: string; room: string; side: string; at: number; kind: string; width: number; height: number; sill: number | null }[];
  stairs: { id: string; room: string; side: string; to_level: string | null; width: number }[];
  fixtures: { id: string; room: string; kind: string; side: string; at: number; rotation: number | null; width: number | null; depth: number | null; height: number | null }[];
  balconies: { id: string; room: string; side: string; depth: number }[];
  columns: { id: string; level: string; x: number; y: number }[];
  elements?: { id: string; kind: string; level: string; name: string | null; height: number | null; thickness: number | null; width: number | null; depth: number | null; elevation: number }[];
  porch: { side: string; depth: number } | null;
  roof: { kind: string; pitch: number; overhang: number };
  wall_material: string | null;
}

export interface Facts { title: string; rows: [string, string][]; roomId?: string }

const SIDE_NAMES: Record<string, string> = { N: "north", S: "south", E: "east", W: "west" };
const sideName = (s: string | null | undefined) => (s ? SIDE_NAMES[s] ?? s : "");
const kindName = (k: unknown) => String(k ?? "").replace(/_/g, " ");
const cap = (s: string) => s.replace(/^\w/, (c) => c.toUpperCase());

export function levelName(id: unknown): string {
  if (typeof id !== "string") return "the ground floor";
  if (/^B\d+$/i.test(id)) {
    const b = Number(id.slice(1));
    return b === 1 ? "the basement" : `basement level ${b}`;
  }
  const n = Number(id.replace(/^L/i, ""));
  return n === 1 ? "the ground floor" : n === 2 ? "the first floor" : `level ${n}`;
}

/** Design-level facts about a spec element id, or null when the id is not one the design knows. */
export function describeElement(design: Design | null, id: string): Facts | null {
  if (!design) return null;
  const roomLabel = (rid: string) => { const r = design.rooms.find((x) => x.id === rid); return r ? `the ${r.name}` : `the ${rid}`; };
  const levelLabel = (lid: string) => design.levels.find((x) => x.id === lid)?.name ?? levelName(lid).replace(/^the /, "");
  const size = (w: number | null | undefined, h: number | null | undefined) => (w && h ? [["size", `${w} × ${h} m`]] as [string, string][] : []);

  let m = id.match(/^(\w+?)-wall-([\w-]+)\+([\w-]+)$/);
  if (m) return { title: `Wall between ${roomLabel(m[2])} and ${roomLabel(m[3])}`, rows: [["level", levelLabel(m[1])], ["type", "partition wall, 0.12 m"], ["rooms", `${roomLabel(m[2])}, ${roomLabel(m[3])}`]] };
  m = id.match(/^(\w+?)-wall-([\w-]+)-([NSEW])$/);
  if (m) return { title: `${sideName(m[3])} wall of ${roomLabel(m[2])}`, rows: [["level", levelLabel(m[1])], ["type", `exterior wall, 0.3 m${design.wall_material ? `, ${design.wall_material}` : ""}`], ["room", roomLabel(m[2])], ["side", sideName(m[3])]], roomId: m[2] };
  m = id.match(/^(\w+?)-wall-([\w-]+?)-(\w+)$/);
  if (m && design.rooms.some((r) => r.id === m![2])) return { title: `Wall of ${roomLabel(m[2])}`, rows: [["level", levelLabel(m[1])], ["room", roomLabel(m[2])], ["edge", m[3]]], roomId: m[2] };

  m = id.match(/^(\w+?)-space-([\w-]+)$/);
  const room = m ? design.rooms.find((r) => r.id === m![2]) : design.rooms.find((r) => r.id === id);
  if (room) {
    const rect = room.rect;
    const rows: [string, string][] = [["level", levelLabel(room.level)], ["kind", kindName(room.kind)]];
    if (rect) rows.push(["size", `${rect[2]} × ${rect[3]} m (${(rect[2] * rect[3]).toFixed(1)} m²)`], ["position", `x ${rect[0]}, y ${rect[1]}`]);
    else if (room.poly) rows.push(["outline", `${room.poly.length} edges${room.area ? ` · ${room.area.toFixed(1)} m²` : ""}`]);
    if (room.roofed === false) rows.push(["roof", "open to the sky"]);
    if (room.enclosed === false) rows.push(["walls", "none — columns carry the roof"]);
    rows.push(
      ["doors", design.doors.filter((d) => d.room === room.id || d.to === room.id).map((d) => (d.to === "outside" ? "entrance" : d.room === room.id ? roomLabel(d.to) : roomLabel(d.room))).join(", ") || "none"],
      ["windows", String(design.windows.filter((w) => w.room === room.id).length)],
      ["furniture", design.fixtures.filter((f) => f.room === room.id).map((f) => kindName(f.kind)).join(", ") || "none"],
    );
    return { title: room.name, rows, roomId: room.id };
  }

  m = id.match(/^(\w+?)-(floor|slab)(-\d+)?$/);
  if (m) return { title: `Floor slab of ${levelLabel(m[1])}`, rows: [["level", levelLabel(m[1])]] };
  if (id === "roof" || id.endsWith("-roof")) {
    return { title: id.startsWith("porch") ? "Porch roof" : "Roof", rows: [["kind", design.roof.kind], ...(design.roof.kind !== "flat" ? [["pitch", `${design.roof.pitch}°`]] as [string, string][] : []), ["overhang", `${design.roof.overhang} m`]] };
  }
  const door = design.doors.find((d) => d.id === id);
  if (door) {
    return { title: door.to === "outside" ? `Entrance door of ${roomLabel(door.room)}` : `Door between ${roomLabel(door.room)} and ${roomLabel(door.to)}`,
      rows: [["kind", kindName(door.kind)], ...size(door.width, door.height), ...(door.side ? [["side", sideName(door.side)]] as [string, string][] : []), ["position", `${Math.round(door.at * 100)}% along the wall`]], roomId: door.room };
  }
  const win = design.windows.find((w) => w.id === id);
  if (win) {
    return { title: `Window on the ${sideName(win.side)} wall of ${roomLabel(win.room)}`,
      rows: [["kind", kindName(win.kind)], ...size(win.width, win.height), ...(win.sill !== null ? [["sill", `${win.sill} m`]] as [string, string][] : []), ["position", `${Math.round(win.at * 100)}% along the wall`]], roomId: win.room };
  }
  const stair = design.stairs.find((s) => s.id === id);
  if (stair) return { title: `Stair in ${roomLabel(stair.room)}`, rows: [["along", `${sideName(stair.side)} wall`], ["width", `${stair.width} m`], ["to", stair.to_level ? levelLabel(stair.to_level) : "the level above"]], roomId: stair.room };
  const fx = design.fixtures.find((f) => f.id === id);
  if (fx) {
    return { title: cap(`${kindName(fx.kind)} in ${roomLabel(fx.room)}`),
      rows: [["kind", kindName(fx.kind)], ["placement", fx.side === "center" ? "middle of the room" : `against the ${sideName(fx.side)} wall`], ...(fx.width && fx.depth ? [["size", `${fx.width} × ${fx.depth}${fx.height ? ` × ${fx.height}` : ""} m`]] as [string, string][] : [])], roomId: fx.room };
  }
  const bal = design.balconies.find((b) => b.id === id || `${b.id}-railing` === id);
  if (bal) return { title: id.endsWith("-railing") ? `Railing of the balcony of ${roomLabel(bal.room)}` : `Balcony of ${roomLabel(bal.room)}`, rows: [["side", sideName(bal.side)], ["depth", `${bal.depth} m`]], roomId: bal.room };
  if (id.startsWith("porch")) return { title: id.startsWith("porch-col") ? "Porch column" : "Porch", rows: design.porch ? [["side", sideName(design.porch.side)], ["depth", `${design.porch.depth} m`]] : [] };
  const col = design.columns.find((c) => c.id === id);
  if (col) return { title: "Column", rows: [["level", levelLabel(col.level)], ["position", `x ${col.x}, y ${col.y}`]] };
  const free = design.elements?.find((e) => e.id === id);
  if (free) {
    const rows: [string, string][] = [["level", levelLabel(free.level)], ["kind", `free-standing ${kindName(free.kind)}`]];
    if (free.elevation) rows.push(["elevation", `${free.elevation} m above the level`]);
    if (free.height) rows.push(["height", `${free.height} m`]);
    if (free.thickness) rows.push(["thickness", `${free.thickness} m`]);
    if (free.width) rows.push(["width", `${free.width} m`]);
    if (free.depth) rows.push(["depth", `${free.depth} m`]);
    return { title: free.name ?? cap(kindName(free.kind)), rows };
  }
  return null;
}

/** The room on `level` whose outline contains plan point (x, y), or null. */
export function roomAt(design: Design | null, level: string, x: number, y: number) {
  if (!design) return null;
  for (const r of design.rooms) {
    if (r.level !== level) continue;
    if (r.rect) {
      const [rx, ry, w, d] = r.rect;
      if (x >= rx && x <= rx + w && y >= ry && y <= ry + d) return r;
    } else if (r.poly && inPolygon(r.poly.map((e) => e.to), x, y)) return r;
  }
  return null;
}

function inPolygon(pts: Pt[], x: number, y: number) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
