"""Small geometric recipes shared by the template planner and the mock LLM: turn a rectangular room
into an L or give it a curved wall, place an extra room beside the house, lay out a pergola or a
garden wall. Deterministic and deliberately plain — they exist so tests and headless demos can
exercise polygons, arcs, open rooms and free elements without a real model."""

from __future__ import annotations

from shapely.geometry import box as shp_box
from shapely.ops import unary_union

from schemas.design import Design, RoomDef, Side

Pt = tuple[float, float]


def footprint_bounds(design: Design, level: str) -> tuple[float, float, float, float] | None:
    polys = [r.polygon() for r in design.rooms_on(level) if r.placed]
    if not polys:
        return None
    return unary_union(polys).bounds


def free_side(design: Design, room: RoomDef, depth: float) -> Side | None:
    """An exterior side of `room` where a `depth` deep strip along the whole side hits no other room."""
    x0, y0, x1, y1 = room.box
    others = [r.polygon() for r in design.rooms_on(room.level) if r.id != room.id and r.placed]
    strips = {"S": shp_box(x0, y0 - depth, x1, y0), "N": shp_box(x0, y1, x1, y1 + depth),
              "E": shp_box(x1, y0, x1 + depth, y1), "W": shp_box(x0 - depth, y0, x0, y1)}
    for side in ("S", "N", "E", "W"):
        if all(strips[side].intersection(o).area < 0.01 for o in others):
            return side
    return None


def l_shape(design: Design, room: RoomDef, depth: float = 2.0) -> list | None:
    """The room's rectangle plus a half-width wing sticking `depth` metres out of a free side."""
    if not room.is_rect:
        return None
    side = free_side(design, room, depth)
    if side is None:
        return None
    x0, y0, x1, y1 = room.box
    mx, my = round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)
    if side == "S":
        return [[x0, y0 - depth], [mx, y0 - depth], [mx, y0], [x1, y0], [x1, y1], [x0, y1]]
    if side == "N":
        return [[x0, y0], [x1, y0], [x1, y1], [mx, y1], [mx, y1 + depth], [x0, y1 + depth]]
    if side == "E":
        return [[x0, y0], [x1, y0], [x1 + depth, y0], [x1 + depth, my], [x1, my], [x1, y1], [x0, y1]]
    return [[x0 - depth, y0], [x1, y0], [x1, y1], [x0, y1], [x0, my], [x0 - depth, my]]


def curved_side(design: Design, room: RoomDef, side: Side | None = None, bulge: float = 1.0) -> list | None:
    """The room's rectangle with one exterior side replaced by an arc bulging `bulge` metres outward."""
    if not room.is_rect:
        return None
    side = side if side and free_side(design, room, bulge) == side else free_side(design, room, bulge)
    if side is None:
        return None
    x0, y0, x1, y1 = room.box
    mx, my = round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)
    if side == "S":
        return [{"to": [x0, y0]}, {"to": [x1, y0], "through": [mx, y0 - bulge]}, {"to": [x1, y1]}, {"to": [x0, y1]}]
    if side == "E":
        return [{"to": [x0, y0]}, {"to": [x1, y0]}, {"to": [x1, y1], "through": [x1 + bulge, my]}, {"to": [x0, y1]}]
    if side == "N":
        return [{"to": [x0, y0]}, {"to": [x1, y0]}, {"to": [x1, y1]}, {"to": [x0, y1], "through": [mx, y1 + bulge]}]
    return [{"to": [x0, y0], "through": [x0 - bulge, my]}, {"to": [x1, y0]}, {"to": [x1, y1]}, {"to": [x0, y1]}]


def beside(design: Design, level: str, width: float, depth: float, side: Side = "E") -> list[float]:
    """A rectangle of width × depth placed against the footprint on `side` (east by default)."""
    b = footprint_bounds(design, level)
    if b is None:
        return [0, 0, width, depth]
    minx, miny, maxx, maxy = b
    if side == "E":
        return [round(maxx, 2), round(miny, 2), width, depth]
    if side == "W":
        return [round(minx - width, 2), round(miny, 2), width, depth]
    if side == "N":
        return [round(minx, 2), round(maxy, 2), width, depth]
    return [round(minx, 2), round(miny - depth, 2), width, depth]


