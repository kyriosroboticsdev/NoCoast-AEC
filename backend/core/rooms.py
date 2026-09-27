"""Room geometry shared by every derivation pass: the derived walls of a room, picking one of them by
compass side or a nearby point, and placing a w × d piece inside a room against a wall or in its middle.

Catalogue fixtures, custom shapes and library bricks (core/derive_bricks.py) are all placed with
`place_piece`, so they land the same way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point as ShpPoint, Polygon

from schemas.design import Pt, RoomDef, Side

SIDE_ORDER: tuple[Side, ...] = ("S", "E", "W", "N")
CLEAR = 0.15           # fixtures and stairs keep this far from wall centre lines
NEAR_MAX = 3.0         # `near` points further than this from every candidate wall are rejected (a bulging arc wall sits ~2 m from a point inside the room)


class DesignError(ValueError):
    """The design cannot be built; the message is meant for the model."""


@dataclass
class WallSeg:
    """A derived wall: straight (`path` has two points) or faceted along an arc."""

    id: str
    level: str
    path: list[Pt]
    external: bool
    rooms: tuple[str, ...]           # one room (exterior), two (partition), none (free-standing)
    side: Side | None                # exterior: compass direction the outside faces
    arc: bool = False
    radius: float | None = None
    height: float | None = None      # free-standing walls may be lower than the storey
    openings: list[tuple[float, float, str]] = field(default_factory=list)  # (offset, width, id)
    line: LineString = field(default=None, repr=False)

    def __post_init__(self):
        self.line = LineString(self.path)

    @property
    def start(self) -> Pt:
        return self.path[0]

    @property
    def end(self) -> Pt:
        return self.path[-1]

    @property
    def length(self) -> float:
        return self.line.length

    @property
    def straight(self) -> bool:
        return not self.arc and len(self.path) == 2

    @property
    def horizontal(self) -> bool:
        return abs(self.end[1] - self.start[1]) <= abs(self.end[0] - self.start[0])

    @property
    def mid(self) -> Pt:
        p = self.line.interpolate(0.5, normalized=True)
        return (r2(p.x), r2(p.y))

    def unit(self) -> Pt:
        (ax, ay), (bx, by) = self.start, self.end
        d = math.dist(self.start, self.end) or 1.0
        return ((bx - ax) / d, (by - ay) / d)

    def inward(self, poly: Polygon) -> Pt:
        """Unit normal pointing into `poly` (the room this wall is looked at from)."""
        ux, uy = self.unit()
        mx, my = self.mid
        for nx, ny in ((-uy, ux), (uy, -ux)):
            if poly.contains(ShpPoint(mx + nx * 0.05, my + ny * 0.05)):
                return (nx, ny)
        return (-uy, ux)


@dataclass
class RoomInfo:
    room: RoomDef
    polygon: Polygon
    exterior: dict[Side, list[WallSeg]]
    partitions: dict[str, list[WallSeg]]  # neighbour id -> walls shared with it
    open_sides: list[Side] = field(default_factory=list)

    @property
    def sides(self) -> list[Side]:
        return [s for s in SIDE_ORDER if self.exterior.get(s)]

    @property
    def neighbours(self) -> list[str]:
        return sorted(self.partitions)

    @property
    def walls(self) -> list[WallSeg]:
        out = [w for ws in self.exterior.values() for w in ws]
        seen = set()
        for ws in self.partitions.values():
            for w in ws:
                if w.id not in seen:
                    out.append(w)
                    seen.add(w.id)
        return out


def r2(v: float) -> float:
    return round(v, 2)


def side_name(side: Side) -> str:
    return {"N": "north", "S": "south", "E": "east", "W": "west"}[side]


def compass(nx: float, ny: float) -> Side:
    """Nearest compass direction of a (normal) vector."""
    ang = math.degrees(math.atan2(ny, nx)) % 360
    if 45 <= ang < 135:
        return "N"
    if 135 <= ang < 225:
        return "W"
    if 225 <= ang < 315:
        return "S"
    return "E"


def _same_line(walls: list[WallSeg]) -> bool:
    """All straight walls lie on one line (within 1 cm)."""
    base = walls[0]
    ux, uy = base.unit()
    for w in walls[1:]:
        if w.arc:
            return False
        vx, vy = w.unit()
        if abs(ux * vy - uy * vx) > 1e-6:
            return False
        # Perpendicular distance of w's start from the base line.
        if abs((w.start[0] - base.start[0]) * uy - (w.start[1] - base.start[1]) * ux) > 0.01:
            return False
    return True


def pick_wall(candidates: list[WallSeg], near: Pt | None, side: Side | None, what: str, room: RoomDef | None,
          sides_available: list[Side] | None = None, poly: Polygon | None = None) -> tuple[WallSeg, float | None]:
    """The wall an item goes on: by a nearby point, by compass side, or the longest. Returns the wall
    and, for `near`, the fraction along it (else None = use the item's own `at`). With `poly` (the room
    looked at from), a wall's side is the direction its far face points seen from that room, so partitions
    have a side too."""
    label = f"room '{room.id}'" if room else "the design"
    if not candidates:
        raise DesignError(f"{what}: {label} has no wall to put it on")

    def side_of(w: WallSeg) -> Side | None:
        if poly is None:
            return w.side
        ix, iy = w.inward(poly)
        return compass(-ix, -iy)
    if near is not None:
        pt = ShpPoint(near)
        best = min(candidates, key=lambda w: w.line.distance(pt))
        dist = best.line.distance(pt)
        if dist > NEAR_MAX:
            opts = "; ".join(f"{w.id} (near {w.mid})" for w in candidates[:8])
            raise DesignError(f"{what}: near={list(near)} is {dist:.1f} m from every wall of {label}; walls: {opts}")
        at = best.line.project(pt, normalized=True)
        return best, min(max(at, 0.02), 0.98)
    if side is not None:
        on_side = [w for w in candidates if side_of(w) == side]
        if not on_side:
            have = sides_available if sides_available is not None else sorted({s for s in (side_of(w) for w in candidates) if s})
            if poly is None:
                raise DesignError(f"{what}: {label} has no exterior wall on side {side}; "
                                  f"its exterior sides are {', '.join(have) or 'none'}")
            raise DesignError(f"{what}: {label} has no wall on side {side}; its walls face {', '.join(have) or 'none'}")
        # Several pieces of one straight edge (a side split by different neighbours) are not ambiguous;
        # two separate edges facing the same way (an L-shape) are.
        if len(on_side) > 1 and not all(w.arc for w in on_side) and not _same_line(on_side):
            pts = " or ".join(f"near {list(w.mid)}" for w in on_side)
            raise DesignError(f"{what}: {label} has {len(on_side)} walls facing {side}; say which with near:[x, y] ({pts})")
        return max(on_side, key=lambda w: w.length), None
    return max(candidates, key=lambda w: w.length), None


def exterior_walls(info: RoomInfo) -> list[WallSeg]:
    return [w for s in SIDE_ORDER for w in info.exterior.get(s, [])]


def fits(poly: Polygon, footprint: list[Pt]) -> bool:
    return poly.buffer(0.02).contains(Polygon(footprint))


def rect_at(cx: float, cy: float, w: float, d: float, angle: float) -> list[Pt]:
    """Corners of a w×d rectangle centred at (cx, cy), its depth axis along `angle` (radians)."""
    c, s = math.cos(angle), math.sin(angle)
    out = []
    for px, py in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
        out.append((cx + px * c - py * s, cy + px * s + py * c))
    return out


def place_piece(what: str, room: RoomDef, info: RoomInfo, side: str, near: Pt | None, at: float, w: float, d: float) -> tuple[Pt, float]:
    """Where a w × d footprint goes inside a room — against the wall named by `near`/`side`, or in the
    middle — and which way it then faces (degrees; its back to the wall). Shared by catalogue fixtures
    and model-composed custom shapes so both are placed the same way."""
    poly = info.polygon
    x0, y0, x1, y1 = room.box
    rw, rd = x1 - x0, y1 - y0
    too_small = DesignError(f"{what}: room '{room.id}' is too small ({rw:.1f} x {rd:.1f} m) for a {w:.1f} x {d:.1f} m piece")

    if near is None and side == "center":
        c = poly.centroid if poly.contains(poly.centroid) else poly.representative_point()
        inner = poly.buffer(-CLEAR, join_style="mitre")  # keep CLEAR from every wall, as against-the-wall pieces do
        if inner.is_empty or not fits(inner, rect_at(c.x, c.y, w, d, 0.0)):
            raise too_small
        return (r2(c.x), r2(c.y)), 0.0

    wall, picked_at = pick_wall(info.walls, near, None if side == "center" else side, what, room, None, poly)
    at = at if picked_at is None else picked_at
    if wall.length < w + 2 * CLEAR:
        raise too_small
    ux, uy = wall.unit()
    ix, iy = wall.inward(poly)
    along = CLEAR + w / 2 + at * (wall.length - 2 * CLEAR - w)
    if wall.arc:
        p = wall.line.interpolate(along)
        # Local tangent of the faceted wall at that point.
        q = wall.line.interpolate(min(wall.length, along + 0.1))
        ux, uy = (q.x - p.x), (q.y - p.y)
        n = math.hypot(ux, uy) or 1.0
        ux, uy = ux / n, uy / n
        ix, iy = (-uy, ux) if poly.contains(ShpPoint(p.x - uy * 0.1, p.y + ux * 0.1)) else (uy, -ux)
        bx, by = p.x, p.y
    else:
        bx, by = wall.start[0] + ux * along, wall.start[1] + uy * along
    cx, cy = bx + ix * (CLEAR + d / 2), by + iy * (CLEAR + d / 2)
    rot = (math.degrees(math.atan2(iy, ix)) - 90) % 360
    if not fits(poly, rect_at(cx, cy, w, d, math.radians(rot))):
        raise DesignError(f"{what}: a {w:.1f} x {d:.1f} m piece against wall {wall.id} does not fit inside room '{room.id}'")
    return (r2(cx), r2(cy)), r2(rot)
