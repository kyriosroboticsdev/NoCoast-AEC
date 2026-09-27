"""Floor plans as DXF, for the CAD side of the office: AutoCAD, Rhino, Vectorworks, Revit links.

Model space, in metres, one plan per storey laid out left to right (or a single storey on its own),
drawn from the same spec as the PDF set so the marks, room numbers and areas agree. Layers follow the
US National CAD Standard / AIA layer guidelines, so an office's own layer states and plot styles pick
them up:

    A-WALL        cut wall outlines          A-WALL-PATT  wall poché (solid hatch)
    A-DOOR        leaves and swings          A-DOOR-IDEN  door marks (D101…)
    A-GLAZ        window frames and glass    A-GLAZ-IDEN  window marks (W101…)
    A-FLOR-STRS   flights, treads, arrows    A-FLOR-HRAL  railings and balustrades
    A-FLOR-FIXT   sanitary, kitchen, fitted  A-EQPM       equipment and library assets
    S-COLS        columns                    S-GRID       structural grid and bubbles
    A-AREA        room boundaries (closed)   A-AREA-IDEN  room name, number, area
    A-ANNO-DIMS   dimension strings          A-ANNO-TTLB  plan titles

Text is sized to plot at 2.5 mm at 1:100.
"""

from __future__ import annotations

import io
import math

import ezdxf
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import Polygon
from shapely.ops import unary_union

from core.draw.sheets import (_fixture_outline, _grid, _openings, _pieces, _stair_outline, extent, level_of, marks,
                              outward, spaces_union)
from schemas.bim import Asset, BuildingSpec, Column, CustomFixture, Door, Fixture, Railing, Space, Stair, Wall, Window

LAYERS = {  # name: (ACI colour, lineweight in 1/100 mm, linetype, description)
    "A-WALL": (7, 50, "Continuous", "Walls, cut"),
    "A-WALL-PATT": (8, 0, "Continuous", "Wall poché"),
    "A-DOOR": (2, 25, "Continuous", "Doors: leaves and swings"),
    "A-DOOR-IDEN": (2, 18, "Continuous", "Door marks"),
    "A-GLAZ": (4, 25, "Continuous", "Glazing: frames and glass"),
    "A-GLAZ-IDEN": (4, 18, "Continuous", "Window marks"),
    "A-FLOR-STRS": (3, 25, "Continuous", "Stairs"),
    "A-FLOR-STRS-BELW": (3, 18, "DASHED", "Stair flight arriving from below"),
    "A-FLOR-HRAL": (3, 35, "Continuous", "Railings and balustrades"),
    "A-FLOR-FIXT": (9, 18, "Continuous", "Sanitary, kitchen and fitted furniture"),
    "A-EQPM": (6, 18, "DASHED", "Equipment and assets"),
    "S-COLS": (1, 35, "Continuous", "Columns"),
    "S-GRID": (8, 13, "CENTER", "Structural grid"),
    "S-GRID-IDEN": (8, 18, "Continuous", "Grid bubbles"),
    "A-AREA": (5, 13, "Continuous", "Room boundaries"),
    "A-AREA-IDEN": (7, 18, "Continuous", "Room name, number and area"),
    "A-ANNO-DIMS": (1, 13, "Continuous", "Dimensions"),
    "A-ANNO-TTLB": (7, 35, "Continuous", "Plan titles"),
}
TEXT = 0.25            # m: 2.5 mm at 1:100
GAP = 15.0             # m between storeys laid side by side
DIMSTYLE = "NC-MM-100"


def _new_doc() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2010", setup=True, units=ezdxf.units.M)
    doc.header["$MEASUREMENT"] = 1
    for name, (color, lw, ltype, desc) in LAYERS.items():
        layer = doc.layers.add(name, color=color, linetype=ltype)
        layer.dxf.lineweight = lw
        layer.description = desc
    style = doc.dimstyles.duplicate_entry("EZ_M_100_H25_CM", DIMSTYLE)
    style.dxf.dimlfac = 1000          # model in metres, dimensions read in millimetres
    style.dxf.dimdec = 0
    style.dxf.dimpost = ""
    return doc


