"""The semantic design — what the language model builds up, step by step.

A Design says what the building contains and roughly where: storeys, rooms as
rectangles or polygons on the plan, doors between rooms, windows on a wall of a
room, stairs, furniture, balconies, a porch, the roof kind, plus free-standing
elements outside the room system. It never contains a derived wall or a coordinate
of an opening: `core/derive.py` derives every wall from the room outlines (shared
edges become partitions, free edges become exterior walls), places openings along
those walls, and produces the geometric `BuildingSpec`.

Ids are stable handles: a room keeps its id when it moves, so the walls, spaces
and openings derived from it keep their ids and therefore their IFC GlobalIds.
All dimensions are metres; rectangles are [x, y, width, depth] with (x, y) the
south-west corner, x east, y north. Polygons are counter-clockwise vertex lists
whose edges may be arcs (through a third point) or open (no wall).

Naming a wall: `side` (N/S/E/W, the compass direction its outside faces) is sugar
that works for rectangles; `near` [x, y] (a point on or next to the wall) works for
any shape and is what the model uses for polygons.
"""

from __future__ import annotations

import math
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.bim import FixtureKind, RoofShape, WallMaterial

Side = Literal["N", "S", "E", "W"]
RoomKind = Literal["living", "kitchen", "dining", "office", "bedroom", "bathroom", "hall", "garage", "utility",
                   "storage", "courtyard", "terrace", "carport", "pergola", "other"]
DoorKind = Literal["single", "double", "sliding", "french", "garage"]
WindowKind = Literal["standard", "large", "floor", "small"]
FreeKind = Literal["wall", "slab", "roof", "column", "beam"]
Rect = tuple[float, float, float, float]
Pt = tuple[float, float]

MAX_STOREYS = 40
ARC_SEGMENT = 0.25       # chord length used to facet arcs
UNROOFED_KINDS = ("courtyard", "terrace")
UNWALLED_KINDS = ("carport", "pergola")
KIND_WORDS: list[tuple[str, RoomKind]] = [
    (r"living|lounge|family|sitting|great room|salon", "living"), (r"kitchen", "kitchen"), (r"dining|breakfast", "dining"),
    (r"office|study|studio|library", "office"), (r"bed|master|guest|nursery|suite", "bedroom"),
    (r"bath|ensuite|en-suite|wc|toilet|powder|shower", "bathroom"), (r"hall|entry|foyer|corridor|landing|vestibule|lobby", "hall"),
    (r"carport", "carport"), (r"pergola|loggia|gazebo", "pergola"), (r"courtyard|patio|atrium", "courtyard"),
    (r"terrace|roof deck|deck|veranda", "terrace"),
    (r"garage", "garage"), (r"laundry|utility|mud", "utility"), (r"stor|closet|pantry|walk-in", "storage"),
]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "room"


def guess_kind(name: str) -> RoomKind:
    low = name.lower()
    for pattern, kind in KIND_WORDS:
        if re.search(pattern, low):
            return kind
    return "other"


def _round(v: float) -> float:
    return round(float(v), 2)


def _pt(v) -> Pt:
    if isinstance(v, dict):
        v = [v.get("x"), v.get("y")]
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"a point is [x, y]; got {v!r}")
    return (_round(v[0]), _round(v[1]))


# --- polygon helpers -------------------------------------------------------

def arc_points(a: Pt, m: Pt, b: Pt, max_seg: float = ARC_SEGMENT) -> list[Pt]:
    """Points along the circular arc from `a` through `m` to `b`, excluding `a`, including `b`.
    Collinear points give just [b]."""
    ax, ay = a
    mx, my = m
    bx, by = b
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-9:
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
    pts = [(_round(ux + r * math.cos(ta + span * i / n)), _round(uy + r * math.sin(ta + span * i / n))) for i in range(1, n)]
    return pts + [b]


def signed_area(pts: list[Pt]) -> float:
    n = len(pts)
    return sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2


class Edge(BaseModel):
    """One edge of a room polygon, ending at `to` (it starts where the previous edge ended)."""

    to: Pt
    through: Optional[Pt] = Field(None, description="Make the edge an arc passing through this point")
    open: bool = Field(False, description="No wall on this edge: columns instead when it faces outside")

    @field_validator("to", "through", mode="before")
    @classmethod
    def _p(cls, v):
        return None if v is None else _pt(v)

    @model_validator(mode="before")
    @classmethod
    def _shape(cls, v):
        if isinstance(v, (list, tuple)):  # bare [x, y] vertex
            return {"to": v}
        return v


