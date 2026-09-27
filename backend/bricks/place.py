"""Where a placed brick goes: generic placement against frames.

A `Frame` is anything a brick can be placed in or on — a named plan outline with a height range on a
level. A `void` frame is a region things go inside (a space, a storey, the ground around a building);
a solid frame is a body things go on (a slab, a wall, a table, another brick). Frames know nothing about
what they are: the application that owns the model (for buildings, core/derive_bricks.py) makes them.

A `Placement` names a frame (`ref`, else a level datum) and says where in it:

  * `position` [x, y] or [x, y, z] — exact (plan coordinates; z relative to the level)
  * `side` (N/S/E/W) or `near` [x, y] — back against that side of the frame, `at` 0..1 along it
  * `start` / `end` — a path (bricks with mount "path")
  * nothing — the middle of the frame

and the brick's `mount` decides the height: resting on the frame's floor (void) or top (solid), hanging
from its ceiling or underside, or fixed to a side at the brick's `elevation`. `place` returns the pose,
the fitted parameter values and the evaluated solids, or raises PlacementError with a message meant
for the model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional, assert_never

import numpy as np
from pydantic import BaseModel, Field, field_validator
from shapely.geometry import LineString, MultiPoint, Point as ShpPoint, Polygon

from bricks.geometry import Bounds, bounds, transform
from bricks.model import Brick

Face = Literal["N", "S", "E", "W", "center"]
P2 = tuple[float, float]
P3 = tuple[float, float, float]
NEAR_MAX = 3.0       # a `near` point further than this from every side is refused
FIT_TOL = 0.02       # footprints may poke this far past a void frame's outline


class PlacementError(ValueError):
    """The placement cannot work; the message is meant for the model."""


def _point(v, dims: tuple[int, ...] = (2,)):
    if v is None:
        return None
    if isinstance(v, dict):
        v = [v.get(k) for k in ("x", "y", "z") if v.get(k) is not None]
    if not isinstance(v, (list, tuple)) or len(v) not in dims:
        raise ValueError(f"expected {' or '.join(map(str, dims))} numbers, got {v!r}")
    return tuple(round(float(c), 4) for c in v)


class Placement(BaseModel):
    """Where a brick goes. Everything optional; what is needed depends on the brick's mount."""

    ref: Optional[str] = Field(None, description="Id of the frame it goes in or on; null = the level datum")
    level: Optional[str] = Field(None, description="Level datum when there is no ref (default: the first level)")
    side: Face = "center"
    near: Optional[P2] = None
    at: float = Field(0.5, ge=0, le=1)
    position: Optional[tuple[float, ...]] = Field(None, description="[x, y] or [x, y, z]")
    start: Optional[tuple[float, ...]] = None
    end: Optional[tuple[float, ...]] = None
    rotation: Optional[float] = None

    @field_validator("near", mode="before")
    @classmethod
    def _p2(cls, v):
        return _point(v)

    @field_validator("position", "start", "end", mode="before")
    @classmethod
    def _p3(cls, v):
        return _point(v, (2, 3))


@dataclass(frozen=True)
class Side:
    """A vertical face of a frame, as a plan line with the unit normal pointing out of the footprint."""

    line: LineString
    outward: P2
    id: Optional[str] = None

    @property
    def compass(self) -> str:
        return compass(*self.outward)


@dataclass
class Frame:
    id: str
    level: str
    z0: float                       # relative to the level
    z1: float
    footprint: Optional[Polygon]    # None: an unbounded datum
    void: bool
    sides: list[Side] = field(default_factory=list)
    inset: float = 0.0              # void frames: how far inside its sides the usable space starts (half a wall)
    hint: str = ""                  # said in messages ("outside the building")
    note: Optional[str] = None      # carried onto what rests on it ("on a gable roof: set at mid-slope")

    @property
    def size(self) -> P3:
        if self.footprint is None:
            return (0.0, 0.0, self.z1 - self.z0)
        x0, y0, x1, y1 = self.footprint.bounds
        return (x1 - x0, y1 - y0, self.z1 - self.z0)

    def describe(self) -> str:
        if self.footprint is None:
            return f"'{self.id}'"
        x0, y0, x1, y1 = self.footprint.bounds
        return f"'{self.id}'" + (f" ({self.hint})" if self.hint else "") + f" (x {x0:.1f}..{x1:.1f}, y {y0:.1f}..{y1:.1f})"


