"""Plan geometry: points, polygon edges that may be arcs, and the faceting that turns them
into straight segments.

Lifted unchanged in behaviour out of the old room layer — the machinery was never
room-specific, only its callers were. Everything here is 2D and in metres; a profile drawn
with these helpers is placed in 3D by `schemas.geo.Placement`.

Polygons are counter-clockwise vertex lists. An edge ends at `to` and starts where the
previous edge ended; giving it `through` makes it a circular arc passing through that point,
which is faceted at `ARC_SEGMENT` chord length. A "band" is an open polyline thickened by a
width — a wall footprint, a ring, an annulus.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Pt = tuple[float, float]

ARC_SEGMENT = 0.25       # chord length used to facet arcs
EPS = 1e-9


def r2(v: float) -> float:
    return round(float(v), 4)


def as_point(v) -> Pt:
    """Accept [x, y], (x, y) or {"x":…, "y":…}."""
    if isinstance(v, dict):
        v = [v.get("x"), v.get("y")]
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"a plan point is [x, y]; got {v!r}")
    return (r2(v[0]), r2(v[1]))


def as_point3(v) -> tuple[float, float, float]:
    if isinstance(v, dict):
        v = [v.get("x"), v.get("y"), v.get("z", 0)]
    if isinstance(v, (list, tuple)) and len(v) == 2:
        v = [v[0], v[1], 0.0]
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise ValueError(f"a point is [x, y, z] (or [x, y]); got {v!r}")
    return (r2(v[0]), r2(v[1]), r2(v[2]))


# --- arcs -------------------------------------------------------------------

def arc_points(a: Pt, m: Pt, b: Pt, max_seg: float = ARC_SEGMENT) -> list[Pt]:
    """Points along the circular arc from `a` through `m` to `b`, excluding `a`, including `b`.
    Collinear points give just [b]."""
    ax, ay = a
    mx, my = m
    bx, by = b
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < EPS:
        return [b]
    ux = ((ax * ax + ay * ay) * (my - by) + (mx * mx + my * my) * (by - ay) + (bx * bx + by * by) * (ay - my)) / d
    uy = ((ax * ax + ay * ay) * (bx - mx) + (mx * mx + my * my) * (ax - bx) + (bx * bx + by * by) * (mx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    ta, tm, tb = (math.atan2(p[1] - uy, p[0] - ux) for p in (a, m, b))

    def ccw_span(t0: float, t1: float) -> float:
        return (t1 - t0) % (2 * math.pi)

    # Go counter-clockwise if `m` lies on the ccw way from a to b, else clockwise.
    if ccw_span(ta, tm) <= ccw_span(ta, tb):
        span = ccw_span(ta, tb)
    else:
        span = -((ta - tb) % (2 * math.pi))
    n = max(4, math.ceil(abs(span) * r / max_seg))
    pts = [(r2(ux + r * math.cos(ta + span * i / n)), r2(uy + r * math.sin(ta + span * i / n))) for i in range(1, n)]
    return pts + [b]


def arc_radius(a: Pt, m: Pt, b: Pt) -> float | None:
    """Radius of the circle through three points, or None when they are collinear."""
    d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
    if abs(d) < EPS:
        return None
    ux = ((a[0] ** 2 + a[1] ** 2) * (m[1] - b[1]) + (m[0] ** 2 + m[1] ** 2) * (b[1] - a[1]) + (b[0] ** 2 + b[1] ** 2) * (a[1] - m[1])) / d
    uy = ((a[0] ** 2 + a[1] ** 2) * (b[0] - m[0]) + (m[0] ** 2 + m[1] ** 2) * (a[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (m[0] - a[0])) / d
    return r2(math.hypot(a[0] - ux, a[1] - uy))


# --- edges ------------------------------------------------------------------

class Edge(BaseModel):
    """One edge of an outline, ending at `to` (it starts where the previous edge ended).
    A bare [x, y] is accepted and means a straight edge to that vertex."""

    to: Pt
    through: Optional[Pt] = Field(None, description="Make the edge a circular arc passing through this point")

    @field_validator("to", "through", mode="before")
    @classmethod
    def _p(cls, v):
        return None if v is None else as_point(v)

    @model_validator(mode="before")
    @classmethod
    def _shape(cls, v):
        if isinstance(v, (list, tuple)):  # bare [x, y] vertex
            return {"to": v}
        if isinstance(v, dict) and "to" not in v and "x" in v:
            d = dict(v)
            return {"to": [d.pop("x"), d.pop("y")], **d}
        if isinstance(v, dict) and "arc" in v and "through" not in v:
            d = dict(v)
            d["through"] = d.pop("arc")
            return d
        return v


def edges(raw) -> list[Edge]:
    """Coerce a loose points/edges list into Edges, so callers can accept either form."""
    if raw is None:
        return []
    if isinstance(raw, dict) and "points" in raw:
        raw = raw["points"]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("an outline is a list of points [[x, y], …]")
    return [e if isinstance(e, Edge) else Edge.model_validate(e) for e in raw]


def facet(es: list[Edge], closed: bool = True) -> list[Pt]:
    """The outline as straight-segment vertices: arcs faceted, duplicates dropped.
    For a closed outline the first vertex is not repeated at the end."""
    if not es:
        return []
    pts: list[Pt] = []

    def push(p: Pt) -> None:
        if not pts or math.dist(pts[-1], p) > 1e-6:
            pts.append(p)

    rng = range(len(es)) if closed else range(1, len(es))
    if closed:
        push(es[-1].to)
    else:
        push(es[0].to)
    for i in rng:
        prev = pts[-1]
        e = es[i]
        if e.through:
            for p in arc_points(prev, e.through, e.to):
                push(p)
        else:
            push(e.to)
    if closed and len(pts) > 1 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts.pop()
    return pts


def signed_area(pts: list[Pt]) -> float:
    n = len(pts)
    if n < 3:
        return 0.0
    return sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2


def ccw(pts: list[Pt]) -> list[Pt]:
    """Same ring, counter-clockwise."""
    return pts if signed_area(pts) >= 0 else pts[::-1]


def bounds(pts: list[Pt]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def polyline_length(pts: list[Pt]) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def circle_points(diameter: float, sides: int = 32, centre: Pt = (0.0, 0.0)) -> list[Pt]:
    r = diameter / 2
    return [(r2(centre[0] + r * math.cos(2 * math.pi * i / sides)),
             r2(centre[1] + r * math.sin(2 * math.pi * i / sides))) for i in range(sides)]


def rect_points(width: float, depth: float, centre: Pt = (0.0, 0.0)) -> list[Pt]:
    """A width x depth rectangle centred on `centre`, counter-clockwise."""
    cx, cy = centre
    w, d = width / 2, depth / 2
    return [(r2(cx - w), r2(cy - d)), (r2(cx + w), r2(cy - d)), (r2(cx + w), r2(cy + d)), (r2(cx - w), r2(cy + d))]


def band_points(pts: list[Pt], width: float, closed: bool = False) -> tuple[list[Pt], list[list[Pt]]]:
    """A polyline thickened by `width`, as (outer ring, inner rings).

    An open polyline gives a flat-ended, mitre-jointed strip — the footprint of a wall along
    its axis. A closed one gives an annulus: the ring wall of a tower, a circular parapet."""
    from shapely.geometry import LineString, Polygon

    if len(pts) < 2:
        raise ValueError("a band needs at least two points")
    if closed and math.dist(pts[0], pts[-1]) > 1e-6:
        pts = list(pts) + [pts[0]]
    geom = LineString(pts)
    poly = geom.buffer(width / 2, cap_style="flat", join_style="mitre")
    if poly.is_empty:
        raise ValueError("a band with this width has no area")
    if not isinstance(poly, Polygon):
        poly = max(poly.geoms, key=lambda g: g.area)
    outer = ccw([(r2(x), r2(y)) for x, y in poly.exterior.coords[:-1]])
    holes = [ccw([(r2(x), r2(y)) for x, y in ring.coords[:-1]])[::-1] for ring in poly.interiors]
    return outer, holes
