"""A rule-of-thumb structural check — not engineering, but enough to catch what a model forgets.

  * Room spans: a floor or roof spans the short way across a room. If the widest unsupported strip
    (between walls, beams and lines of columns running the long way) is longer than the walls' material
    allows, the room needs a beam — suggested along the long direction, with columns if the beam
    itself would be too long.
  * Beam spans: a span brick longer than its `max_span` between supports gets columns suggested.
  * Overhangs: an upper storey reaching more than 1 m past the storey below needs posts under it.

Each issue carries the brick steps that would fix it, so the fix round (or the mock) can apply them.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point as ShpPoint, Polygon
from shapely.ops import unary_union

from bricks import HOSTS, library
from core.derive import Derived
from core.rooms import r2
from core.issues import Issue
from schemas.bim import Asset, Beam, Column
from schemas.design import Design, Pt

SPAN_LIMITS = {"timber": 6.0, "masonry": 7.0, "plaster": 7.0, "stone": 7.0, "concrete": 8.0, "glass": 5.0}
DEFAULT_SPAN = 7.0
OVERHANG_MAX = 1.0
BEAM_BRICK = "steel_beam"
COLUMN_BRICK = "steel_column"
NEAR_LINE = 0.35        # a column this close to a beam's axis supports it


def span_limit(design: Design) -> float:
    return SPAN_LIMITS.get(design.wall_material or "", DEFAULT_SPAN)


def _supports(derived: Derived, level: str) -> tuple[list[tuple[float, float]], list[LineString]]:
    """Point supports (columns, structural bricks) and line supports (beams, span bricks) on a storey."""
    points, lines = [], []
    for e in derived.spec.elements:
        if getattr(e, "level", None) != level:
            continue
        if isinstance(e, Column):
            points.append(e.position)
        elif isinstance(e, Beam):
            lines.append(LineString([e.start, e.end]))
        elif isinstance(e, Asset) and e.structural and e.elevation >= -0.01:
            if HOSTS[e.host].spans:
                lines.append(_asset_line(e))
            else:
                points.append(e.position)
    return points, lines


def _asset_line(a: Asset) -> LineString:
    half = a.size[0] / 2
    c, s = math.cos(math.radians(a.rotation)), math.sin(math.radians(a.rotation))
    return LineString([(a.position[0] - c * half, a.position[1] - s * half), (a.position[0] + c * half, a.position[1] + s * half)])


def room_spans(design: Design, derived: Derived) -> list[Issue]:
    limit = span_limit(design)
    issues = []
    for room in design.rooms:
        if not room.roofed or room.id not in derived.rooms:
            continue
        poly = derived.rooms[room.id].polygon
        x0, y0, x1, y1 = poly.bounds
        along_x = (x1 - x0) >= (y1 - y0)            # the long direction; the floor spans across it
        lo, hi = (y0, y1) if along_x else (x0, x1)
        if hi - lo <= limit:
            continue
        points, lines = _supports(derived, room.level)
        inner = poly.buffer(-0.05)
        cuts = [lo, hi]
        for ln in lines:
            if not ln.intersects(inner):
                continue
            (ax, ay), (bx, by) = ln.coords[0], ln.coords[-1]
            if (abs(bx - ax) >= abs(by - ay)) == along_x:
                cuts.append((ay + by) / 2 if along_x else (ax + bx) / 2)
        for px, py in points:
            if inner.contains(ShpPoint(px, py)):
                cuts.append(py if along_x else px)
        cuts.sort()
        gap = max(b - a for a, b in zip(cuts, cuts[1:]))
        if gap <= limit + 0.01:
            continue
        issues.append(Issue("structure", "error",
                            f"{room.name} ({room.id}) spans {gap:.1f} m unsupported; {design.wall_material or 'masonry'} walls "
                            f"carry about {limit:g} m — add a beam along its long side",
                            [room.id], _beam_steps(room.id, (x0, y0, x1, y1), limit)))
    return issues


def beam_line(box: tuple[float, float, float, float], at: float = 0.5) -> tuple[Pt, Pt]:
    """A beam along the long direction of a room's bounding box, 0.1 m clear of its walls, `at` of the way across."""
    x0, y0, x1, y1 = box
    if x1 - x0 >= y1 - y0:
        y = r2(y0 + (y1 - y0) * at)
        return (r2(x0 + 0.1), y), (r2(x1 - 0.1), y)
    x = r2(x0 + (x1 - x0) * at)
    return (x, r2(y0 + 0.1)), (x, r2(y1 - 0.1))