def solid_frame(id_: str, level: str, outline: Polygon, z0: float, z1: float, **kw) -> Frame:
    """A solid body: its sides are the outline's edges."""
    return Frame(id_, level, z0, z1, outline, False, sides=outline_sides(outline), **kw)


def outline_sides(poly: Polygon) -> list[Side]:
    ring = poly.exterior
    pts = list(ring.coords)
    ccw = ring.is_ccw
    out = []
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        if n < 1e-6:
            continue
        out.append(Side(LineString([a, b]), (dy / n, -dx / n) if ccw else (-dy / n, dx / n)))
    return out


def compass(nx: float, ny: float) -> str:
    ang = math.degrees(math.atan2(ny, nx)) % 360
    if 45 <= ang < 135:
        return "N"
    if 135 <= ang < 225:
        return "W"
    if 225 <= ang < 315:
        return "S"
    return "E"


@dataclass
class Pose:
    level: str
    position: P3                    # of the brick's origin; z relative to the level
    yaw: float = 0.0                # degrees about z
    pitch: float = 0.0              # degrees, raising local +x (paths that climb)

    @property
    def matrix(self) -> np.ndarray:
        return transform(self.position, (0.0, -self.pitch, self.yaw))


@dataclass
class Placed:
    pose: Pose
    values: dict[str, float]
    solids: list
    bounds: Bounds
    keepout: list[Bounds]
    path: Optional[tuple[P3, P3]] = None
    note: Optional[str] = None


def world_box(box: Bounds, pose: Pose) -> tuple[Polygon, float, float]:
    """Plan outline (convex hull) and z range of a local box once posed."""
    x0, y0, z0, x1, y1, z1 = box
    pts = np.array([(x, y, z, 1.0) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]) @ pose.matrix.T
    hull = MultiPoint([(float(x), float(y)) for x, y in pts[:, :2]]).convex_hull
    if not isinstance(hull, Polygon):
        hull = hull.buffer(0.005)
    return hull, float(pts[:, 2].min()), float(pts[:, 2].max())


class Frames:
    """The frames of one model, by id, plus its level datums (void, unbounded, one per level)."""

    def __init__(self, levels: dict[str, float], default_level: str):
        self.levels = levels                    # level id -> storey height
        self.default_level = default_level
        self.by_id: dict[str, Frame] = {}

    def add(self, frame: Frame) -> None:
        self.by_id[frame.id] = frame

    def get(self, placement: Placement, what: str) -> Frame:
        if placement.ref is not None:
            frame = self.by_id.get(placement.ref)
            if frame is None:
                known = sorted(self.by_id)
                raise PlacementError(f"{what}: nothing called '{placement.ref}' to place it in or on "
                                     f"(e.g. {', '.join(known[:30])}{', …' if len(known) > 30 else ''})")
            if placement.level and placement.level != frame.level:
                raise PlacementError(f"{what}: '{frame.id}' is on {frame.level}, not {placement.level}")
            return frame
        level = placement.level or self.default_level
        if level not in self.levels:
            raise PlacementError(f"{what}: unknown level '{level}' (levels: {', '.join(self.levels)})")
        return Frame(level, level, 0.0, self.levels[level], None, True)