class Segment(BaseModel):
    """A straight piece of a room boundary (arcs are faceted)."""

    a: Pt
    b: Pt
    edge: int          # index of the polygon edge it belongs to
    arc: bool = False
    open: bool = False

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)


def rect_edges(rect: Rect) -> list[Edge]:
    x, y, w, d = rect
    return [Edge(to=(x, y)), Edge(to=(_round(x + w), y)), Edge(to=(_round(x + w), _round(y + d))), Edge(to=(x, _round(y + d)))]


def edges_to_segments(edges: list[Edge], closed: bool = True) -> list[Segment]:
    """Facet a polygon (or an open polyline when closed=False) into straight segments."""
    segs: list[Segment] = []
    n = len(edges)
    rng = range(n) if closed else range(1, n)
    for i in rng:
        prev = edges[i - 1].to
        e = edges[i]
        if e.through:
            pts = arc_points(prev, e.through, e.to)
            cur = prev
            for p in pts:
                if math.dist(cur, p) > 1e-6:
                    segs.append(Segment(a=cur, b=p, edge=i, arc=True, open=e.open))
                cur = p
        elif math.dist(prev, e.to) > 1e-6:
            segs.append(Segment(a=prev, b=e.to, edge=i, open=e.open))
    return segs


def outline_of(edges: list[Edge]) -> list[Pt]:
    return [s.a for s in edges_to_segments(edges)]


def reverse_edges(edges: list[Edge]) -> list[Edge]:
    """Same closed polygon, opposite orientation; each edge keeps its arc point and open flag."""
    n = len(edges)
    verts = [e.to for e in edges]
    out = []
    for j in range(n):
        src = edges[(n - j) % n]
        out.append(Edge(to=verts[n - 1 - j], through=src.through, open=src.open))
    return out


# --- levels and rooms ------------------------------------------------------

LEVEL_ID = re.compile(r"^([LB])(\d+)$")


class LevelDef(BaseModel):
    id: str = Field(description="'L1' is the ground floor, 'L2' the storey above it …, 'B1' the first level below ground, 'B2' below that")
    name: Optional[str] = None
    height: float = Field(3.0, ge=2.2, le=12.0, description="Floor-to-floor height in metres")
    below_ground: bool = Field(False, description="Basement level: no windows, no roof; stacks downward from ground")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = str(v).strip().upper()
        if not LEVEL_ID.match(v) or int(v[1:]) < 1:
            raise ValueError(f"level ids look like 'L1', 'L2' … or 'B1', 'B2' for basements; got {v!r}")
        return v

    def model_post_init(self, __context) -> None:
        if self.id.startswith("B"):
            self.below_ground = True

    @property
    def index(self) -> int:
        """0 for the ground floor, positive above, negative below (B1 = -1)."""
        n = int(self.id[1:])
        return -n if self.id.startswith("B") else n - 1

    @property
    def display(self) -> str:
        if self.name:
            return self.name
        if self.index < 0:
            return "Basement" if self.index == -1 else f"Basement {-self.index}"
        return "Ground Floor" if self.index == 0 else f"Level {self.index + 1}"


