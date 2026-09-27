"""The drawing set: the sheets an architect would issue for a design review, drawn from the model.

`drawing_set()` turns a `BuildingSpec` (and its review, see core/review.py) into numbered ARCH-D-ish
A3 sheets following US National CAD Standard numbering:

    G-001  cover: axonometric, project data, code summary, drawing index
    A-101… floor plans, one per storey: poché walls, door swings, glazing, stairs, furniture, room
           tags with number and area, structural grid, dimension strings, section mark, north arrow
    A-201  the four elevations with level datums
    A-301  building section A-A through the stair
    A-601… room, door and window schedules and the area summary

Every sheet carries the same title block. Geometry is read straight from the spec, so the drawings
always match the IFC.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import substring, unary_union

from core.draw.canvas import Canvas, text_width
from schemas.bim import (Asset, BuildingSpec, Column, CustomFixture, Door, Fixture, Railing, Roof, Slab, Space,
                         Stair, Wall, Window)

W, H = 420.0, 297.0
M = 10.0                       # border
TB = 78.0                      # title block strip width
AREA = (M + 6, M + 6, W - M - TB - 6, H - M - 22)   # drawing area x0, y0, x1, y1 (leaves room for the title)
SCALES = (20, 50, 100, 125, 200, 250, 500, 1000, 2000)
INK, POCHE, THIN, FAINT = "#1b1b1b", "#262626", "#6b6b6b", "#b4b4b4"
ACCENT = "#c2410c"

TINTS = {
    "living": "#f6eedb", "dining": "#f6eedb", "bedroom": "#e4edf8", "kitchen": "#e2f1ec", "bathroom": "#dcefef",
    "utility": "#e2f1ec", "hall": "#f1f1ef", "office": "#ebe8f6", "meeting": "#ebe8f6", "reception": "#ebe8f6",
    "classroom": "#ebe8f6", "lab": "#ebe8f6", "clinic": "#e9f2fb", "ward": "#e9f2fb", "retail": "#f8e6e1",
    "cafe": "#f8e6e1", "gym": "#f8e6e1", "auditorium": "#f8e6e1", "courtyard": "#e5f1dc", "terrace": "#e5f1dc",
    "carport": "#eeeeee", "pergola": "#e5f1dc", "garage": "#ececec", "workshop": "#ececec", "warehouse": "#ececec",
    "plant": "#e8e8e8", "server": "#e8e8e8", "storage": "#ececec", "parking": "#ececec", "barn": "#efe9dd",
    "stable": "#efe9dd",
}
LEGEND = [("Living", "#f6eedb"), ("Sleeping", "#e4edf8"), ("Wet / service", "#e2f1ec"), ("Work / learn", "#ebe8f6"),
          ("Public / assembly", "#f8e6e1"), ("Circulation", "#f1f1ef"), ("Support", "#ececec"), ("External", "#e5f1dc")]
FACADE = {"brick": "#d8b39b", "masonry": "#ece7dd", "render": "#f0ece4", "concrete": "#d8d8d6", "timber": "#dcc59f",
          "glass": "#cfe1ea", "steel": "#c7ccd1", "stone": "#dfd6c3", "plaster": "#efefed", None: "#ece7dd"}


@dataclass
class Meta:
    project: str
    project_id: str = ""
    version: int = 1
    description: str = ""
    brief: str = ""
    author: str = "NoCoast agent"
    created: float = 0.0
    status: str = "PRELIMINARY — NOT FOR CONSTRUCTION"

    @property
    def date(self) -> str:
        ts = self.created or datetime.now(timezone.utc).timestamp()
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Sheet:
    number: str
    title: str
    kind: str
    canvas: Canvas
    scale: str = ""
    index: list = field(default_factory=list)

    def svg(self) -> str:
        return self.canvas.svg()


# --- helpers -------------------------------------------------------------

def mm(v: float) -> str:
    return f"{v * 1000:,.0f}"


def wrap(s: str, width: float, size: float, bold: bool = False) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        trial = f"{cur} {word}".strip()
        if text_width(trial, size, bold) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


class View:
    """World metres (x east, y north) to sheet millimetres (y down) at a drawing scale."""

    def __init__(self, x0: float, y0: float, scale: int, ox: float, oy: float):
        self.x0, self.y0, self.k, self.ox, self.oy = x0, y0, 1000.0 / scale, ox, oy
        self.scale = scale

    def __call__(self, p) -> tuple[float, float]:
        return (self.ox + (p[0] - self.x0) * self.k, self.oy - (p[1] - self.y0) * self.k)

    def pts(self, pts) -> list[tuple[float, float]]:
        return [self(p) for p in pts]


def pick_scale(w: float, h: float, room_w: float, room_h: float, pad: float = 0.0) -> int:
    for s in SCALES:
        if w * 1000 / s + pad <= room_w and h * 1000 / s + pad <= room_h:
            return s
    return SCALES[-1]


def level_of(el) -> str | None:
    return getattr(el, "level", None)


def extent(spec: BuildingSpec, level: str | None = None) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for el in spec.elements:
        if level is not None and level_of(el) != level:
            continue
        pts = []
        if isinstance(el, Wall):
            pts = el.axis
        elif isinstance(el, (Slab, Roof, Space)):
            pts = el.outline
        elif isinstance(el, (Fixture, Column, CustomFixture, Stair)):
            pts = [el.position]
        elif isinstance(el, Asset):
            pts = [el.position]
        elif isinstance(el, Railing):
            pts = el.path
        for p in pts:
            xs.append(p[0])
            ys.append(p[1])
    if not xs:
        return (0.0, 0.0, 10.0, 10.0)
    return (min(xs), min(ys), max(xs), max(ys))


def spaces_union(spec: BuildingSpec, level: str):
    polys = [Polygon(e.outline).buffer(0.1, join_style="mitre") for e in spec.elements
             if isinstance(e, Space) and e.level == level and len(e.outline) >= 3]
    return unary_union(polys) if polys else None


def outward(wall: Wall, inside) -> tuple[float, float]:
    """Unit normal of a straight wall pointing away from the storey's rooms."""
    (ax, ay), (bx, by) = wall.axis[0], wall.axis[-1]
    L = math.hypot(bx - ax, by - ay) or 1.0
    nx, ny = -(by - ay) / L, (bx - ax) / L
    mx, my = (ax + bx) / 2, (ay + by) / 2
    probe = max(0.35, wall.thickness)
    if inside is not None and inside.contains(Point(mx + nx * probe, my + ny * probe)):
        return (-nx, -ny)
    return (nx, ny)


def roof_height(roof: Roof, x: float, y: float) -> float:
    xs, ys = [p[0] for p in roof.outline], [p[1] for p in roof.outline]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    w, d = x1 - x0, y1 - y0
    t = math.tan(math.radians(roof.pitch))
    ridge = roof.ridge or ("x" if w >= d else "y")
    x, y = min(max(x, x0), x1), min(max(y, y0), y1)
    if roof.shape == "gable":
        return t * (d / 2 - abs(y - (y0 + y1) / 2)) if ridge == "x" else t * (w / 2 - abs(x - (x0 + x1) / 2))
    if roof.shape == "shed":
        return t * (y - y0) if ridge == "x" else t * (x - x0)
    if roof.shape == "hip":
        return t * min(x - x0, x1 - x, y - y0, y1 - y, min(w, d) / 2)
    return 0.0


# --- the title block -----------------------------------------------------