def place(brick: Brick, given: dict[str, float], p: Placement, frames: Frames, what: str) -> Placed:
    frame = frames.get(p, what)
    path = _path(brick, p, what)
    w, d, h = frame.size
    context = {"ref_w": w, "ref_d": d, "ref_h": h}
    if path is not None:
        context["path_length"] = round(math.dist(path[0], path[1]), 4)
    try:
        values = brick.resolve(given, context)
        solids = brick.solids(values)
        keepout = brick.keepout_boxes(values)
    except ValueError as exc:
        raise PlacementError(f"{what}: {exc}") from exc
    box = bounds(solids)
    lift = brick.elevation_of(values)
    if path is not None:
        pose = _along(frame, path, lift)
    else:
        pose = _pose(brick, frame, p, box, lift, what)
    _check_fit(frame, brick, pose, box, what)
    note = frame.note if brick.mount == "rest" and not frame.void else None
    return Placed(pose, values, solids, box, keepout, path, note)


def _path(brick: Brick, p: Placement, what: str) -> tuple[P3, P3] | None:
    if brick.mount != "path":
        if p.start is not None or p.end is not None:
            raise PlacementError(f"{what}: `start`/`end` are for path bricks; {brick.id} is mount {brick.mount} — give `position`, `side` or `near`")
        return None
    if p.start is None or p.end is None:
        missing = " and ".join(f"`{k}`" for k in ("start", "end") if getattr(p, k) is None)
        raise PlacementError(f"{what}: {brick.id} runs along a path: give {missing}")
    a, b = (tuple(v) + (0.0,) * (3 - len(v)) for v in (p.start, p.end))
    if math.dist(a, b) < 0.2:
        raise PlacementError(f"{what}: start and end are {math.dist(a, b):.2f} m apart; a path needs two distinct points")
    return a, b


def _along(frame: Frame, path: tuple[P3, P3], lift: float) -> Pose:
    (x0, y0, z0), (x1, y1, z1) = path
    base = frame.z0 if frame.void else frame.z1
    yaw = math.degrees(math.atan2(y1 - y0, x1 - x0))
    pitch = math.degrees(math.atan2(z1 - z0, math.hypot(x1 - x0, y1 - y0)))
    return Pose(frame.level, (x0, y0, base + lift + z0), yaw, pitch)


def _pose(brick: Brick, frame: Frame, p: Placement, box: Bounds, lift: float, what: str) -> Pose:
    bz0, bz1 = box[2], box[5]
    if p.position is not None:
        (x, y), yaw = p.position[:2], p.rotation or 0.0
    elif p.near is not None or p.side != "center" or brick.mount == "fix":
        x, y, yaw = _against(brick, frame, p, box, what)
    else:
        (x, y), yaw = _middle(frame, what), p.rotation or 0.0
    if p.position is not None and len(p.position) == 3:
        return Pose(frame.level, (x, y, p.position[2]), yaw)
    match brick.mount:
        case "rest" | "path":
            z = (frame.z0 if frame.void else frame.z1) + lift - bz0
        case "fix":
            z = frame.z0 + lift - bz0
        case "hang":
            z = (frame.z1 if frame.void else frame.z0) - lift - bz1
        case _:
            assert_never(brick.mount)
    return Pose(frame.level, (x, y, z), yaw)


def _middle(frame: Frame, what: str) -> P2:
    if frame.footprint is None:
        raise PlacementError(f"{what}: on a bare level it needs `position` [x, y] (or a `ref` to place it in or on)")
    c = frame.footprint.centroid
    if not frame.footprint.contains(c):
        c = frame.footprint.representative_point()
    return (round(c.x, 3), round(c.y, 3))