def _beam_steps(room_id: str, box: tuple[float, float, float, float], limit: float) -> list[dict]:
    x0, y0, x1, y1 = box
    beam = library().get(BEAM_BRICK)
    n = math.ceil(min(x1 - x0, y1 - y0) / limit) - 1
    steps: list[dict] = []
    for i in range(1, n + 1):
        a, b = beam_line(box, i / (n + 1))
        length = math.dist(a, b)
        steps.append({"step": "brick", "brick": BEAM_BRICK, "id": f"beam-{room_id}" + (f"-{i}" if n > 1 else ""),
                      "start": list(a), "end": list(b)})
        if beam.max_span and length > beam.max_span:
            k = math.ceil(length / beam.max_span) - 1
            for j in range(1, k + 1):
                t = j / (k + 1)
                steps.append({"step": "brick", "brick": COLUMN_BRICK, "room": room_id,
                              "position": [r2(a[0] + (b[0] - a[0]) * t), r2(a[1] + (b[1] - a[1]) * t)]})
    return steps


def beam_spans(design: Design, derived: Derived) -> list[Issue]:
    issues = []
    for a in (e for e in derived.spec.elements if isinstance(e, Asset) and HOSTS[e.host].spans):
        brick = library().get(a.brick)
        if brick is None or not brick.max_span or a.size[0] <= brick.max_span:
            continue
        line = _asset_line(a)
        points, _ = _supports(derived, a.level)
        ts = sorted({0.0, line.length} | {line.project(ShpPoint(p)) for p in points if line.distance(ShpPoint(p)) <= NEAR_LINE})
        steps = []
        worst = 0.0
        for t0, t1 in zip(ts, ts[1:]):
            worst = max(worst, t1 - t0)
            if t1 - t0 > brick.max_span:
                k = math.ceil((t1 - t0) / brick.max_span) - 1
                for j in range(1, k + 1):
                    p = line.interpolate(t0 + (t1 - t0) * j / (k + 1))
                    steps.append({"step": "brick", "brick": COLUMN_BRICK, "level": a.level, "position": [r2(p.x), r2(p.y)]})
        if steps:
            issues.append(Issue("structure", "error", f"{a.brick} '{a.id}' spans {worst:.1f} m between supports; it carries at most "
                                                      f"{brick.max_span:g} m — add a column under it", [a.id], steps))
    return issues


def overhangs(design: Design, derived: Derived) -> list[Issue]:
    issues = []
    ordered = [l for l in design.ordered_levels() if l.index >= 0]
    for below, above in zip(ordered, ordered[1:]):
        up, down = derived.footprints.get(above.id), derived.footprints.get(below.id)
        if not up or not down:
            continue
        lower = unary_union(down)
        for piece in _pieces(unary_union(up).difference(lower.buffer(0.01))):
            depth = max(lower.distance(ShpPoint(p)) for p in piece.exterior.coords)
            if depth <= OVERHANG_MAX:
                continue
            points, _ = _supports(derived, below.id)
            if any(piece.buffer(0.3).contains(ShpPoint(p)) for p in points):
                continue
            c = piece.centroid
            far = sorted({(x, y) for x, y in piece.exterior.coords if lower.distance(ShpPoint(x, y)) > OVERHANG_MAX / 2},
                         key=lambda p: -lower.distance(ShpPoint(p)))[:4]
            steps = []
            for x, y in far:
                dx, dy = c.x - x, c.y - y
                n = math.hypot(dx, dy) or 1.0
                steps.append({"step": "brick", "brick": COLUMN_BRICK, "level": below.id,
                              "position": [r2(x + dx / n * 0.25), r2(y + dy / n * 0.25)]})
            issues.append(Issue("structure", "error", f"{above.id} overhangs {below.id} by {depth:.1f} m with nothing under it; "
                                                      f"add columns on {below.id} under the overhang", [above.id], steps))
    return issues


def _pieces(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    polys = [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    return [p for p in polys if p.area > 0.5]


def report(design: Design, derived: Derived) -> list[Issue]:
    return room_spans(design, derived) + beam_spans(design, derived) + overhangs(design, derived)