class RoomDef(BaseModel):
    id: str
    name: str
    level: str = "L1"
    kind: RoomKind = "other"
    rect: Optional[Rect] = Field(None, description="[x, y, width, depth]; null = place it automatically (or see poly)")
    poly: Optional[list[Edge]] = Field(None, description="Any outline: vertices counter-clockwise; edges may be arcs or open")
    area: Optional[float] = Field(None, gt=0, description="Target m² when neither rect nor poly is given")
    roofed: Optional[bool] = Field(None, description="False for courtyards and terraces: no roof or ceiling over this room (default by kind)")
    enclosed: Optional[bool] = Field(None, description="False for carports and pergolas: no walls at all, columns hold the roof (default by kind)")

    @field_validator("rect")
    @classmethod
    def _rect(cls, v):
        if v is None:
            return None
        x, y, w, d = (_round(c) for c in v)
        if w < 0.8 or d < 0.8:
            raise ValueError(f"room rectangles must be at least 0.8 m in both directions, got {w} x {d}")
        return (x, y, w, d)

    @model_validator(mode="after")
    def _poly(self) -> "RoomDef":
        if self.roofed is None:
            self.roofed = self.kind not in UNROOFED_KINDS
        if self.enclosed is None:
            self.enclosed = self.kind not in UNWALLED_KINDS
        if self.poly is not None:
            if len(self.poly) < 3:
                raise ValueError("a room polygon needs at least 3 vertices")
            pts = outline_of(self.poly)
            if len(pts) < 3:
                raise ValueError("a room polygon needs at least 3 distinct vertices")
            from shapely.geometry import Polygon
            if not Polygon(pts).is_valid:
                raise ValueError("room polygon crosses itself; list the vertices in order around the room")
            if signed_area(pts) < 0:
                self.poly = reverse_edges(self.poly)
                pts = outline_of(self.poly)
            if abs(signed_area(pts)) < 1.0:
                raise ValueError(f"room polygon area is {abs(signed_area(pts)):.2f} m²; rooms need at least 1 m²")
            self.rect = None
        return self

    # --- geometry -------------------------------------------------------------

    def edges(self) -> list[Edge]:
        if self.poly is not None:
            return self.poly
        if self.rect is not None:
            return rect_edges(self.rect)
        raise ValueError(f"room '{self.id}' has no outline yet")

    def segments(self) -> list[Segment]:
        return edges_to_segments(self.edges())

    def outline(self) -> list[Pt]:
        return [s.a for s in self.segments()]

    def polygon(self):
        from shapely.geometry import Polygon
        return Polygon(self.outline())

    @property
    def placed(self) -> bool:
        return self.rect is not None or self.poly is not None

    @property
    def is_rect(self) -> bool:
        return self.poly is None and self.rect is not None

    @property
    def box(self) -> tuple[float, float, float, float]:
        """Bounding box (x0, y0, x1, y1)."""
        if self.rect is not None and self.poly is None:
            x, y, w, d = self.rect
            return x, y, _round(x + w), _round(y + d)
        pts = self.outline()
        return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))

    @property
    def area_m2(self) -> float:
        if self.rect is not None and self.poly is None:
            return self.rect[2] * self.rect[3]
        if self.poly is not None:
            return abs(signed_area(self.outline()))
        return self.area or 0.0

    def has_open_edges(self) -> bool:
        return not self.enclosed or any(e.open for e in (self.poly or []))


class DoorDef(BaseModel):
    id: str
    room: Optional[str] = Field(None, description="Room the door belongs to (null only with `wall`)")
    to: str = Field("outside", description="Other room id, or 'outside'")
    side: Optional[Side] = Field(None, description="Exterior doors: which side of the room; null = pick one")
    near: Optional[Pt] = Field(None, description="A point on or next to the wall the door goes in")
    wall: Optional[str] = Field(None, description="Id of a free-standing wall element to put the door in")
    at: float = Field(0.5, ge=0, le=1, description="Position along the wall, 0 = start (west/south end)")
    kind: DoorKind = "single"
    width: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)

    @field_validator("near", mode="before")
    @classmethod
    def _near(cls, v):
        return None if v is None else _pt(v)


class WindowDef(BaseModel):
    id: str
    room: Optional[str] = None
    side: Optional[Side] = None
    near: Optional[Pt] = None
    wall: Optional[str] = None
    at: float = Field(0.5, ge=0, le=1)
    kind: WindowKind = "standard"
    width: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)
    sill: Optional[float] = Field(None, ge=0)

    @field_validator("near", mode="before")
    @classmethod
    def _near(cls, v):
        return None if v is None else _pt(v)


class StairDef(BaseModel):
    id: str
    room: str
    side: Optional[Side] = Field(None, description="The flight runs along this wall of the room; null = the longest straight wall")
    near: Optional[Pt] = None
    to_level: Optional[str] = Field(None, description="null = the level above")
    width: float = Field(1.0, gt=0.6, le=3.0)

    @field_validator("near", mode="before")
    @classmethod
    def _near(cls, v):
        return None if v is None else _pt(v)


class FixtureDef(BaseModel):
    id: str
    room: str
    kind: FixtureKind
    side: Literal["N", "S", "E", "W", "center"] = Field("center", description="Against which wall (back to the wall)")
    near: Optional[Pt] = Field(None, description="Against the wall nearest this point")
    at: float = Field(0.5, ge=0, le=1, description="Position along that wall")
    rotation: Optional[float] = Field(None, description="Degrees; null = face away from the wall")
    width: Optional[float] = Field(None, gt=0)
    depth: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)

    @field_validator("near", mode="before")
    @classmethod
    def _near(cls, v):
        return None if v is None else _pt(v)