def _against(brick: Brick, frame: Frame, p: Placement, box: Bounds, what: str) -> tuple[float, float, float]:
    """Origin and yaw that put the brick's back (local min y) against a side, `at` of the way along it."""
    side = _pick_side(frame, p, what)
    bx0, by0, _, bx1, _, _ = box
    width = bx1 - bx0
    inset = frame.inset if frame.void else 0.0
    at = side.line.project(ShpPoint(p.near), normalized=True) if p.near is not None else p.at
    usable = side.line.length - 2 * inset - width
    if usable < -1e-6:
        raise PlacementError(f"{what}: {width:.2f} m wide does not fit along the {side.compass} side of {frame.describe()} "
                             f"({side.line.length:.2f} m)")
    along = inset + width / 2 + min(max(at, 0.0), 1.0) * max(usable, 0.0)
    pt = side.line.interpolate(along)
    ahead, behind = side.line.interpolate(min(side.line.length, along + 0.05)), side.line.interpolate(max(0.0, along - 0.05))
    tx, ty = ahead.x - behind.x, ahead.y - behind.y
    n = math.hypot(tx, ty) or 1.0
    normal = (-ty / n, tx / n)                                   # the local normal on the outward side (sides may be faceted arcs)
    if normal[0] * side.outward[0] + normal[1] * side.outward[1] < 0:
        normal = (-normal[0], -normal[1])
    facing = (-normal[0], -normal[1]) if frame.void else normal  # the way the brick's front points
    yaw = p.rotation if p.rotation is not None else (math.degrees(math.atan2(facing[1], facing[0])) - 90) % 360
    sx, sy = pt.x + facing[0] * inset, pt.y + facing[1] * inset
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    lx, ly = (bx0 + bx1) / 2, by0                                # the middle of the brick's back, in its own frame
    return round(sx - (lx * c - ly * s), 3), round(sy - (lx * s + ly * c), 3), round(yaw, 3)


def _pick_side(frame: Frame, p: Placement, what: str) -> Side:
    if not frame.sides:
        raise PlacementError(f"{what}: {frame.describe()} has no sides to put it against; give `position`")
    if p.near is not None:
        pt = ShpPoint(p.near)
        best = min(frame.sides, key=lambda s: s.line.distance(pt))
        if best.line.distance(pt) > NEAR_MAX:
            raise PlacementError(f"{what}: near={list(p.near)} is {best.line.distance(pt):.1f} m from every side of {frame.describe()}")
        return best
    if p.side == "center":
        return max(frame.sides, key=lambda s: s.line.length)
    matching = [s for s in frame.sides if s.compass == p.side]
    if not matching:
        have = sorted({s.compass for s in frame.sides})
        raise PlacementError(f"{what}: {frame.describe()} has no side facing {p.side}; its sides face {', '.join(have)}")
    if len(matching) > 1 and not _one_line(matching):
        mids = " or ".join(f"near {[round(s.line.centroid.x, 2), round(s.line.centroid.y, 2)]}" for s in matching)
        raise PlacementError(f"{what}: {frame.describe()} has {len(matching)} sides facing {p.side}; say which with `near` ({mids})")
    return max(matching, key=lambda s: s.line.length)


def _one_line(sides: list[Side]) -> bool:
    """Several pieces of one straight side (split by neighbours) are not ambiguous; two separate sides are."""
    (ax, ay), (bx, by) = sides[0].line.coords[0], sides[0].line.coords[-1]
    n = math.hypot(bx - ax, by - ay) or 1.0
    return all(abs((x - ax) * (by - ay) - (y - ay) * (bx - ax)) / n <= 0.01 for s in sides for x, y in s.line.coords)


def _check_fit(frame: Frame, brick: Brick, pose: Pose, box: Bounds, what: str) -> None:
    if frame.footprint is None:
        return
    outline, z0, z1 = world_box(box, pose)
    x, y = pose.position[:2]
    if frame.void:
        if not frame.footprint.buffer(FIT_TOL).contains(outline):
            raise PlacementError(f"{what}: at [{x:.2f}, {y:.2f}] it does not fit inside {frame.describe()}; "
                                 f"move it, make it smaller or place it elsewhere")
        if z1 > frame.z1 + 0.01 or z0 < frame.z0 - 0.01:
            raise PlacementError(f"{what}: from z {z0:.2f} to {z1:.2f} m it does not fit in the {frame.z0:g}..{frame.z1:g} m height of '{frame.id}'")
    elif brick.mount in ("rest", "hang") and not frame.footprint.buffer(FIT_TOL).contains(outline):
        raise PlacementError(f"{what}: at [{x:.2f}, {y:.2f}] it is off {frame.describe()}; use a smaller size or another position")