class _Plan:
    """One storey drawn into model space, shifted by `dx` so storeys sit side by side."""

    def __init__(self, doc, spec: BuildingSpec, review: dict, level_id: str, dx: float):
        self.msp, self.spec, self.level_id, self.dx = doc.modelspace(), spec, level_id, dx
        self.rooms = {r["id"]: r for r in review.get("rooms", [])}
        self.tag = marks(spec)
        self.els = [e for e in spec.elements if level_of(e) == level_id]
        self.walls = [e for e in self.els if isinstance(e, Wall)]

    def p(self, pt) -> tuple[float, float]:
        return (pt[0] + self.dx, pt[1])

    def poly(self, pts, layer: str, closed: bool = True) -> None:
        self.msp.add_lwpolyline([self.p(q) for q in pts], close=closed, dxfattribs={"layer": layer})

    def line(self, a, b, layer: str) -> None:
        self.msp.add_line(self.p(a), self.p(b), dxfattribs={"layer": layer})

    def text(self, s: str, at, layer: str, height: float = TEXT, align=TextEntityAlignment.MIDDLE_CENTER) -> None:
        self.msp.add_text(s, height=height, dxfattribs={"layer": layer, "style": "OpenSans"}).set_placement(self.p(at), align=align)

    def draw(self) -> None:
        self.rooms_and_tags()
        self.walls_cut()
        self.openings()
        self.stairs()
        self.fittings()
        self.grid_and_dims()
        self.title()

    def rooms_and_tags(self) -> None:
        for e in self.els:
            if not isinstance(e, Space) or len(e.outline) < 3:
                continue
            self.poly(e.outline, "A-AREA")
            poly = Polygon(e.outline)
            c = poly.centroid if poly.contains(poly.centroid) else poly.representative_point()
            r = self.rooms.get(e.id)
            self.text((e.name or e.id).upper(), (c.x, c.y + TEXT * 0.9), "A-AREA-IDEN")
            if r:
                self.text(str(r["number"]), (c.x, c.y - TEXT * 0.6), "A-AREA-IDEN", TEXT * 0.9)
                self.text(f"{r['area']:.1f} m²", (c.x, c.y - TEXT * 1.9), "A-AREA-IDEN", TEXT * 0.8)

    def walls_cut(self) -> None:
        by_wall = _openings(self.spec)
        pieces = []
        for w in self.walls:
            pieces += _pieces(w, [(o.offset, o.offset + o.width) for o in by_wall.get(w.id, [])])
        if not pieces:
            return
        merged = unary_union(pieces)
        for poly in getattr(merged, "geoms", [merged]):
            if poly.is_empty or not isinstance(poly, Polygon):
                continue
            rings = [list(poly.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in poly.interiors]
            hatch = self.msp.add_hatch(color=8, dxfattribs={"layer": "A-WALL-PATT"})
            for i, ring in enumerate(rings):
                hatch.paths.add_polyline_path([self.p(q) for q in ring], is_closed=True, flags=1 if i == 0 else 0)
                self.poly(ring, "A-WALL")

    def openings(self) -> None:
        by_wall = _openings(self.spec)
        inside = spaces_union(self.spec, self.level_id)
        for w in self.walls:
            if len(w.axis) != 2:
                continue
            (ax, ay), (bx, by) = w.axis
            L = w.length or 1
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = -uy, ux
            out = outward(w, inside) if w.external else (nx, ny)
            t = w.thickness
            for o in by_wall.get(w.id, []):
                s0 = (ax + ux * o.offset, ay + uy * o.offset)
                s1 = (ax + ux * (o.offset + o.width), ay + uy * (o.offset + o.width))
                off = lambda q, k: (q[0] + nx * k, q[1] + ny * k)
                mark = self.tag.get(o.id, "")
                if isinstance(o, Window):
                    for k in (-t / 2, t / 2):
                        self.line(off(s0, k), off(s1, k), "A-GLAZ")
                    for k in (-t * 0.12, t * 0.12):
                        self.line(off(s0, k), off(s1, k), "A-GLAZ")
                    for q in (s0, s1):
                        self.line(off(q, -t / 2), off(q, t / 2), "A-GLAZ")
                    mid = ((s0[0] + s1[0]) / 2 + out[0] * (t / 2 + 0.45), (s0[1] + s1[1]) / 2 + out[1] * (t / 2 + 0.45))
                    self.text(mark, mid, "A-GLAZ-IDEN", TEXT * 0.8)
                    continue
                sw = (-out[0], -out[1]) if w.external else (nx, ny)
                self.door(o, s0, s1, (ux, uy), sw, t)
                mid = ((s0[0] + s1[0]) / 2 - sw[0] * (t / 2 + 0.5), (s0[1] + s1[1]) / 2 - sw[1] * (t / 2 + 0.5))
                self.text(mark, mid, "A-DOOR-IDEN", TEXT * 0.8)

    def door(self, o: Door, s0, s1, u, sw, t: float) -> None:
        ux, uy = u
        if o.kind in ("garage", "roller"):
            self.line(s0, s1, "A-DOOR")
            self.line((s0[0] + sw[0] * 0.6, s0[1] + sw[1] * 0.6), (s1[0] + sw[0] * 0.6, s1[1] + sw[1] * 0.6), "A-DOOR")
            return
        if o.kind == "sliding":
            half = o.width / 2 + 0.05
            nx, ny = -uy, ux
            for a0, k in ((0.0, t * 0.15), (o.width - half, -t * 0.15)):
                base = (s0[0] + ux * a0 + nx * k, s0[1] + uy * a0 + ny * k)
                self.poly([base, (base[0] + ux * half, base[1] + uy * half),
                           (base[0] + ux * half + nx * 0.04, base[1] + uy * half + ny * 0.04),
                           (base[0] + nx * 0.04, base[1] + ny * 0.04)], "A-DOOR")
            return
        if o.kind == "revolving":
            c = ((s0[0] + s1[0]) / 2, (s0[1] + s1[1]) / 2)
            self.msp.add_circle(self.p(c), o.width / 2, dxfattribs={"layer": "A-DOOR"})
            r = o.width / 2
            self.line((c[0] - ux * r, c[1] - uy * r), (c[0] + ux * r, c[1] + uy * r), "A-DOOR")
            self.line((c[0] + uy * r, c[1] - ux * r), (c[0] - uy * r, c[1] + ux * r), "A-DOOR")
            return
        leaves = [(s0, 1, o.width)] if o.kind == "single" else [(s0, 1, o.width / 2), (s1, -1, o.width / 2)]
        for hinge, dirn, r in leaves:
            tip = (hinge[0] + sw[0] * r, hinge[1] + sw[1] * r)
            self.line(hinge, tip, "A-DOOR")
            a_tip = math.degrees(math.atan2(sw[1], sw[0]))
            a_shut = math.degrees(math.atan2(uy * dirn, ux * dirn))
            start, end = (a_tip, a_shut) if (a_shut - a_tip) % 360 <= 180 else (a_shut, a_tip)
            self.msp.add_arc(self.p(hinge), r, start, end, dxfattribs={"layer": "A-DOOR"})

    def stairs(self) -> None:
        levels = {l.id: l for l in self.spec.levels}
        for s in self.spec.elements:
            if not isinstance(s, Stair) or self.level_id not in (s.level, s.to_level):
                continue
            here = s.level == self.level_id
            layer = "A-FLOR-STRS" if here else "A-FLOR-STRS-BELW"
            rise = s.rise or levels[s.level].height
            run, (ux, uy), (nx, ny), outline = _stair_outline(s, rise)
            self.poly(outline, layer)
            hw = s.width / 2
            for i in range(1, s.steps(rise)):
                x, y = s.position[0] + ux * s.going * i, s.position[1] + uy * s.going * i
                self.line((x + nx * hw, y + ny * hw), (x - nx * hw, y - ny * hw), layer)
            end = (s.position[0] + ux * (run - 0.15), s.position[1] + uy * (run - 0.15))
            self.line(s.position, end, layer)
            for side in (0.4, -0.4):
                a = math.atan2(uy, ux) + math.pi + side
                self.line(end, (end[0] + 0.2 * math.cos(a), end[1] + 0.2 * math.sin(a)), layer)
            label = f"UP {s.steps(rise)}R" if here else "DN"
            self.text(label, (s.position[0] - ux * 0.35, s.position[1] - uy * 0.35), layer, TEXT * 0.8)

    def fittings(self) -> None:
        for e in self.els:
            if isinstance(e, (Fixture, CustomFixture)):
                self.poly(_fixture_outline(e), "A-FLOR-FIXT")
            elif isinstance(e, Asset) and e.ifc_class not in ("IfcWall", "IfcSlab", "IfcBeam", "IfcColumn"):
                self.poly(_fixture_outline(e), "A-EQPM")
            elif isinstance(e, Column):
                hw, hd = e.width / 2, e.depth / 2
                px, py = e.position
                pts = [(px - hw, py - hd), (px + hw, py - hd), (px + hw, py + hd), (px - hw, py + hd)]
                self.poly(pts, "S-COLS")
                hatch = self.msp.add_hatch(color=1, dxfattribs={"layer": "S-COLS"})
                hatch.paths.add_polyline_path([self.p(q) for q in pts], is_closed=True)
            elif isinstance(e, Railing):
                self.poly(e.path, "A-FLOR-HRAL", closed=False)

    def grid_and_dims(self) -> None:
        x0, y0, x1, y1 = extent(self.spec)
        ext = [w for w in self.spec.elements if isinstance(w, Wall) and w.external]
        gx = _grid([p[0] for w in ext for p in w.axis if abs(w.axis[0][0] - w.axis[-1][0]) < 0.01])[:12]
        gy = _grid([p[1] for w in ext for p in w.axis if abs(w.axis[0][1] - w.axis[-1][1]) < 0.01])[:12]
        bubble = 0.5
        for i, x in enumerate(gx):
            self.line((x, y0 - 1.0), (x, y1 + 2.0), "S-GRID")
            self.msp.add_circle(self.p((x, y1 + 2.0 + bubble)), bubble, dxfattribs={"layer": "S-GRID-IDEN"})
            self.text(str(i + 1), (x, y1 + 2.0 + bubble), "S-GRID-IDEN", TEXT * 1.2)
        for i, y in enumerate(reversed(gy)):
            self.line((x0 - 2.0, y), (x1 + 1.0, y), "S-GRID")
            self.msp.add_circle(self.p((x0 - 2.0 - bubble, y)), bubble, dxfattribs={"layer": "S-GRID-IDEN"})
            self.text(chr(ord("A") + i), (x0 - 2.0 - bubble, y), "S-GRID-IDEN", TEXT * 1.2)

        here = [w for w in self.walls if w.external]
        xs = _grid([p[0] for w in here for p in w.axis]) if here else [x0, x1]
        ys = _grid([p[1] for w in here for p in w.axis]) if here else [y0, y1]
        attribs = {"layer": "A-ANNO-DIMS"}
        for a, b in zip(xs, xs[1:]):
            self.msp.add_linear_dim(base=self.p((a, y0 - 2.2)), p1=self.p((a, y0)), p2=self.p((b, y0)),
                                    dimstyle=DIMSTYLE, dxfattribs=attribs).render()
        self.msp.add_linear_dim(base=self.p((xs[0], y0 - 3.2)), p1=self.p((xs[0], y0)), p2=self.p((xs[-1], y0)),
                                dimstyle=DIMSTYLE, dxfattribs=attribs).render()
        for a, b in zip(ys, ys[1:]):
            self.msp.add_linear_dim(base=self.p((x1 + 2.2, a)), p1=self.p((x1, a)), p2=self.p((x1, b)), angle=90,
                                    dimstyle=DIMSTYLE, dxfattribs=attribs).render()
        self.msp.add_linear_dim(base=self.p((x1 + 3.2, ys[0])), p1=self.p((x1, ys[0])), p2=self.p((x1, ys[-1])), angle=90,
                                dimstyle=DIMSTYLE, dxfattribs=attribs).render()

    def title(self) -> None:
        x0, y0, _, _ = extent(self.spec)
        level = next(l for l in self.spec.levels if l.id == self.level_id)
        self.text(f"{level.name.upper()} PLAN", (x0, y0 - 5.0), "A-ANNO-TTLB", TEXT * 2, TextEntityAlignment.LEFT)
        self.text(f"FFL {level.elevation or 0:+.3f}  ·  1:100  ·  {self.spec.building.name}", (x0, y0 - 5.8),
                  "A-ANNO-TTLB", TEXT, TextEntityAlignment.LEFT)


def plans_dxf(spec: BuildingSpec, review: dict, level: str | None = None) -> bytes:
    """Every storey's plan side by side in one DXF, or just `level`'s."""
    doc = _new_doc()
    doc.header["$PROJECTNAME"] = spec.building.name[:255]
    x0, y0, x1, y1 = extent(spec)
    step = (x1 - x0) + GAP
    ids = [level] if level else [l.id for l in spec.levels]
    for i, lid in enumerate(ids):
        _Plan(doc, spec, review, lid, i * step).draw()
    doc.set_modelspace_vport(height=(y1 - y0) + 12, center=((x0 + x1) / 2 + step * (len(ids) - 1) / 2, (y0 + y1) / 2 - 2))
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode("utf-8")