def pergola_steps(design: Design, level: str = "L1", size: float = 4.0, gap: float = 1.0) -> list[dict]:
    """A free-standing pergola: four posts, two beams and a flat roof, east of the house."""
    b = footprint_bounds(design, level)
    minx, miny, maxx, maxy = b if b else (0, 0, 0, 0)
    x0, y0 = round(maxx + gap, 2), round(miny, 2)
    x1, y1 = round(x0 + size, 2), round(y0 + size, 2)
    steps = [{"step": "element", "kind": "column", "name": f"Pergola post {i}", "level": level, "position": p, "width": 0.2, "height": 2.4}
             for i, p in enumerate(([x0 + 0.1, y0 + 0.1], [x1 - 0.1, y0 + 0.1], [x1 - 0.1, y1 - 0.1], [x0 + 0.1, y1 - 0.1]), 1)]
    steps.append({"step": "element", "kind": "beam", "name": "Pergola beam south", "level": level, "start": [x0, y0 + 0.1], "end": [x1, y0 + 0.1]})
    steps.append({"step": "element", "kind": "beam", "name": "Pergola beam north", "level": level, "start": [x0, y1 - 0.1], "end": [x1, y1 - 0.1]})
    steps.append({"step": "element", "kind": "roof", "name": "Pergola roof", "level": level, "poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "thickness": 0.1})
    return steps


def garden_wall_steps(design: Design, level: str = "L1", offset: float = 3.0, height: float = 1.8) -> list[dict]:
    """A garden wall along the south of the plot with a gate in the middle."""
    b = footprint_bounds(design, level)
    minx, miny, maxx, maxy = b if b else (0, 0, 10, 8)
    y = round(miny - offset, 2)
    return [{"step": "element", "kind": "wall", "name": "Garden wall", "level": level, "path": [[round(minx - 1, 2), y], [round(maxx + 1, 2), y]],
             "height": height, "thickness": 0.2},
            {"step": "door", "wall": "garden-wall", "at": 0.5, "kind": "double"}]


def bridge_steps(design: Design, level: str = "L1", span: float = 24.0, width: float = 3.0, clearance: float = 3.0,
                 pier_spacing: float = 8.0) -> list[dict]:
    """A footbridge with no rooms at all: piers, two girders under a deck slab, and two parapets, laid out east of
    whatever the design already holds (from the origin when it is empty). The girders hang below `clearance`,
    the deck rests on them and the parapets stand on the deck; the piers reach the girders' underside."""
    b = footprint_bounds(design, level)
    x0 = round(b[2] + 4.0, 2) if b else 0.0
    y0 = 0.0
    x1, y1 = round(x0 + span, 2), round(y0 + width, 2)
    ym = round(y0 + width / 2, 2)
    girder, deck = 0.6, 0.3
    lvl = next((l for l in design.levels if l.id == level), None)
    level_height = lvl.height if lvl else 3.0
    steps: list[dict] = []
    n = max(2, int(round(span / pier_spacing)) + 1)
    for i in range(n):
        x = round(x0 + span * i / (n - 1), 2)
        steps.append({"step": "element", "kind": "column", "name": f"Pier {i + 1}", "level": level, "position": [x, ym],
                      "width": 0.8, "height": round(clearance - girder, 2)})
    for tag, y in (("south", y0 + 0.2), ("north", y1 - 0.2)):
        steps.append({"step": "element", "kind": "beam", "name": f"Girder {tag}", "level": level, "start": [x0, round(y, 2)],
                      "end": [x1, round(y, 2)], "width": 0.3, "depth": girder, "elevation": round(max(0.0, clearance - level_height), 2)})
    steps.append({"step": "element", "kind": "slab", "name": "Bridge deck", "level": level, "thickness": deck,
                  "elevation": round(clearance + deck, 2), "poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]})
    for tag, y in (("south", y0 + 0.075), ("north", y1 - 0.075)):
        steps.append({"step": "element", "kind": "wall", "name": f"Parapet {tag}", "level": level, "path": [[x0, round(y, 2)], [x1, round(y, 2)]],
                      "height": 1.1, "thickness": 0.15, "elevation": round(clearance + deck, 2)})
    return steps


def deck_steps(design: Design, level: str = "L1", depth: float = 3.0) -> list[dict]:
    b = footprint_bounds(design, level)
    minx, miny, maxx, maxy = b if b else (0, 0, 10, 8)
    x0, x1 = round(minx, 2), round(maxx, 2)
    return [{"step": "element", "kind": "slab", "name": "Deck", "level": level, "thickness": 0.15,
             "poly": [[x0, round(miny - depth, 2)], [x1, round(miny - depth, 2)], [x1, round(miny, 2)], [x0, round(miny, 2)]]}]