def frame(c: Canvas, meta: Meta, number: str, title: str, scale: str) -> None:
    c.rect(M, M, W - 2 * M, H - 2 * M, None, INK, 0.5)
    x0 = W - M - TB
    c.line((x0, M), (x0, H - M), 0.5, INK)
    x, r = x0 + 4, W - M - 4
    y = M + 9
    c.text((x, y), "NOCOAST", 6.2, True)
    c.text((x + text_width("NOCOAST", 6.2, True) + 1.2, y), "AEC", 6.2, False, color=ACCENT)
    c.text((x, y + 4.5), "Computational architecture studio", 2.2, color=THIN)
    y += 9
    c.line((x0, y), (W - M, y), 0.25, INK)
    y += 5
    c.text((x, y), "GENERAL NOTES", 2.3, True)
    notes = ["All dimensions in millimetres unless noted. Do not scale from this drawing.",
             "Drawn directly from the IFC model of this version; the model governs.",
             "Code review is an indicative design-stage screen (IBC / IRC 2021, ADA 2010), not a permit review.",
             "Verify all dimensions and conditions on site before fabrication."]
    for i, n in enumerate(notes, 1):
        for j, line in enumerate(wrap(n, TB - 13, 1.9)):
            y += 2.8
            c.text((x + (0 if j else 0), y), f"{i}." if j == 0 else "", 1.9)
            c.text((x + 4, y), line, 1.9, color="#333")
        y += 0.8
    y += 4
    c.rect(x, y, TB - 8, 12, "#fff7ed", ACCENT, 0.4)
    status = meta.status.split("—")
    c.text((x0 + TB / 2, y + 5), status[0].strip(), 2.6, True, "middle", ACCENT)
    if len(status) > 1:
        c.text((x0 + TB / 2, y + 9.2), status[1].strip(), 2.1, True, "middle", ACCENT)
    y += 17
    c.line((x0, y), (W - M, y), 0.25, INK)
    y += 4.5
    c.text((x, y), "REV", 1.9, True)
    c.text((x + 9, y), "DESCRIPTION", 1.9, True)
    c.text((r, y), "DATE", 1.9, True, "end")
    y += 1.5
    c.line((x, y), (r, y), 0.13, THIN)
    for n in range(max(1, meta.version - 2), meta.version + 1):
        y += 3.6
        c.text((x, y), f"{n:02d}", 1.9)
        c.text((x + 9, y), "Issued for design review" if n == meta.version else f"Design iteration {n}", 1.9)
        c.text((r, y), meta.date if n == meta.version else "—", 1.9, anchor="end")
    y = H - M - 92
    c.line((x0, y), (W - M, y), 0.25, INK)
    y += 5
    c.text((x, y), "PROJECT", 1.8, True, color=THIN)
    for line in wrap(meta.project.upper(), TB - 8, 3.4, True)[:2]:
        y += 4.4
        c.text((x, y), line, 3.4, True)
    for line in wrap(meta.description, TB - 8, 2.1)[:2]:
        y += 3.2
        c.text((x, y), line, 2.1, color="#333")
    y = H - M - 62
    c.line((x0, y), (W - M, y), 0.25, INK)
    y += 5
    c.text((x, y), "DRAWING", 1.8, True, color=THIN)
    for line in wrap(title.upper(), TB - 8, 3.6, True)[:2]:
        y += 4.8
        c.text((x, y), line, 3.6, True)
    y = H - M - 38
    c.line((x0, y), (W - M, y), 0.25, INK)
    cells = [("SCALE", scale or "AS NOTED"), ("DATE", meta.date), ("DRAWN", meta.author), ("CHECKED", "—"),
             ("PROJECT NO.", meta.project_id or "—"), ("MODEL", f"v{meta.version} · IFC4")]
    for i, (k, v) in enumerate(cells):
        cx, cy = x + (i % 2) * (TB / 2 - 2), y + 4.5 + (i // 2) * 7
        c.text((cx, cy), k, 1.6, True, color=THIN)
        c.text((cx, cy + 3.2), v if text_width(v, 2.1) < TB / 2 - 6 else v[:int(len(v) * (TB / 2 - 6) / text_width(v, 2.1))], 2.1)
    y = H - M - 16
    c.line((x0, y), (W - M, y), 0.25, INK)
    c.text((x, y + 5), "SHEET", 1.8, True, color=THIN)
    c.text((r, y + 12.5), number, 9.5, True, "end")


def drawing_title(c: Canvas, x: float, y: float, n: int, title: str, scale: str, width: float = 70) -> None:
    c.circle((x + 4, y), 4, None, INK, 0.35)
    c.line((x, y), (x + 8, y), 0.2, INK)
    c.text((x + 4, y - 0.9), str(n), 2.4, True, "middle")
    c.line((x + 10, y + 0.6), (x + 10 + width, y + 0.6), 0.5, INK)
    c.text((x + 10, y - 1.2), title.upper(), 3.2, True)
    c.text((x + 10, y + 4), scale, 2.1, color=THIN)


def north_arrow(c: Canvas, x: float, y: float) -> None:
    c.circle((x, y), 5.5, None, INK, 0.25)
    c.polygon([(x, y - 7.5), (x + 2.6, y + 3.5), (x, y + 1.8)], INK, INK, 0.1)
    c.polygon([(x, y - 7.5), (x - 2.6, y + 3.5), (x, y + 1.8)], "#fff", INK, 0.2)
    c.text((x, y - 9), "N", 2.8, True, "middle")


def scale_bar(c: Canvas, x: float, y: float, scale: int) -> None:
    step = next(s for s in (0.5, 1, 2, 5, 10, 20, 50) if s * 1000 / scale >= 6)
    k = 1000 / scale
    for i in range(5):
        c.rect(x + i * step * k, y, step * k, 1.6, INK if i % 2 == 0 else "#fff", INK, 0.2)
        c.text((x + i * step * k, y + 4.6), f"{step * i:g}", 1.8, anchor="middle")
    c.text((x + 5 * step * k, y + 4.6), f"{step * 5:g} m", 1.8, anchor="middle")


# --- plans -----------------------------------------------------------------

def _pieces(wall: Wall, cuts: list[tuple[float, float]]) -> list:
    axis = list(wall.axis)
    t = wall.thickness
    (ax, ay), (bx, by) = axis[0], axis[1]
    L0 = math.hypot(bx - ax, by - ay) or 1
    (cx, cy), (dx, dy) = axis[-2], axis[-1]
    L1 = math.hypot(dx - cx, dy - cy) or 1
    ext = [(ax - (bx - ax) / L0 * t / 2, ay - (by - ay) / L0 * t / 2), *axis[1:-1],
           (dx + (dx - cx) / L1 * t / 2, dy + (dy - cy) / L1 * t / 2)]
    line = LineString(ext)
    total = line.length
    cuts = sorted((a + t / 2, b + t / 2) for a, b in cuts)
    out, pos = [], 0.0
    for a, b in cuts + [(total, total)]:
        if a - pos > 0.01:
            seg = substring(line, pos, a)
            if seg.length > 0.01:
                out.append(seg.buffer(t / 2, cap_style="flat", join_style="mitre"))
        pos = max(pos, b)
    return out


def _openings(spec: BuildingSpec) -> dict[str, list]:
    by_wall: dict[str, list] = {}
    for el in spec.elements:
        if isinstance(el, (Door, Window)):
            by_wall.setdefault(el.wall, []).append(el)
    return by_wall


def marks(spec: BuildingSpec) -> dict[str, str]:
    out, d, w = {}, 0, 0
    levels = [l.id for l in spec.levels]
    walls = {e.id: e for e in spec.elements if isinstance(e, Wall)}
    items = [e for e in spec.elements if isinstance(e, (Door, Window))]
    items.sort(key=lambda e: (levels.index(walls[e.wall].level) if e.wall in walls and walls[e.wall].level in levels else 0))
    for e in items:
        wall = walls.get(e.wall)
        lvl = (levels.index(wall.level) + 1) if wall and wall.level in levels else 1
        if isinstance(e, Door):
            d += 1
            out[e.id] = f"D{lvl}{d:02d}"
        else:
            w += 1
            out[e.id] = f"W{lvl}{w:02d}"
    return out


def _grid(values: list[float], tol: float = 0.4) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _dims(c: Canvas, v: View, a: float, b: float, at: float, chain: list[float], horizontal: bool) -> None:
    """A chained dimension string between world coordinates in `chain`, drawn `at` mm off the drawing."""
    pts = sorted(chain)
    for i, x in enumerate(pts):
        if horizontal:
            sx, _ = v((x, 0))
            c.line((sx, at - 1.5), (sx, at + 1.5), 0.13, INK)
            c.line((sx - 0.9, at + 0.9), (sx + 0.9, at - 0.9), 0.35, INK)
        else:
            _, sy = v((0, x))
            c.line((at - 1.5, sy), (at + 1.5, sy), 0.13, INK)
            c.line((at - 0.9, sy + 0.9), (at + 0.9, sy - 0.9), 0.35, INK)
        if i:
            p = pts[i - 1]
            label = mm(x - p)
            if horizontal:
                s0, s1 = v((p, 0))[0], v((x, 0))[0]
                c.line((s0, at), (s1, at), 0.13, INK)
                if s1 - s0 > text_width(label, 1.9) + 1:
                    c.text(((s0 + s1) / 2, at - 1.1), label, 1.9, anchor="middle")
            else:
                s0, s1 = v((0, p))[1], v((0, x))[1]
                c.line((at, s0), (at, s1), 0.13, INK)
                if s0 - s1 > text_width(label, 1.9) + 1:
                    c.text((at - 1.1, (s0 + s1) / 2), label, 1.9, anchor="middle", angle=90)


def _fixture_outline(el) -> list[tuple[float, float]]:
    if isinstance(el, Fixture):
        hw, hd = el.width / 2, el.depth / 2
        corners = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    elif isinstance(el, CustomFixture):
        xs = [p.x for p in el.parts] + [p.x + p.w for p in el.parts]
        ys = [p.y for p in el.parts] + [p.y + (p.w if p.shape == "round" else p.d) for p in el.parts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        corners = [(x - cx, y - cy) for x, y in [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]]
    else:
        x0, y0, _, x1, y1, _ = el.bounds
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    a = math.radians(el.rotation)
    ca, sa = math.cos(a), math.sin(a)
    px, py = el.position
    return [(px + x * ca - y * sa, py + x * sa + y * ca) for x, y in corners]


def _stair_outline(s: Stair, rise: float):
    run = s.run(rise)
    a = math.radians(s.direction)
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    x0, y0 = s.position
    hw = s.width / 2
    return run, (ux, uy), (nx, ny), [(x0 + nx * hw, y0 + ny * hw), (x0 - nx * hw, y0 - ny * hw),
                                       (x0 - nx * hw + ux * run, y0 - ny * hw + uy * run),
                                       (x0 + nx * hw + ux * run, y0 + ny * hw + uy * run)]


def plan_sheet(spec: BuildingSpec, level_id: str, review: dict, meta: Meta, number: str, n: int,
               section: tuple[str, float] | None) -> Sheet:
    level = next(l for l in spec.levels if l.id == level_id)
    c = Canvas(W, H)
    x0, y0, x1, y1 = extent(spec)
    ax0, ay0, ax1, ay1 = AREA
    pad = 34.0
    scale = pick_scale(x1 - x0, y1 - y0, ax1 - ax0 - pad, ay1 - ay0 - pad - 10)
    k = 1000 / scale
    ox = ax0 + 22 + ((ax1 - ax0 - pad) - (x1 - x0) * k) / 2
    oy = ay0 + 16 + ((ay1 - ay0 - pad - 10) - (y1 - y0) * k) / 2 + (y1 - y0) * k
    v = View(x0, y0, scale, ox, oy)
    rooms = {r["id"]: r for r in review.get("rooms", [])}
    tag = marks(spec)
    els = [e for e in spec.elements if level_of(e) == level_id]
    walls = [e for e in els if isinstance(e, Wall)]
    inside = spaces_union(spec, level_id)
    by_wall = _openings(spec)

    # slab edge and room fills
    for e in els:
        if isinstance(e, Slab):
            c.polygon(v.pts(e.outline), "#fbfbfa", FAINT, 0.18)
    for e in els:
        if isinstance(e, Space):
            kind = rooms.get(e.id, {}).get("kind", "other")
            c.polygon(v.pts(e.outline), TINTS.get(kind, "#f3f3f1"), None)
    # below: the level under this one, ghosted, where this one oversails or steps back
    # structural grid
    ext_walls = [w for w in spec.elements if isinstance(w, Wall) and w.external]
    gx = _grid([p[0] for w in ext_walls for p in w.axis if abs(w.axis[0][0] - w.axis[-1][0]) < 0.01])[:12]
    gy = _grid([p[1] for w in ext_walls for p in w.axis if abs(w.axis[0][1] - w.axis[-1][1]) < 0.01])[:12]
    top_y, left_x = v((0, y1))[1] - 12, v((x0, 0))[0] - 30
    bot_y, right_x = v((0, y0))[1] + 6, v((x1, 0))[0] + 6
    for i, gxv in enumerate(gx):
        sx = v((gxv, 0))[0]
        c.line((sx, top_y + 3.2), (sx, bot_y), 0.13, FAINT, (4, 1, 0.6, 1))
        c.circle((sx, top_y), 3.2, "#fff", INK, 0.25)
        c.text((sx, top_y + 1.0), str(i + 1), 2.6, True, "middle")
    for i, gyv in enumerate(reversed(gy)):
        sy = v((0, gyv))[1]
        c.line((left_x + 3.2, sy), (right_x, sy), 0.13, FAINT, (4, 1, 0.6, 1))
        c.circle((left_x, sy), 3.2, "#fff", INK, 0.25)
        c.text((left_x, sy + 1.0), chr(ord("A") + i), 2.6, True, "middle")

    # fixtures, assets, columns, railings
    for e in els:
        if isinstance(e, (Fixture, CustomFixture)):
            c.polygon(v.pts(_fixture_outline(e)), "#ffffff", THIN, 0.13)
            if isinstance(e, Fixture) and e.kind in ("toilet", "washbasin", "sink"):
                px, py = v(e.position)
                c.circle((px, py), min(e.width, e.depth) * k * 0.3, None, THIN, 0.13)
        elif isinstance(e, Asset) and e.ifc_class not in ("IfcWall", "IfcSlab", "IfcBeam", "IfcColumn"):
            c.polygon(v.pts(_fixture_outline(e)), None, THIN, 0.13, (1.2, 0.8))
        elif isinstance(e, Column):
            hw, hd = e.width / 2, e.depth / 2
            px, py = e.position
            c.polygon(v.pts([(px - hw, py - hd), (px + hw, py - hd), (px + hw, py + hd), (px - hw, py + hd)]), POCHE, POCHE, 0.1)
        elif isinstance(e, Railing):
            c.polyline(v.pts(e.path), 0.35, INK)

    # stairs (and the flight arriving from below)
    for s in spec.elements:
        if not isinstance(s, Stair) or level_id not in (s.level, s.to_level):
            continue
        rise = s.rise or next(l for l in spec.levels if l.id == s.level).height
        run, (ux, uy), (nx, ny), outline = _stair_outline(s, rise)
        here = s.level == level_id
        c.polygon(v.pts(outline), "#ffffff", INK, 0.25, None if here else (1.5, 1))
        steps = s.steps(rise)
        for i in range(1, steps):
            px, py = s.position[0] + ux * s.going * i, s.position[1] + uy * s.going * i
            c.line(v((px + nx * s.width / 2, py + ny * s.width / 2)), v((px - nx * s.width / 2, py - ny * s.width / 2)),
                   0.13, INK if here else FAINT)
        a, b = v(s.position), v((s.position[0] + ux * (run - 0.15), s.position[1] + uy * (run - 0.15)))
        c.line(a, b, 0.18, INK)
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        c.polygon([b, (b[0] - 2 * math.cos(ang - 0.4), b[1] - 2 * math.sin(ang - 0.4)),
                   (b[0] - 2 * math.cos(ang + 0.4), b[1] - 2 * math.sin(ang + 0.4))], INK)
        c.circle(a, 0.7, "#fff", INK, 0.18)
        label = f"UP {steps}R" if here else "DN"
        lx, ly = v((s.position[0] - ux * 0.35, s.position[1] - uy * 0.35))
        c.text((lx, ly + 1), label, 1.8, True, "middle")

    # walls: cut in poché, openings left open
    pieces = []
    for w in walls:
        cuts = [(o.offset, o.offset + o.width) for o in by_wall.get(w.id, [])]
        pieces += _pieces(w, cuts)
    if pieces:
        merged = unary_union(pieces)
        for poly in getattr(merged, "geoms", [merged]):
            if poly.is_empty or not isinstance(poly, Polygon):
                continue
            rings = [v.pts(list(poly.exterior.coords))] + [v.pts(list(r.coords)) for r in poly.interiors]
            c.shape(rings, POCHE, INK, 0.12)

    # openings
    for w in walls:
        if len(w.axis) != 2:
            continue
        (ax_, ay_), (bx_, by_) = w.axis
        L = w.length or 1
        ux, uy = (bx_ - ax_) / L, (by_ - ay_) / L
        nx, ny = -uy, ux
        out = outward(w, inside) if w.external else (nx, ny)
        t = w.thickness
        for o in by_wall.get(w.id, []):
            s0 = (ax_ + ux * o.offset, ay_ + uy * o.offset)
            s1 = (ax_ + ux * (o.offset + o.width), ay_ + uy * (o.offset + o.width))
            if isinstance(o, Window):
                for side in (-1, 1):
                    c.line(v((s0[0] + nx * t / 2 * side, s0[1] + ny * t / 2 * side)),
                           v((s1[0] + nx * t / 2 * side, s1[1] + ny * t / 2 * side)), 0.13, INK)
                c.line(v((s0[0] + nx * t * 0.12, s0[1] + ny * t * 0.12)), v((s1[0] + nx * t * 0.12, s1[1] + ny * t * 0.12)), 0.18, INK)
                c.line(v((s0[0] - nx * t * 0.12, s0[1] - ny * t * 0.12)), v((s1[0] - nx * t * 0.12, s1[1] - ny * t * 0.12)), 0.18, INK)
                for p in (s0, s1):
                    c.line(v((p[0] + nx * t / 2, p[1] + ny * t / 2)), v((p[0] - nx * t / 2, p[1] - ny * t / 2)), 0.18, INK)
                mid = ((s0[0] + s1[0]) / 2 + out[0] * (t / 2 + 0.45), (s0[1] + s1[1]) / 2 + out[1] * (t / 2 + 0.45))
                mx, my = v(mid)
                label = tag.get(o.id, "")
                tw = text_width(label, 1.5) + 1.6
                c.polygon([(mx - tw / 2, my - 1.4), (mx + tw / 2, my - 1.4), (mx + tw / 2 + 1, my), (mx + tw / 2, my + 1.4),
                           (mx - tw / 2, my + 1.4), (mx - tw / 2 - 1, my)], "#fff", INK, 0.13)
                c.text((mx, my + 0.55), label, 1.5, anchor="middle")
                continue
            # doors swing into the room side (for an exterior door: inwards)
            sw = (-out[0], -out[1]) if w.external else (nx, ny)
            if o.kind in ("garage", "roller"):
                c.line(v(s0), v(s1), 0.18, INK, (1.2, 0.8))
                c.line(v((s0[0] + sw[0] * 0.6, s0[1] + sw[1] * 0.6)), v((s1[0] + sw[0] * 0.6, s1[1] + sw[1] * 0.6)), 0.13, THIN, (1.2, 0.8))
            elif o.kind == "sliding":
                half = o.width / 2 + 0.05
                for j, off in ((0, t * 0.15), (1, -t * 0.15)):
                    a0 = o.offset + (0 if j == 0 else o.width - half)
                    c.polygon(v.pts([(ax_ + ux * a0 + nx * off, ay_ + uy * a0 + ny * off),
                                     (ax_ + ux * (a0 + half) + nx * off, ay_ + uy * (a0 + half) + ny * off),
                                     (ax_ + ux * (a0 + half) + nx * (off + 0.04), ay_ + uy * (a0 + half) + ny * (off + 0.04)),
                                     (ax_ + ux * a0 + nx * (off + 0.04), ay_ + uy * a0 + ny * (off + 0.04))]), "#fff", INK, 0.15)
            elif o.kind == "revolving":
                cx_, cy_ = (s0[0] + s1[0]) / 2, (s0[1] + s1[1]) / 2
                c.circle(v((cx_, cy_)), o.width / 2 * k, None, INK, 0.18)
                for ang in (0, math.pi / 2):
                    dx, dy = math.cos(ang) * o.width / 2, math.sin(ang) * o.width / 2
                    c.line(v((cx_ - dx, cy_ - dy)), v((cx_ + dx, cy_ + dy)), 0.25, INK)
            else:
                leaves = [(s0, 1, o.width)] if o.kind == "single" else [(s0, 1, o.width / 2), (s1, -1, o.width / 2)]
                for hinge, dirn, r in leaves:
                    tip = (hinge[0] + sw[0] * r, hinge[1] + sw[1] * r)
                    c.line(v(hinge), v(tip), 0.3, INK)
                    close = (hinge[0] + ux * r * dirn, hinge[1] + uy * r * dirn)
                    hx, hy = v(hinge)
                    a0 = math.atan2(v(tip)[1] - hy, v(tip)[0] - hx)
                    a1 = math.atan2(v(close)[1] - hy, v(close)[0] - hx)
                    if a1 - a0 > math.pi:
                        a1 -= 2 * math.pi
                    elif a0 - a1 > math.pi:
                        a1 += 2 * math.pi
                    c.arc((hx, hy), r * k, a0, a1, 0.13, THIN)
            label = tag.get(o.id, "")
            mid = ((s0[0] + s1[0]) / 2 - sw[0] * (t / 2 + 0.5), (s0[1] + s1[1]) / 2 - sw[1] * (t / 2 + 0.5))
            mx, my = v(mid)
            c.rect(mx - text_width(label, 1.5) / 2 - 0.8, my - 1.4, text_width(label, 1.5) + 1.6, 2.8, "#fff", INK, 0.13)
            c.text((mx, my + 0.55), label, 1.5, anchor="middle")

    # room tags
    for e in els:
        if not isinstance(e, Space):
            continue
        r = rooms.get(e.id)
        poly = Polygon(e.outline)
        p = poly.centroid if poly.contains(poly.centroid) else poly.representative_point()
        px, py = v((p.x, p.y))
        bx0, by0, bx1, by1 = poly.bounds
        small = min(bx1 - bx0, by1 - by0) * k < 20
        size = 1.8 if small else 2.3
        name = (e.name or e.id).upper()
        while text_width(name, size, True) > (bx1 - bx0) * k - 2 and size > 1.3:
            size -= 0.1
        c.text((px, py - 0.8), name, size, True, "middle")
        if r:
            num = r["number"]
            c.rect(px - 4, py + 0.6, 8, 3.2, "#fff", INK, 0.18)
            c.text((px, py + 3.0), num, 1.9, True, "middle")
            c.text((px, py + 6.6), f"{r['area']:.1f} m²  ·  {r['area'] * 10.7639:,.0f} sf", 1.7, anchor="middle", color="#333")

    # dimension strings
    ext_here = [w for w in walls if w.external]
    xs = _grid([p[0] for w in ext_here for p in w.axis]) if ext_here else [x0, x1]
    ys = _grid([p[1] for w in ext_here for p in w.axis]) if ext_here else [y0, y1]
    base_y = v((0, y0))[1] + 10
    _dims(c, v, x0, x1, base_y, xs, True)
    _dims(c, v, x0, x1, base_y + 6, [xs[0], xs[-1]], True)
    base_x = v((x0, 0))[0] - 18
    _dims(c, v, y0, y1, base_x + 7, ys, False)
    _dims(c, v, y0, y1, base_x, [ys[0], ys[-1]], False)

    # section mark
    if section is not None:
        axis, at = section
        if axis == "y":
            sy = v((0, at))[1]
            ends = [(v((x0, 0))[0] - 8, sy), (v((x1, 0))[0] + 12, sy)]
            arrow = (0, -5.2)
        else:
            sx = v((at, 0))[0]
            ends = [(sx, v((0, y1))[1] - 6), (sx, v((0, y0))[1] + 26)]
            arrow = (-5.2, 0)
        (ex0, ey0), (ex1, ey1) = ends
        dx, dy = (ex1 - ex0), (ey1 - ey0)
        L = math.hypot(dx, dy) or 1
        c.line((ex0 + dx / L * 3, ey0 + dy / L * 3), (ex0 + dx / L * 12, ey0 + dy / L * 12), 0.5, INK, (3, 1, 0.6, 1))
        c.line((ex1 - dx / L * 12, ey1 - dy / L * 12), (ex1 - dx / L * 3, ey1 - dy / L * 3), 0.5, INK, (3, 1, 0.6, 1))
        for ex, ey in ends:
            c.circle((ex, ey), 3.0, "#fff", INK, 0.3)
            if axis == "y":
                c.polygon([(ex - 3.0, ey), (ex + 3.0, ey), (ex + arrow[0], ey + arrow[1])], INK)
            else:
                c.polygon([(ex, ey - 3.0), (ex, ey + 3.0), (ex + arrow[0], ey + arrow[1])], INK)
            c.text((ex, ey + 1.0), "A", 2.2, True, "middle")
        c.text((ex1 + 4, ey1 + 1), "A-301", 1.7, color=THIN)

    # furniture legend, north arrow, scale bar, title
    lx, ly = ax0, ay1 - 2
    north_arrow(c, ax1 - 10, ay0 + 12)
    scale_bar(c, ax1 - 62, ay1 - 12, scale)
    drawing_title(c, lx, ly - 4, n, f"{level.name} plan", f"SCALE 1:{scale}  ·  FFL {level.elevation or 0:+.3f}", 90)
    kinds = {rooms.get(e.id, {}).get("kind") for e in els if isinstance(e, Space)}
    shown = [(label, col) for label, col in LEGEND if col in {TINTS.get(kd) for kd in kinds}]
    for i, (label, col) in enumerate(shown):
        cx = lx + 110 + (i % 4) * 30
        cy = ly - 9 + (i // 4) * 4.5
        c.rect(cx, cy - 2.2, 4, 2.8, col, THIN, 0.13)
        c.text((cx + 5.5, cy), label, 1.8)
    frame(c, meta, number, f"{level.name} plan", f"1:{scale} @ A3")
    return Sheet(number, f"{level.name} plan", "plan", c, f"1:{scale}")


# --- elevations and section -----------------------------------------------

SIDES = {"south": ((0, -1), lambda p: p[0]), "north": ((0, 1), lambda p: -p[0]),
         "east": ((1, 0), lambda p: p[1]), "west": ((-1, 0), lambda p: -p[1])}


def _faces(spec: BuildingSpec, normal, u_of, only=None):
    """Wall faces seen looking against `normal`, far ones first, each with its openings."""
    levels = {l.id: l for l in spec.levels}
    by_wall = _openings(spec)
    out = []
    for w in spec.elements:
        if not isinstance(w, Wall) or len(w.axis) != 2 or (only and not only(w)):
            continue
        n = outward(w, spaces_union(spec, w.level)) if w.external else None
        if n is None:
            continue
        if n[0] * normal[0] + n[1] * normal[1] < 0.7:
            continue
        lvl = levels[w.level]
        z0 = (lvl.elevation or 0) + w.elevation
        z1 = z0 + (w.height or lvl.height)
        a, b = w.axis
        L = w.length or 1
        ops = []
        for o in by_wall.get(w.id, []):
            p0 = (a[0] + (b[0] - a[0]) * o.offset / L, a[1] + (b[1] - a[1]) * o.offset / L)
            p1 = (a[0] + (b[0] - a[0]) * (o.offset + o.width) / L, a[1] + (b[1] - a[1]) * (o.offset + o.width) / L)
            zb = z0 + (o.sill_height if isinstance(o, Window) else 0)
            ops.append((o, u_of(p0), u_of(p1), zb, zb + o.height))
        depth = (a[0] + b[0]) / 2 * normal[0] + (a[1] + b[1]) / 2 * normal[1]
        out.append((depth, w, u_of(a), u_of(b), z0, z1, ops))
    out.sort(key=lambda f: f[0])
    return out


def _roof_profile(roof: Roof, level, u_of, normal, samples: int = 48):
    xs, ys = [p[0] for p in roof.outline], [p[1] for p in roof.outline]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    base = (level.elevation or 0) + level.height + roof.elevation
    horizontal = abs(normal[1]) > 0.5
    pts = []
    for i in range(samples + 1):
        f = i / samples
        if horizontal:
            x = x0 + (x1 - x0) * f
            h = max(roof_height(roof, x, y0 + (y1 - y0) * j / 16) for j in range(17))
            pts.append((u_of((x, 0)), h))
        else:
            y = y0 + (y1 - y0) * f
            h = max(roof_height(roof, x0 + (x1 - x0) * j / 16, y) for j in range(17))
            pts.append((u_of((0, y)), h))
    pts.sort()
    return base, pts


def _datums(c: Canvas, spec: BuildingSpec, zv, xl: float, xr: float, label_x: float, roof_top: float | None) -> None:
    for l in spec.levels:
        z = l.elevation or 0
        y = zv(z)
        c.line((xl, y), (xr, y), 0.13, THIN, (3, 1.2))
        c.polygon([(label_x, y), (label_x + 2.2, y - 2.2), (label_x + 4.4, y)], INK)
        c.text((label_x + 6, y - 0.6), l.name.upper(), 1.9, True)
        c.text((label_x + 6, y + 2.4), f"{'±' if abs(z) < 1e-6 else '+' if z > 0 else ''}{z:.3f}", 1.8, color=THIN)
    if roof_top is not None:
        y = zv(roof_top)
        c.line((xl, y), (xr, y), 0.13, THIN, (3, 1.2))
        c.polygon([(label_x, y), (label_x + 2.2, y - 2.2), (label_x + 4.4, y)], INK)
        c.text((label_x + 6, y - 0.6), "TOP OF ROOF", 1.9, True)
        c.text((label_x + 6, y + 2.4), f"+{roof_top:.3f}", 1.8, color=THIN)


def _top(spec: BuildingSpec) -> float:
    levels = {l.id: l for l in spec.levels}
    top = max((l.elevation or 0) + l.height for l in spec.levels)
    for r in spec.elements:
        if isinstance(r, Roof):
            lvl = levels[r.level]
            _, prof = _roof_profile(r, lvl, lambda p: p[0], (0, -1), 8)
            top = max(top, (lvl.elevation or 0) + lvl.height + r.elevation + max(h for _, h in prof) + r.thickness)
    return top


def elevation(c: Canvas, spec: BuildingSpec, side: str, cell: tuple[float, float, float, float], scale: int, n: int) -> None:
    normal, u_of = SIDES[side]
    x0, y0, x1, y1 = extent(spec)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    us = [u_of(p) for p in corners]
    umin, umax = min(us), max(us)
    k = 1000 / scale
    cx0, cy0, cx1, cy1 = cell
    top = _top(spec)
    width = (umax - umin) * k
    ox = cx0 + (cx1 - cx0 - 30 - width) / 2
    ground = cy1 - 16

    def uv(u: float) -> float:
        return ox + (u - umin) * k

    def zv(z: float) -> float:
        return ground - z * k

    c.rect(uv(umin) - 6, ground, width + 12, 2.2, "#e7e1d3", None)
    levels = {l.id: l for l in spec.levels}
    for depth, w, ua, ub, z0, z1, ops in _faces(spec, normal, u_of):
        ul, ur = min(ua, ub), max(ua, ub)
        c.rect(uv(ul), zv(z1), (ur - ul) * k, (z1 - z0) * k, FACADE.get(w.material, FACADE[None]), INK, 0.25)
        for o, u0, u1, zb, zt in ops:
            ul_, ur_ = min(u0, u1), max(u0, u1)
            if isinstance(o, Window):
                c.rect(uv(ul_), zv(zt), (ur_ - ul_) * k, (zt - zb) * k, "#cfe1ea", INK, 0.2)
                c.line((uv(ul_), zv(zb)), (uv(ur_), zv(zb)), 0.45, INK)
                panes = max(1, round((ur_ - ul_) / 1.2))
                for j in range(1, panes):
                    xm = uv(ul_ + (ur_ - ul_) * j / panes)
                    c.line((xm, zv(zt)), (xm, zv(zb)), 0.13, INK)
            else:
                c.rect(uv(ul_), zv(zt), (ur_ - ul_) * k, (zt - zb) * k, "#e7dfd0" if o.kind not in ("garage", "roller") else "#d3d6d9", INK, 0.25)
                if o.kind in ("double", "french"):
                    xm = uv((ul_ + ur_) / 2)
                    c.line((xm, zv(zt)), (xm, zv(zb)), 0.13, INK)
                elif o.kind in ("garage", "roller"):
                    for j in range(1, 8):
                        z = zb + (zt - zb) * j / 8
                        c.line((uv(ul_), zv(z)), (uv(ur_), zv(z)), 0.1, THIN)
    for r in spec.elements:
        if isinstance(r, Roof):
            lvl = levels[r.level]
            base, prof = _roof_profile(r, lvl, u_of, normal)
            if r.shape == "flat":
                c.rect(uv(prof[0][0]) - 0.8, zv(base + r.thickness), (prof[-1][0] - prof[0][0]) * k + 1.6, r.thickness * k, "#7d7d7d", INK, 0.25)
            else:
                upper = [(uv(u), zv(base + h + r.thickness)) for u, h in prof]
                lower = [(uv(u), zv(base + h)) for u, h in reversed(prof)]
                c.polygon(upper + lower, "#8f8a84", INK, 0.25)
                fill = [(uv(u), zv(base + h)) for u, h in prof] + [(uv(prof[-1][0]), zv(base)), (uv(prof[0][0]), zv(base))]
                c.polygon(fill, "#b8b1a6", INK, 0.2)
    c.line((uv(umin) - 8, ground), (uv(umax) + 8, ground), 0.6, INK)
    _datums(c, spec, zv, uv(umin) - 6, uv(umax) + 10, uv(umax) + 11, top)
    drawing_title(c, cx0 + 2, cy1 - 5, n, f"{side} elevation", f"SCALE 1:{scale}", 60)


def elevation_sheet(spec: BuildingSpec, meta: Meta, number: str) -> Sheet:
    c = Canvas(W, H)
    ax0, ay0, ax1, ay1 = AREA
    ay1 += 16
    x0, y0, x1, y1 = extent(spec)
    top = _top(spec)
    cw, ch = (ax1 - ax0) / 2, (ay1 - ay0) / 2
    scale = pick_scale(max(x1 - x0, y1 - y0), top, cw - 44, ch - 30)
    cells = [(ax0, ay0, ax0 + cw, ay0 + ch), (ax0 + cw, ay0, ax1, ay0 + ch),
             (ax0, ay0 + ch, ax0 + cw, ay1), (ax0 + cw, ay0 + ch, ax1, ay1)]
    for i, (side, cell) in enumerate(zip(("south", "north", "east", "west"), cells), 1):
        elevation(c, spec, side, cell, scale, i)
    frame(c, meta, number, "Elevations", f"1:{scale} @ A3")
    return Sheet(number, "Elevations", "elevation", c, f"1:{scale}")


def section_line(spec: BuildingSpec) -> tuple[str, float]:
    """Where section A-A cuts: along the first stair's flight, so the section shows it; else mid-plan.
    ("y", v) is a cut on the line y = v looking north; ("x", v) is x = v looking west."""
    stairs = [s for s in spec.elements if isinstance(s, Stair)]
    x0, y0, x1, y1 = extent(spec)
    if stairs:
        s = stairs[0]
        _, (ux, uy), _, _ = _stair_outline(s, s.rise or next(l for l in spec.levels if l.id == s.level).height)
        return ("y", s.position[1]) if abs(uy) < 0.5 else ("x", s.position[0])
    return ("y", (y0 + y1) / 2) if (x1 - x0) >= (y1 - y0) else ("x", (x0 + x1) / 2)


def _turn(p):
    """Plan rotation that makes a cut on x = v looking west into a cut on y = -v looking north."""
    return (p[1], -p[0])


def rotated(spec: BuildingSpec) -> BuildingSpec:
    out = spec.model_copy(deep=True)
    for e in out.elements:
        if isinstance(e, Roof) and e.shape != "flat":
            xs, ys = [p[0] for p in e.outline], [p[1] for p in e.outline]
            ridge = e.ridge or ("x" if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else "y")
            e.ridge = "y" if ridge == "x" else "x"
        for attr in ("start", "end", "position"):
            if getattr(e, attr, None) is not None:
                setattr(e, attr, _turn(getattr(e, attr)))
        for attr in ("path", "outline"):
            if getattr(e, attr, None):
                setattr(e, attr, [_turn(p) for p in getattr(e, attr)])
        if isinstance(e, Stair):
            e.direction = (e.direction - 90) % 360
        if isinstance(e, (Fixture, CustomFixture, Asset)):
            e.rotation = e.rotation - 90
    return out


def section_sheet(spec: BuildingSpec, review: dict, meta: Meta, number: str) -> Sheet:
    c = Canvas(W, H)
    ax0, ay0, ax1, ay1 = AREA
    axis, at = section_line(spec)
    looking = "north"
    cut = at
    if axis == "x":
        spec, cut, looking = rotated(spec), -at, "west"
    x0, y0, x1, y1 = extent(spec)
    top = _top(spec)
    scale = pick_scale(x1 - x0, top + 1.0, ax1 - ax0 - 70, ay1 - ay0 - 40)
    k = 1000 / scale
    ox = ax0 + 30 + ((ax1 - ax0 - 70) - (x1 - x0) * k) / 2
    ground = ay1 - 22
    levels = {l.id: l for l in spec.levels}

    def uv(x: float) -> float:
        return ox + (x - x0) * k

    def zv(z: float) -> float:
        return ground - z * k

    # beyond: the far walls (inner faces of walls north of the cut)
    beyond = _faces(spec, (0, 1), lambda p: p[0], only=lambda w: min(p[1] for p in w.axis) > cut + 0.05)[::-1]
    c.rect(uv(x0) - 10, ground, (x1 - x0) * k + 20, 0.6 * k, "#ece6d8", None)
    for depth, w, ua, ub, z0, z1, ops in beyond:
        ul, ur = min(ua, ub), max(ua, ub)
        c.rect(uv(ul), zv(z1), (ur - ul) * k, (z1 - z0) * k, "#ffffff", FAINT, 0.18)
        for o, u0, u1, zb, zt in ops:
            c.rect(uv(min(u0, u1)), zv(zt), abs(u1 - u0) * k, (zt - zb) * k, "#eef4f7" if isinstance(o, Window) else "#f4f0e8", FAINT, 0.15)
    # far faces of north walls seen from inside face south; also draw the interior partitions beyond as lines
    cutline = LineString([(x0 - 50, cut), (x1 + 50, cut)])
    for s in spec.elements:
        if isinstance(s, Space):
            lvl = levels[s.level]
            seg = Polygon(s.outline).intersection(cutline)
            if seg.is_empty:
                continue
            bx0, _, bx1, _ = seg.bounds
            z = lvl.elevation or 0
            c.text(((uv(bx0) + uv(bx1)) / 2, zv(z + 1.25)), (s.name or s.id).upper(), 1.9, True, "middle")
            num = next((r["number"] for r in review.get("rooms", []) if r["id"] == s.id), "")
            if num:
                c.text(((uv(bx0) + uv(bx1)) / 2, zv(z + 1.25) + 3), num, 1.7, anchor="middle", color=THIN)
    # cut elements
    for e in spec.elements:
        if isinstance(e, Slab):
            lvl = levels[e.level]
            seg = Polygon(e.outline).intersection(cutline)
            for g in getattr(seg, "geoms", [seg]):
                if g.is_empty or g.length <= 0:
                    continue
                gx0, _, gx1, _ = g.bounds
                ztop = (lvl.elevation or 0) + e.elevation
                c.rect(uv(gx0), zv(ztop), (gx1 - gx0) * k, e.thickness * k, POCHE, INK, 0.12)
        elif isinstance(e, Wall):
            line = LineString(e.axis)
            hit = line.intersection(cutline)
            if hit.is_empty or not isinstance(hit, Point):
                continue
            lvl = levels[e.level]
            (ax_, ay_), (bx_, by_) = e.axis[0], e.axis[-1]
            sin = abs(by_ - ay_) / (math.hypot(bx_ - ax_, by_ - ay_) or 1)
            half = e.thickness / 2 / max(sin, 0.3)
            z0 = (lvl.elevation or 0) + e.elevation
            z1 = z0 + (e.height or lvl.height)
            opening = None
            dist = math.dist(e.axis[0], (hit.x, hit.y))
            for o in _openings(spec).get(e.id, []):
                if o.offset <= dist <= o.offset + o.width:
                    opening = o
            if opening is None:
                c.rect(uv(hit.x - half), zv(z1), 2 * half * k, (z1 - z0) * k, POCHE, INK, 0.12)
            else:
                zb = z0 + (opening.sill_height if isinstance(opening, Window) else 0)
                zt = zb + opening.height
                if zb > z0:
                    c.rect(uv(hit.x - half), zv(zb), 2 * half * k, (zb - z0) * k, POCHE, INK, 0.12)
                c.rect(uv(hit.x - half), zv(z1), 2 * half * k, (z1 - zt) * k, POCHE, INK, 0.12)
                if isinstance(opening, Window):
                    c.line((uv(hit.x), zv(zt)), (uv(hit.x), zv(zb)), 0.3, INK)
        elif isinstance(e, Stair):
            rise = e.rise or levels[e.level].height
            run, (ux, uy), _, _ = _stair_outline(e, rise)
            if abs(uy) > 0.3 or abs(e.position[1] - cut) > e.width / 2 + 0.01:
                continue
            steps = e.steps(rise)
            r = rise / steps
            z = levels[e.level].elevation or 0
            pts = [(e.position[0], z)]
            for i in range(steps):
                x = e.position[0] + ux * e.going * i
                pts += [(x, z + r * (i + 1)), (x + ux * e.going, z + r * (i + 1))]
            end = pts[-1]
            pts += [(end[0], end[1] - 0.25), (e.position[0] + ux * 0.25, z)]
            c.polygon([(uv(x), zv(zz)) for x, zz in pts], "#3a3a3a", INK, 0.15)
        elif isinstance(e, Roof):
            lvl = levels[e.level]
            base = (lvl.elevation or 0) + lvl.height + e.elevation
            xs = [p[0] for p in e.outline]
            rx0, rx1 = min(xs), max(xs)
            samples = [rx0 + (rx1 - rx0) * i / 48 for i in range(49)]
            upper = [(uv(x), zv(base + roof_height(e, x, cut) + e.thickness)) for x in samples]
            lower = [(uv(x), zv(base + roof_height(e, x, cut))) for x in reversed(samples)]
            c.polygon(upper + lower, POCHE, INK, 0.12)
    c.line((uv(x0) - 12, ground), (uv(x1) + 12, ground), 0.6, INK)
    _datums(c, spec, zv, uv(x0) - 10, uv(x1) + 12, uv(x1) + 14, top)
    # floor-to-floor dimension chain
    zs = sorted({l.elevation or 0 for l in spec.levels} | {top})
    at = uv(x0) - 18
    for i, z in enumerate(zs):
        y = zv(z)
        c.line((at - 1.5, y), (at + 1.5, y), 0.13, INK)
        c.line((at - 0.9, y + 0.9), (at + 0.9, y - 0.9), 0.35, INK)
        if i:
            y0_ = zv(zs[i - 1])
            c.line((at, y0_), (at, y), 0.13, INK)
            c.text((at - 1.2, (y0_ + y) / 2), mm(z - zs[i - 1]), 1.9, anchor="middle", angle=90)
    drawing_title(c, ax0, ay1 - 2, 1, "Section A-A", f"SCALE 1:{scale}  ·  cut at {axis} = {at:.2f} m, looking {looking}", 110)
    frame(c, meta, number, "Building section A-A", f"1:{scale} @ A3")
    return Sheet(number, "Building section A-A", "section", c, f"1:{scale}")


# --- schedules -------------------------------------------------------------

def table(c: Canvas, x: float, y: float, title: str, cols: list[tuple[str, float, str]], rows: list[list[str]],
          row_h: float = 4.3) -> float:
    total = sum(w for _, w, _ in cols)
    c.text((x, y), title.upper(), 2.8, True)
    y += 2.5
    c.rect(x, y, total, row_h + 0.6, "#1f2937", None)
    cx = x
    for name, w, align in cols:
        tx = cx + 1.4 if align == "start" else cx + w - 1.4 if align == "end" else cx + w / 2
        c.text((tx, y + row_h - 1.1), name, 1.8, True, align, "#ffffff")
        cx += w
    y += row_h + 0.6
    for i, row in enumerate(rows):
        if i % 2:
            c.rect(x, y, total, row_h, "#f4f4f2", None)
        cx = x
        for (name, w, align), val in zip(cols, row):
            tx = cx + 1.4 if align == "start" else cx + w - 1.4 if align == "end" else cx + w / 2
            s = str(val)
            while text_width(s, 1.9) > w - 2 and len(s) > 3:
                s = s[:-2] + "…"
            c.text((tx, y + row_h - 1.2), s, 1.9, anchor=align)
            cx += w
        y += row_h
    c.line((x, y), (x + total, y), 0.3, INK)
    return y


def schedule_rows(spec: BuildingSpec, review: dict) -> tuple[list, list, list, list]:
    tag = marks(spec)
    walls = {e.id: e for e in spec.elements if isinstance(e, Wall)}
    levels = {l.id: l for l in spec.levels}
    rooms = review.get("rooms", [])
    room_rows = [[r["number"], r["name"], r["level_name"], f"{r['area']:.2f}", f"{r['area'] * 10.7639:,.0f}",
                  f"{r['perimeter']:.1f}", f"{r['clear_height'] * 1000:,.0f}", f"{r['window_floor_ratio']:.0%}",
                  str(r["occupants"] or "—")] for r in rooms]
    door_rows, window_rows = [], []
    for e in spec.elements:
        if isinstance(e, Door):
            w = walls.get(e.wall)
            door_rows.append([tag.get(e.id, e.id), e.kind.title(), f"{e.width * 1000:,.0f}", f"{e.height * 1000:,.0f}",
                              levels[w.level].name if w else "", "Exterior" if w and w.external else "Interior",
                              e.name or e.id])
        elif isinstance(e, Window):
            w = walls.get(e.wall)
            window_rows.append([tag.get(e.id, e.id), f"{e.width * 1000:,.0f}", f"{e.height * 1000:,.0f}",
                                f"{e.sill_height * 1000:,.0f}", f"{e.width * e.height:.2f}",
                                levels[w.level].name if w else "", e.name or e.id])
    door_rows.sort(key=lambda r: r[0])
    window_rows.sort(key=lambda r: r[0])
    level_rows = [[l["name"], f"{l['gia']:.1f}", f"{l['nia']:.1f}", f"{l['circulation']:.1f}",
                   f"{l['efficiency']:.0%}", str(l["occupants"])] for l in review.get("levels", [])]
    t = review.get("totals", {})
    if level_rows:
        level_rows.append(["TOTAL", f"{t.get('gia', 0):.1f}", f"{t.get('nia', 0):.1f}",
                           f"{sum(l['circulation'] for l in review.get('levels', [])):.1f}",
                           f"{t.get('efficiency', 0):.0%}", str(review.get("occupancy", {}).get("load", ""))])
    return room_rows, door_rows, window_rows, level_rows


ROOM_COLS = [("NO.", 11, "start"), ("ROOM", 37, "start"), ("LEVEL", 22, "start"), ("m²", 14, "end"),
             ("sf", 13, "end"), ("PERIM. m", 15, "end"), ("CLEAR H", 14, "end"), ("GLAZING", 14, "end"),
             ("OCC.", 10, "end")]
DOOR_COLS = [("MARK", 13, "start"), ("TYPE", 17, "start"), ("W mm", 13, "end"), ("H mm", 13, "end"),
             ("LEVEL", 22, "start"), ("LOCATION", 19, "start"), ("DESCRIPTION", 53, "start")]
WINDOW_COLS = [("MARK", 13, "start"), ("W mm", 13, "end"), ("H mm", 13, "end"), ("SILL mm", 14, "end"),
               ("AREA m²", 15, "end"), ("LEVEL", 22, "start"), ("DESCRIPTION", 60, "start")]
LEVEL_COLS = [("LEVEL", 34, "start"), ("GIA m²", 20, "end"), ("NIA m²", 20, "end"), ("CIRC. m²", 20, "end"),
              ("NIA/GIA", 18, "end"), ("OCC.", 14, "end")]


def schedule_sheets(spec: BuildingSpec, review: dict, meta: Meta, first: int) -> list[Sheet]:
    room_rows, door_rows, window_rows, level_rows = schedule_rows(spec, review)
    ax0, ay0, ax1, ay1 = AREA
    ay1 += 16
    col_x = [ax0, ax0 + (ax1 - ax0) / 2 + 3]
    sheets: list[Sheet] = []
    state = {"col": 0, "y": ay0 + 4}

    def new_sheet() -> None:
        sheets.append(Sheet(f"A-{first + len(sheets)}", "Schedules", "schedule", Canvas(W, H), "NTS"))
        state.update(col=0, y=ay0 + 4)

    new_sheet()
    for title, cols, rows in [("Area summary", LEVEL_COLS, level_rows), ("Room schedule", ROOM_COLS, room_rows),
                              ("Door schedule", DOOR_COLS, door_rows), ("Window schedule", WINDOW_COLS, window_rows)]:
        start = 0
        while start < len(rows):
            room = int((ay1 - state["y"] - 12) / 4.3) - 1
            if room < 3:
                state.update(col=state["col"] + 1, y=ay0 + 4)
                if state["col"] > 1:
                    new_sheet()
                continue
            chunk = rows[start:start + room]
            label = title if start == 0 else f"{title} (continued)"
            state["y"] = table(sheets[-1].canvas, col_x[state["col"]], state["y"], label, cols, chunk) + 9
            start += len(chunk)
    for sh in sheets:
        frame(sh.canvas, meta, sh.number, "Schedules — areas, rooms, doors, windows", "NTS")
    return sheets


# --- cover and axonometric ------------------------------------------------

def _iso(p) -> tuple[float, float]:
    x, y, z = p
    return ((x - y) * 0.866, -((x + y) * 0.5 + z))


def axonometric(c: Canvas, spec: BuildingSpec, box_: tuple[float, float, float, float]) -> None:
    levels = {l.id: l for l in spec.levels}
    faces = []   # (order, depth, pts3, fill)
    light = (-0.45, -0.6, 0.66)
    view = (-1, -1, 1.15)

    def shade(hexcol: str, n) -> str:
        f = 0.72 + 0.28 * max(0.0, n[0] * light[0] + n[1] * light[1] + n[2] * light[2])
        c_ = hexcol.lstrip("#")
        r, g, b = (int(c_[i:i + 2], 16) for i in (0, 2, 4))
        return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))

    def add(order: float, pts, fill: str, n) -> None:
        if n[0] * view[0] + n[1] * view[1] + n[2] * view[2] <= 1e-6:
            return
        depth = sum(p[0] + p[1] for p in pts) / len(pts)
        faces.append((order, -depth, pts, shade(fill, n)))

    by_wall = _openings(spec)
    order_of = {l.id: i for i, l in enumerate(spec.levels)}
    for e in spec.elements:
        if isinstance(e, Slab):
            lvl = levels[e.level]
            z = (lvl.elevation or 0) + e.elevation
            o = order_of[e.level] * 10
            ring = list(e.outline)
            add(o, [(x, y, z) for x, y in ring], "#e9e7e2", (0, 0, 1))
            for a, b in zip(ring, ring[1:] + ring[:1]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                L = math.hypot(dx, dy) or 1
                add(o, [(a[0], a[1], z), (b[0], b[1], z), (b[0], b[1], z - e.thickness), (a[0], a[1], z - e.thickness)],
                    "#bdbab4", (dy / L, -dx / L, 0))
        elif isinstance(e, Wall) and len(e.axis) >= 2:
            lvl = levels[e.level]
            z0 = (lvl.elevation or 0) + e.elevation
            z1 = z0 + (e.height or lvl.height)
            o = order_of[e.level] * 10 + 1
            col = FACADE.get(e.material, FACADE[None]) if e.external else "#f2f2f0"
            for (ax_, ay_), (bx_, by_) in zip(e.axis, e.axis[1:]):
                L = math.hypot(bx_ - ax_, by_ - ay_) or 1
                nx, ny = -(by_ - ay_) / L * e.thickness / 2, (bx_ - ax_) / L * e.thickness / 2
                A, B = (ax_ + nx, ay_ + ny), (bx_ + nx, by_ + ny)
                Cc, D = (bx_ - nx, by_ - ny), (ax_ - nx, ay_ - ny)
                un = (nx / (e.thickness / 2), ny / (e.thickness / 2))
                add(o, [(*A, z0), (*B, z0), (*B, z1), (*A, z1)], col, (un[0], un[1], 0))
                add(o, [(*D, z0), (*Cc, z0), (*Cc, z1), (*D, z1)], col, (-un[0], -un[1], 0))
                add(o, [(*A, z1), (*B, z1), (*Cc, z1), (*D, z1)], "#4a4a4a", (0, 0, 1))
                ux_, uy_ = (bx_ - ax_) / L, (by_ - ay_) / L
                add(o, [(*A, z0), (*D, z0), (*D, z1), (*A, z1)], col, (-ux_, -uy_, 0))
                add(o, [(*B, z0), (*Cc, z0), (*Cc, z1), (*B, z1)], col, (ux_, uy_, 0))
                if len(e.axis) == 2:
                    for op in by_wall.get(e.id, []):
                        zb = z0 + (op.sill_height if isinstance(op, Window) else 0)
                        zt = zb + op.height
                        for sgn in (1, -1):
                            n_ = (un[0] * sgn, un[1] * sgn, 0)
                            off = (nx * sgn * 1.02, ny * sgn * 1.02)
                            p0 = (ax_ + ux_ * op.offset + off[0], ay_ + uy_ * op.offset + off[1])
                            p1 = (ax_ + ux_ * (op.offset + op.width) + off[0], ay_ + uy_ * (op.offset + op.width) + off[1])
                            add(o + 0.5, [(*p0, zb), (*p1, zb), (*p1, zt), (*p0, zt)],
                                "#5d7b8c" if isinstance(op, Window) else "#6b5a48", n_)
        elif isinstance(e, Roof):
            lvl = levels[e.level]
            base = (lvl.elevation or 0) + lvl.height + e.elevation
            o = order_of[e.level] * 10 + 5
            xs, ys = [p[0] for p in e.outline], [p[1] for p in e.outline]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            if e.shape == "flat":
                ring = list(e.outline)
                add(o, [(x, y, base + e.thickness) for x, y in ring], "#8a8a88", (0, 0, 1))
                for a, b in zip(ring, ring[1:] + ring[:1]):
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    L = math.hypot(dx, dy) or 1
                    add(o, [(a[0], a[1], base), (b[0], b[1], base), (b[0], b[1], base + e.thickness), (a[0], a[1], base + e.thickness)],
                        "#6f6f6d", (dy / L, -dx / L, 0))
                continue
            grid = 12
            for i in range(grid):
                for j in range(grid):
                    xa, xb = x0 + (x1 - x0) * i / grid, x0 + (x1 - x0) * (i + 1) / grid
                    ya, yb = y0 + (y1 - y0) * j / grid, y0 + (y1 - y0) * (j + 1) / grid
                    quad = [(xa, ya), (xb, ya), (xb, yb), (xa, yb)]
                    pts = [(x, y, base + roof_height(e, x, y) + e.thickness) for x, y in quad]
                    ux_ = (pts[1][0] - pts[0][0], 0, pts[1][2] - pts[0][2])
                    vy_ = (0, pts[3][1] - pts[0][1], pts[3][2] - pts[0][2])
                    n = (ux_[1] * vy_[2] - ux_[2] * vy_[1], ux_[2] * vy_[0] - ux_[0] * vy_[2], ux_[0] * vy_[1] - ux_[1] * vy_[0])
                    L = math.sqrt(sum(v_ * v_ for v_ in n)) or 1
                    faces.append((o, -sum(p[0] + p[1] for p in pts) / 4, pts, shade("#a79f95", (n[0] / L, n[1] / L, n[2] / L)), "roof"))
            for side_pts, n in (([(x0, y0), (x1, y0)], (0, -1, 0)), ([(x0, y0), (x0, y1)], (-1, 0, 0))):
                (a, b) = side_pts
                samples = [(a[0] + (b[0] - a[0]) * t / 24, a[1] + (b[1] - a[1]) * t / 24) for t in range(25)]
                top_ = [(x, y, base + roof_height(e, x, y)) for x, y in samples]
                poly = top_ + [(b[0], b[1], base), (a[0], a[1], base)]
                add(o - 0.1, poly, "#e4ded3", n)
    if not faces:
        return
    proj = [_iso(p) for f in faces for p in f[2]]
    px0, py0 = min(p[0] for p in proj), min(p[1] for p in proj)
    px1, py1 = max(p[0] for p in proj), max(p[1] for p in proj)
    bx0, by0, bx1, by1 = box_
    s = min((bx1 - bx0) / ((px1 - px0) or 1), (by1 - by0) / ((py1 - py0) or 1))
    ox = bx0 + ((bx1 - bx0) - (px1 - px0) * s) / 2
    oy = by0 + ((by1 - by0) - (py1 - py0) * s) / 2

    def P(p):
        x, y = _iso(p)
        return (ox + (x - px0) * s, oy + (y - py0) * s)

    x0, y0, x1, y1 = extent(spec)
    pad = max(x1 - x0, y1 - y0) * 0.25
    site = [(x0 - pad, y0 - pad, -0.02), (x1 + pad, y0 - pad, -0.02), (x1 + pad, y1 + pad, -0.02), (x0 - pad, y1 + pad, -0.02)]
    c.polygon([P(p) for p in site], "#eef2e8", "#c9d3bd", 0.2)
    shadow = [(x + 1.5, y + 2.5, -0.01) for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
    c.polygon([P(p) for p in shadow], "#d9dfd0", None)
    faces.sort(key=lambda f: (f[0], f[1]))
    for f in faces:
        stroke = f[3] if len(f) > 4 else "#2d2d2d"
        c.polygon([P(p) for p in f[2]], f[3], stroke, 0.08 if len(f) > 4 else 0.12)


def cover_sheet(spec: BuildingSpec, review: dict, meta: Meta, index: list[tuple[str, str]], number: str = "G-001") -> Sheet:
    c = Canvas(W, H)
    ax0, ay0, ax1, ay1 = AREA
    ay1 += 16
    c.text((ax0, ay0 + 8), meta.project.upper(), 8, True)
    y = ay0 + 14
    for line in wrap(meta.description or "", 190, 3)[:2]:
        c.text((ax0, y), line, 3, color="#333")
        y += 4.4
    axo = (ax0, y + 4, ax0 + 200, ay1 - 30)
    axonometric(c, spec, axo)
    c.text((ax0, ay1 - 24), "AXONOMETRIC FROM THE SOUTH-WEST", 2.2, True, color=THIN)
    if meta.brief:
        c.text((ax0, ay1 - 17), "BRIEF", 1.9, True, color=THIN)
        for i, line in enumerate(wrap(f"“{meta.brief.strip()}”", 196, 2.4)[:3]):
            c.text((ax0, ay1 - 13 + i * 3.5), line, 2.4, color="#222")
    # right column: project data, code summary, index
    x = ax0 + 210
    colw = ax1 - x
    y = ay0 + 6
    occ = review.get("occupancy", {})
    tot = review.get("totals", {})
    c.text((x, y), "PROJECT DATA", 2.6, True)
    y += 2
    data = [("Occupancy", f"{occ.get('group', '—')} · {occ.get('name', '').split('—')[-1].strip()}"),
            ("Construction", occ.get("construction", "—")),
            ("Code basis", review.get("code", "—")),
            ("Storeys", f"{tot.get('storeys', len(spec.levels))} · {tot.get('height', 0):.1f} m to roof"),
            ("Gross floor area", f"{tot.get('gia', 0):,.1f} m² · {tot.get('gia_sf', 0):,} sf"),
            ("Net internal area", f"{tot.get('nia', 0):,.1f} m² · efficiency {tot.get('efficiency', 0):.0%}"),
            ("Design occupant load", f"{occ.get('load', 0)} persons (IBC Table 1004.5)"),
            ("Rooms", str(tot.get("rooms", 0)))]
    for k_, v_ in data:
        y += 5.2
        c.line((x, y + 1.6), (x + colw, y + 1.6), 0.1, FAINT)
        c.text((x, y), k_, 2.0, color=THIN)
        c.text((x + 34, y), v_ if text_width(v_, 2.1) < colw - 36 else v_[:int((colw - 36) / 1.1)] + "…", 2.1)
    y += 11
    score = review.get("score", {})
    c.text((x, y), "CODE REVIEW (INDICATIVE)", 2.6, True)
    y += 6
    chips = [("PASS", score.get("pass", 0), "#15803d"), ("REVIEW", score.get("warn", 0), "#b45309"),
             ("FAIL", score.get("fail", 0), "#b91c1c")]
    for i, (label, n, col) in enumerate(chips):
        cx = x + i * (colw / 3)
        c.rect(cx, y - 4, colw / 3 - 2, 9, "#fff", col, 0.35)
        c.text((cx + 3, y + 2.4), str(n), 5, True, color=col)
        c.text((cx + 12, y + 1.6), label, 2.0, True, color=col)
    y += 9
    issues = [ch for ch in review.get("checks", []) if ch["status"] in ("fail", "warn")][:5]
    for ch in issues:
        y += 4.4
        col = "#b91c1c" if ch["status"] == "fail" else "#b45309"
        c.circle((x + 1, y - 0.7), 0.9, col, None)
        line = f"{ch['title']} — {ch['reference']}"
        c.text((x + 3.5, y), line if text_width(line, 1.9) < colw - 4 else line[:int((colw - 4) / 1.0)] + "…", 1.9)
    if not issues:
        y += 4.4
        c.text((x, y), "All screened requirements pass.", 2.0, color="#15803d")
    y += 11
    c.text((x, y), "DRAWING INDEX", 2.6, True)
    y += 2
    for num, title in [(number, "Cover sheet, project data and code summary")] + index:
        y += 4.6
        c.line((x, y + 1.5), (x + colw, y + 1.5), 0.1, FAINT)
        c.text((x, y), num, 2.1, True)
        c.text((x + 18, y), title, 2.1)
    frame(c, meta, number, "Cover sheet", "NTS")
    return Sheet(number, "Cover sheet", "cover", c, "NTS")


STATUS_COLOURS = {"pass": "#15803d", "warn": "#b45309", "fail": "#b91c1c", "info": "#475569"}
STATUS_LABELS = {"pass": "PASS", "warn": "REVIEW", "fail": "FAIL", "info": "INFO"}


def code_sheet(review: dict, meta: Meta, number: str = "G-002") -> Sheet:
    """The code analysis sheet: occupancy, loads and every screened clause with its measured value."""
    c = Canvas(W, H)
    ax0, ay0, ax1, ay1 = AREA
    ay1 += 16
    occ, tot = review.get("occupancy", {}), review.get("totals", {})
    c.text((ax0, ay0 + 6), "CODE ANALYSIS", 5, True)
    c.text((ax0, ay0 + 12), f"{review.get('code', '')} — indicative design-stage screen from the model geometry", 2.4, color=THIN)
    facts = [("OCCUPANCY", f"{occ.get('group', '')}", occ.get("name", "").split("—")[-1].strip()),
             ("CONSTRUCTION", occ.get("construction", "").split(" (")[0], "assumed, confirm with structural"),
             ("OCCUPANT LOAD", str(occ.get("load", 0)), "persons, IBC Table 1004.5"),
             ("GROSS AREA", f"{tot.get('gia', 0):,.0f} m²", f"{tot.get('gia_sf', 0):,} sf over {tot.get('storeys', 1)} storeys"),
             ("SPRINKLERS", "None", "unsprinklered limits applied")]
    cw = (ax1 - ax0) / len(facts)
    for i, (k, v, sub) in enumerate(facts):
        x = ax0 + i * cw
        c.rect(x, ay0 + 16, cw - 3, 17, "#f8fafc", "#cbd5e1", 0.2)
        c.text((x + 3, ay0 + 21), k, 1.8, True, color=THIN)
        c.text((x + 3, ay0 + 27.5), v, 4.2, True)
        c.text((x + 3, ay0 + 31.2), sub[:48], 1.7, color=THIN)
    cols = [("STATUS", 18, "start"), ("CATEGORY", 24, "start"), ("CLAUSE", 34, "start"), ("CHECK", 58, "start"),
            ("MEASURED", 76, "start"), ("REQUIRED", 64, "start")]
    y = ay0 + 44
    total = sum(w for _, w, _ in cols)
    c.rect(ax0, y, total, 5, "#1f2937", None)
    cx = ax0
    for name, w, _ in cols:
        c.text((cx + 1.4, y + 3.5), name, 1.8, True, color="#fff")
        cx += w
    y += 5
    for i, ch in enumerate(review.get("checks", [])):
        if y > ay1 - 30:
            c.text((ax0, y + 4), "… continued in the review report (review.md).", 1.9, color=THIN)
            break
        row_h = 5.6
        if i % 2:
            c.rect(ax0, y, total, row_h, "#f6f6f4", None)
        col = STATUS_COLOURS.get(ch["status"], INK)
        c.rect(ax0 + 1.2, y + 1.1, 14, 3.4, col, None)
        c.text((ax0 + 8.2, y + 3.6), STATUS_LABELS.get(ch["status"], ""), 1.7, True, "middle", "#fff")
        vals = [ch["category"], ch["reference"], ch["title"], ch["value"], ch["target"]]
        cx = ax0 + cols[0][1]
        for (name, w, _), val in zip(cols[1:], vals):
            s = str(val)
            while text_width(s, 1.9) > w - 2 and len(s) > 3:
                s = s[:-2] + "…"
            c.text((cx + 1.4, y + 3.8), s, 1.9, name == "CHECK")
            cx += w
        y += row_h
    c.line((ax0, y), (ax0 + total, y), 0.3, INK)
    y = max(y + 8, ay1 - 20)
    c.text((ax0, y), "ASSUMPTIONS", 2.2, True)
    for i, a in enumerate(review.get("assumptions", [])):
        c.text((ax0, y + 4 + i * 3.4), f"{i + 1}. {a}", 1.9, color="#333")
    frame(c, meta, number, "Code analysis", "NTS")
    return Sheet(number, "Code analysis", "code", c, "NTS")


def drawing_set(spec: BuildingSpec, review: dict, meta: Meta) -> list[Sheet]:
    has_walls = any(isinstance(e, Wall) for e in spec.elements)
    cut = section_line(spec) if has_walls else None
    sheets: list[Sheet] = []
    plan_levels = [l for l in spec.levels if any(level_of(e) == l.id for e in spec.elements)]
    for i, level in enumerate(plan_levels):
        sheets.append(plan_sheet(spec, level.id, review, meta, f"A-{101 + i}", i + 1, cut))
    if has_walls:
        sheets.append(elevation_sheet(spec, meta, "A-201"))
        sheets.append(section_sheet(spec, review, meta, "A-301"))
    sheets += schedule_sheets(spec, review, meta, 601)
    code = code_sheet(review, meta)
    index = [(code.number, code.title)] + [(s.number, s.title) for s in sheets]
    return [cover_sheet(spec, review, meta, index), code] + sheets