class ShapePartDef(BaseModel):
    """One solid of a custom shape: a box (min corner x,y,z; size w,d,h) or, for a "round" part,
    a w-diameter cylinder (d is ignored). Parts compose freely — a round top plus box legs is a table."""

    shape: Literal["box", "round"] = "box"
    x: float = 0.0
    y: float = 0.0
    z: float = Field(0.0, ge=0)
    w: float = Field(gt=0, description="width (box) or diameter (round)")
    d: float = Field(0.1, gt=0, description="depth; ignored for a round part")
    h: float = Field(gt=0)


class CustomShapeDef(BaseModel):
    """A furniture/object piece the model designs itself, for anything schemas.bim.FixtureKind's
    fixed catalog doesn't cover — a round table, an L-shaped bench, a plinth."""

    id: str
    room: str
    name: str = "Custom object"
    side: Literal["N", "S", "E", "W", "center"] = "center"
    near: Optional[Pt] = None
    at: float = Field(0.5, ge=0, le=1)
    rotation: Optional[float] = None
    parts: list[ShapePartDef] = Field(min_length=1, max_length=12)

    @field_validator("near", mode="before")
    @classmethod
    def _near(cls, v):
        return None if v is None else _pt(v)


class BrickDef(BaseModel):
    """One placed brick from the library (bricks/library): what it is, where, and any parameters that
    differ from the brick's defaults. How it is placed depends on the brick's host — see bricks/model.py."""

    id: str
    brick: str = Field(description="Brick id from the library")
    room: Optional[str] = Field(None, description="Room it stands in (floor/wall/ceiling hosts); optional for free/roof/span")
    level: Optional[str] = Field(None, description="Storey for bricks without a room; default the room's, else the ground floor")
    side: Literal["N", "S", "E", "W", "center"] = "center"
    near: Optional[Pt] = None
    at: float = Field(0.5, ge=0, le=1)
    position: Optional[Pt] = Field(None, description="Exact plan position of its centre")
    start: Optional[Pt] = Field(None, description="span bricks: from")
    end: Optional[Pt] = Field(None, description="span bricks: to")
    rotation: Optional[float] = None
    params: dict[str, float] = Field(default_factory=dict)

    @field_validator("near", "position", "start", "end", mode="before")
    @classmethod
    def _p(cls, v):
        return None if v is None else _pt(v)


class BalconyDef(BaseModel):
    id: str
    room: str
    side: Optional[Side] = None
    near: Optional[Pt] = None
    depth: float = Field(1.5, ge=0.8, le=4.0)

    @field_validator("near", mode="before")
    @classmethod
    def _near(cls, v):
        return None if v is None else _pt(v)


class ColumnDef(BaseModel):
    id: str
    level: str = "L1"
    x: float
    y: float
    size: float = Field(0.3, gt=0)


class FreeDef(BaseModel):
    """A free-standing element outside the room system: a garden wall, a deck, a pergola roof, a
    pier. Unchecked by design except for `feature` requirements matched on its name."""

    id: str
    kind: FreeKind
    level: str = "L1"
    name: Optional[str] = None
    path: Optional[list[Edge]] = Field(None, description="wall: polyline of vertices (arcs allowed), open-ended")
    poly: Optional[list[Edge]] = Field(None, description="slab/roof: outline")
    at: Optional[Pt] = Field(None, description="column: position")
    start: Optional[Pt] = Field(None, description="beam: from")
    end: Optional[Pt] = Field(None, description="beam: to")
    height: Optional[float] = Field(None, gt=0, description="wall/column: default the level height")
    thickness: Optional[float] = Field(None, gt=0, description="wall/slab/roof")
    width: Optional[float] = Field(None, gt=0, description="column size / beam width")
    depth: Optional[float] = Field(None, gt=0, description="beam depth")

    @field_validator("at", "start", "end", mode="before")
    @classmethod
    def _p(cls, v):
        return None if v is None else _pt(v)

    @model_validator(mode="after")
    def _shape(self) -> "FreeDef":
        k = self.kind
        if k == "wall":
            if not self.path or len(self.path) < 2:
                raise ValueError("a free wall needs `path`: at least two points")
        elif k in ("slab", "roof"):
            if not self.poly or len(self.poly) < 3:
                raise ValueError(f"a free {k} needs `poly`: at least three points")
            pts = outline_of(self.poly)
            if signed_area(pts) < 0:
                self.poly = reverse_edges(self.poly)
            if abs(signed_area(outline_of(self.poly))) < 0.5:
                raise ValueError(f"free {k} outline has (almost) no area")
        elif k == "column":
            if self.at is None:
                raise ValueError("a free column needs `at`: [x, y]")
        elif k == "beam":
            if self.start is None or self.end is None:
                raise ValueError("a free beam needs `start` and `end`")
            if math.dist(self.start, self.end) < 0.3:
                raise ValueError("a beam needs at least 0.3 m between start and end")
        return self

    def path_segments(self) -> list[Segment]:
        return edges_to_segments(self.path or [], closed=False)

    def outline(self) -> list[Pt]:
        return outline_of(self.poly or [])


class PorchDef(BaseModel):
    side: Side = "S"
    depth: float = Field(2.4, ge=1.0, le=5.0)


class RoofDef(BaseModel):
    kind: RoofShape = "flat"
    pitch: float = Field(30.0, ge=5, le=60)
    overhang: float = Field(0.3, ge=0, le=1.5)


# Collections whose items stand in a room (`.room`) and go when the room does.
ROOM_OWNED = ("doors", "windows", "stairs", "fixtures", "custom_shapes", "balconies", "bricks")


class Design(BaseModel):
    name: str = "Generated Building"
    description: Optional[str] = None
    levels: list[LevelDef] = Field(default_factory=lambda: [LevelDef(id="L1")])
    rooms: list[RoomDef] = Field(default_factory=list)
    doors: list[DoorDef] = Field(default_factory=list)
    windows: list[WindowDef] = Field(default_factory=list)
    stairs: list[StairDef] = Field(default_factory=list)
    fixtures: list[FixtureDef] = Field(default_factory=list)
    custom_shapes: list[CustomShapeDef] = Field(default_factory=list)
    bricks: list[BrickDef] = Field(default_factory=list, description="Placed library bricks: equipment, services, structure, site")
    balconies: list[BalconyDef] = Field(default_factory=list)
    columns: list[ColumnDef] = Field(default_factory=list)
    elements: list[FreeDef] = Field(default_factory=list, description="Free-standing walls, slabs, roofs, columns, beams")
    porch: Optional[PorchDef] = None
    roof: RoofDef = Field(default_factory=RoofDef)
    wall_material: Optional[WallMaterial] = None
    overrides: list[dict] = Field(default_factory=list, description="Raw element ops replayed after derivation")
    notes: list[str] = Field(default_factory=list)

    # --- lookups ------------------------------------------------------------

    def level(self, level_id: str) -> LevelDef | None:
        return next((l for l in self.levels if l.id == level_id), None)

    def room(self, ref: str) -> RoomDef | None:
        """By id, then by name (case-insensitive), then by slug of the name."""
        if ref is None:
            return None
        key = ref.strip()
        for r in self.rooms:
            if r.id == key:
                return r
        low, sl = key.lower(), slug(key)
        for r in self.rooms:
            if r.name.lower() == low or r.id == sl:
                return r
        return None

    def element(self, ref: str) -> FreeDef | None:
        return next((e for e in self.elements if e.id == ref), None)

    def rooms_on(self, level_id: str) -> list[RoomDef]:
        return [r for r in self.rooms if r.level == level_id]

    def all_ids(self) -> set[str]:
        return {x.id for attr in ("levels", "rooms", "columns", "elements", *ROOM_OWNED) for x in getattr(self, attr)}

    def unique_id(self, base: str) -> str:
        ids = self.all_ids()
        if base not in ids:
            return base
        n = 2
        while f"{base}-{n}" in ids:
            n += 1
        return f"{base}-{n}"

    def storeys(self) -> int:
        """Storeys above ground (what people count when they say 'two-storey house')."""
        return sum(1 for l in self.levels if l.index >= 0)

    def basements(self) -> int:
        return sum(1 for l in self.levels if l.index < 0)

    def ordered_levels(self) -> list[LevelDef]:
        return sorted(self.levels, key=lambda l: l.index)

    def ground_level(self) -> LevelDef:
        """The lowest storey above ground (L1), or the first level when there are only basements."""
        return next((l for l in self.ordered_levels() if l.index >= 0), self.levels[0])

    def level_above(self, level_id: str) -> LevelDef | None:
        cur = self.level(level_id)
        if cur is None:
            return None
        return next((l for l in self.ordered_levels() if l.index > cur.index), None)
