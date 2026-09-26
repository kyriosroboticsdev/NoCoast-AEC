"""Design → BuildingSpec. Deterministic: the same design always yields the same
elements with the same ids, so GlobalIds survive edits.

Walls come from room rectangles: every rectangle edge is split at the corners of
neighbouring rooms; a piece touched by one room is an exterior wall, a piece shared
by two rooms is a partition. Doors and windows are then placed along those walls,
stairs and fixtures inside the rooms, slabs and roofs over the union of the rooms
on each storey. Raw ops stored as `overrides` are replayed at the end.

Everything that can go wrong raises DesignError with a message written for the
model ("kitchen has no exterior wall on side N; its exterior sides are S, W").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import Polygon, box as shp_box
from shapely.ops import unary_union

from ifc.fixtures import default_size
from schemas.bim import (Beam, BuildingSpec, Column, CustomFixture, Door, Fixture, Level, LightFixture, Outlet,
                         Panel, Pipe, Railing, Roof, ShapePart, Slab, Space, Stair, Wall, Window, Wire, is_axis_rectangle)
from schemas.design import CustomShapeDef, Design, DoorDef, FixtureDef, LevelDef, RoomDef, Side, StairDef, WindowDef
from solver.layout import place_rooms

EXT_T, INT_T = 0.3, 0.12
MARGIN = 0.15          # openings keep this far from wall ends
CLEAR = 0.15           # fixtures and stairs keep this far from wall centre lines
DOOR_SIZES = {"single": (0.9, 2.1), "double": (1.6, 2.1), "sliding": (1.8, 2.1), "french": (1.6, 2.1), "garage": (2.4, 2.2)}
WINDOW_SIZES = {"standard": (1.2, 1.2, 0.9), "large": (2.0, 1.6, 0.6), "floor": (2.0, 2.2, 0.1), "small": (0.6, 0.6, 1.5)}
SIDE_ORDER: tuple[Side, ...] = ("S", "E", "W", "N")


class DesignError(ValueError):
    """The design cannot be built; the message is meant for the model."""


@dataclass
class WallSeg:
    id: str
    level: str
    start: tuple[float, float]
    end: tuple[float, float]
    external: bool
    rooms: tuple[str, ...]           # one room (exterior) or two (partition)
    side: Side | None                # exterior: which side of its room
    horizontal: bool
    openings: list[tuple[float, float, str]] = field(default_factory=list)  # (offset, width, id)

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)


@dataclass
class RoomInfo:
    room: RoomDef
    exterior: dict[Side, list[WallSeg]]
    partitions: dict[str, list[WallSeg]]  # neighbour id -> walls shared with it

    @property
    def sides(self) -> list[Side]:
        return [s for s in SIDE_ORDER if self.exterior.get(s)]

    @property
    def neighbours(self) -> list[str]:
        return sorted(self.partitions)


@dataclass
class Derived:
    spec: BuildingSpec
    notes: list[str]
    rooms: dict[str, RoomInfo]
    footprints: dict[str, list[Polygon]]
    design: Design | None = None   # the design actually built (with pruned items removed) when prune=True
    pruned: list[str] = field(default_factory=list)


def _r(v: float) -> float:
    return round(v, 2)


def _side_name(side: Side) -> str:
    return {"N": "north", "S": "south", "E": "east", "W": "west"}[side]


# --- walls ------------------------------------------------------------------

def _walls_for_level(level_id: str, rooms: list[RoomDef], vertices: set[tuple[float, float]], material) -> list[WallSeg]:
    boxes = {r.id: r.box for r in rooms}
    xs = sorted({v for b in boxes.values() for v in (b[0], b[2])})
    ys = sorted({v for b in boxes.values() for v in (b[1], b[3])})
    e = EXT_T / 2
    units: list[tuple] = []  # (horizontal, fixed, a, b, room_low, room_high)

    for y in ys:
        for xa, xb in zip(xs, xs[1:]):
            above = [i for i, (x0, y0, x1, y1) in boxes.items() if y0 == y and x0 <= xa and x1 >= xb]
            below = [i for i, (x0, y0, x1, y1) in boxes.items() if y1 == y and x0 <= xa and x1 >= xb]
            if above or below:
                units.append((True, y, xa, xb, below[0] if below else None, above[0] if above else None))
    for x in xs:
        for ya, yb in zip(ys, ys[1:]):
            right = [i for i, (x0, y0, x1, y1) in boxes.items() if x0 == x and y0 <= ya and y1 >= yb]
            left = [i for i, (x0, y0, x1, y1) in boxes.items() if x1 == x and y0 <= ya and y1 >= yb]
            if left or right:
                units.append((False, x, ya, yb, left[0] if left else None, right[0] if right else None))

    # Merge consecutive units with the same neighbours into one wall.
    merged: list[list] = []
    for u in sorted(units, key=lambda u: (u[0], u[1], u[2])):
        if merged and merged[-1][0] == u[0] and merged[-1][1] == u[1] and merged[-1][3] == u[2] and merged[-1][4:] == list(u[4:]):
            merged[-1][3] = u[3]
        else:
            merged.append(list(u))

    walls: list[WallSeg] = []
    counts: dict[str, int] = {}
    for horizontal, fixed, a, b, low, high in merged:
        if low and high:
            pair = tuple(sorted((low, high)))
            base = f"{level_id}-wall-{pair[0]}+{pair[1]}"
            rooms_t, side, external = pair, None, False
        else:
            room = low or high
            if horizontal:
                side = "N" if low else "S"      # room below the line → its north wall
            else:
                side = "E" if low else "W"      # room left of the line → its east wall
            base = f"{level_id}-wall-{room}-{side}"
            rooms_t, external = (room,), True
        counts[base] = counts.get(base, 0) + 1
        wid = base if counts[base] == 1 else f"{base}-{counts[base]}"
        if horizontal:
            start, end = (a, fixed), (b, fixed)
            if external:  # fill the corners: extend to the outer face of the perpendicular exterior wall
                if (a, fixed) in vertices:
                    start = (_r(a - e), fixed)
                if (b, fixed) in vertices:
                    end = (_r(b + e), fixed)
        else:
            start, end = (fixed, a), (fixed, b)
        walls.append(WallSeg(wid, level_id, start, end, external, rooms_t, side, horizontal))
    return walls


def _wall_element(w: WallSeg, level: Level, names: dict[str, str], material) -> Wall:
    if w.external:
        name = f"{names[w.rooms[0]]} {_side_name(w.side)} wall"
    else:
        name = f"{names[w.rooms[0]]} / {names[w.rooms[1]]} partition"
    return Wall(id=w.id, name=name, level=level.id, start=w.start, end=w.end, thickness=EXT_T if w.external else INT_T,
                external=w.external, material=material if w.external else None)


# --- openings ---------------------------------------------------------------

def _place(wall: WallSeg, width: float, at: float, what: str) -> float:
    """Offset along the wall for a new opening: at the requested position if free, else the nearest free slot."""
    usable = wall.length - width - 2 * MARGIN
    if usable < 0:
        raise DesignError(f"{what}: wall {wall.id} is {wall.length:.2f} m long, too short for a {width:.2f} m opening")
    wanted = MARGIN + at * usable
    # Free intervals [lo, hi] for the opening's start, between existing openings (0.1 m gaps).
    taken = sorted((o - 0.1, o + w + 0.1) for o, w, _ in wall.openings)
    free: list[tuple[float, float]] = []
    cursor = MARGIN
    for a, b in taken:
        if a - width >= cursor:
            free.append((cursor, a - width))
        cursor = max(cursor, b)
    if wall.length - MARGIN - width >= cursor:
        free.append((cursor, wall.length - MARGIN - width))
    if not free:
        raise DesignError(f"{what}: no room left on wall {wall.id} ({wall.length:.2f} m, {len(wall.openings)} opening(s) already there)")
    lo, hi = min(free, key=lambda iv: 0 if iv[0] <= wanted <= iv[1] else min(abs(wanted - iv[0]), abs(wanted - iv[1])))
    return _r(min(max(wanted, lo), hi))


def _longest(walls: list[WallSeg]) -> WallSeg:
    return max(walls, key=lambda w: w.length)


def _exterior_wall(info: RoomInfo, side: Side | None, what: str) -> tuple[WallSeg, Side]:
    if side is None:
        for s in SIDE_ORDER:
            if info.exterior.get(s):
                return _longest(info.exterior[s]), s
        raise DesignError(f"{what}: room '{info.room.id}' has no exterior wall at all")
    if not info.exterior.get(side):
        raise DesignError(f"{what}: room '{info.room.id}' has no exterior wall on side {side}; "
                          f"its exterior sides are {', '.join(info.sides) or 'none'}")
    return _longest(info.exterior[side]), side


def _door(d: DoorDef, design: Design, infos: dict[str, RoomInfo], level: Level) -> Door:
    what = f"door '{d.id}'"
    room = design.room(d.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{d.room}' (rooms: {', '.join(r.id for r in design.rooms)})")
    info = infos[room.id]
    width, height = DOOR_SIZES[d.kind]
    width, height = d.width or width, d.height or height
    if d.to.lower() in ("outside", "exterior", "out", "outdoors", "garden", "street"):
        wall, _ = _exterior_wall(info, d.side, what)
    else:
        other = design.room(d.to)
        if other is None:
            raise DesignError(f"{what}: unknown room '{d.to}' (rooms: {', '.join(r.id for r in design.rooms)})")
        if other.level != room.level:
            raise DesignError(f"{what}: '{room.id}' ({room.level}) and '{other.id}' ({other.level}) are on different storeys")
        shared = info.partitions.get(other.id)
        if not shared:
            raise DesignError(f"{what}: '{room.id}' and '{other.id}' do not share a wall "
                              f"('{room.id}' touches: {', '.join(info.neighbours) or 'nothing'})")
        wall = _longest(shared)
    if height > level.height - 0.05:
        height = level.height - 0.1
    offset = _place(wall, width, d.at, what)
    wall.openings.append((offset, width, d.id))
    other = design.room(d.to)
    name = f"{room.name} entrance" if other is None else f"{room.name} / {other.name} door"
    return Door(id=d.id, name=name, wall=wall.id, offset=offset, width=width, height=height, kind=d.kind)


def _window(w: WindowDef, design: Design, infos: dict[str, RoomInfo], level: Level) -> Window:
    what = f"window '{w.id}'"
    room = design.room(w.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{w.room}' (rooms: {', '.join(r.id for r in design.rooms)})")
    wall, _ = _exterior_wall(infos[room.id], w.side, what)
    width, height, sill = WINDOW_SIZES[w.kind]
    width, height, sill = w.width or width, w.height or height, w.sill if w.sill is not None else sill
    if sill + height > level.height - 0.1:
        height = max(0.4, level.height - 0.1 - sill)
    offset = _place(wall, width, w.at, what)
    wall.openings.append((offset, width, w.id))
    return Window(id=w.id, name=f"{room.name} {_side_name(w.side)} window", wall=wall.id, offset=offset, width=width,
                  height=height, sill_height=sill)


# --- things inside rooms ----------------------------------------------------

def _stair(s: StairDef, design: Design, level: Level) -> Stair:
    what = f"stair '{s.id}'"
    room = design.room(s.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{s.room}'")
    x0, y0, x1, y1 = room.box
    idx = design.level(room.level).index
    above = next((l for l in design.levels if l.index == idx + 1), None)
    to_level = s.to_level or (above.id if above else None)
    if to_level and design.level(to_level) is None:
        raise DesignError(f"{what}: unknown to_level '{to_level}'")
    stair = Stair(id=s.id, name=f"Stair in {room.name}", level=room.level, position=(0, 0), width=s.width, to_level=to_level)
    run = stair.run(level.height)
    need = run + 0.4
    if s.side in ("W", "E"):
        avail, along = y1 - y0, "north-south"
        x = x0 + CLEAR + s.width / 2 if s.side == "W" else x1 - CLEAR - s.width / 2
        stair.position, stair.direction = (_r(x), _r(y0 + 0.3)), 90.0
        across = x1 - x0
    else:
        avail, along = x1 - x0, "east-west"
        y = y0 + CLEAR + s.width / 2 if s.side == "S" else y1 - CLEAR - s.width / 2
        stair.position, stair.direction = (_r(x0 + 0.3), _r(y)), 0.0
        across = y1 - y0
    if avail < need:
        raise DesignError(f"{what}: room '{room.id}' is {avail:.2f} m {along} but a straight flight along side {s.side} "
                          f"needs {need:.2f} m; use a longer side or enlarge the room")
    if across < s.width + 2 * CLEAR:
        raise DesignError(f"{what}: room '{room.id}' is too narrow for a {s.width} m wide flight")
    return stair


def _place_footprint(what: str, room: RoomDef, side: str, at: float, w: float, d: float) -> tuple[tuple[float, float], float]:
    """Where a w x d footprint goes against `side` of a room (or centred), and which way it then
    faces. Shared by catalog fixtures (_fixture) and model-composed ones (_custom_shape) so both
    place against a wall or in the middle the same way."""
    x0, y0, x1, y1 = room.box
    rw, rd = x1 - x0, y1 - y0

    def along(lo: float, hi: float, half: float) -> float:
        if hi - lo < 2 * half + 2 * CLEAR:
            raise DesignError(f"{what}: room '{room.id}' is too small ({rw:.1f} x {rd:.1f} m) for a {w:.1f} x {d:.1f} m piece")
        return _r(lo + CLEAR + half + at * (hi - lo - 2 * CLEAR - 2 * half))

    if side == "center":
        if rw < w + 2 * CLEAR or rd < d + 2 * CLEAR:
            raise DesignError(f"{what}: room '{room.id}' is too small ({rw:.1f} x {rd:.1f} m) for a {w:.1f} x {d:.1f} m piece")
        return ((x0 + x1) / 2, (y0 + y1) / 2), 0.0
    if side == "S":
        return (along(x0, x1, w / 2), _r(y0 + CLEAR + d / 2)), 0.0
    if side == "N":
        return (along(x0, x1, w / 2), _r(y1 - CLEAR - d / 2)), 180.0
    if side == "W":
        return (_r(x0 + CLEAR + d / 2), along(y0, y1, w / 2)), 270.0
    return (_r(x1 - CLEAR - d / 2), along(y0, y1, w / 2)), 90.0


def _fixture(f: FixtureDef, design: Design, level: Level) -> Fixture:
    what = f"{f.kind} '{f.id}'"
    room = design.room(f.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{f.room}'")
    w, d, h = default_size(f.kind)
    w, d, h = f.width or w, f.depth or d, f.height or h
    pos, rot = _place_footprint(what, room, f.side, f.at, w, d)
    return Fixture(id=f.id, name=f"{f.kind.replace('_', ' ')} in {room.name}", level=room.level, kind=f.kind,
                   position=(_r(pos[0]), _r(pos[1])), rotation=f.rotation if f.rotation is not None else rot,
                   width=w, depth=d, height=h)


def _custom_shape(cs: CustomShapeDef, design: Design, level: Level) -> CustomFixture:
    """A shape the model composed itself out of parts (box/round), instead of the fixed
    FixtureKind catalog — placed the same way a catalog fixture would be."""
    what = f"custom shape '{cs.id}'"
    room = design.room(cs.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{cs.room}'")
    x0 = min(p.x for p in cs.parts)
    y0 = min(p.y for p in cs.parts)
    x1 = max(p.x + p.w for p in cs.parts)
    y1 = max(p.y + (p.w if p.shape == "round" else p.d) for p in cs.parts)
    w, d, h = x1 - x0, y1 - y0, max(p.z + p.h for p in cs.parts)
    if w <= 0 or d <= 0:
        raise DesignError(f"{what}: parts have no footprint")
    pos, rot = _place_footprint(what, room, cs.side, cs.at, w, d)
    # Parts are given relative to their own min-corner bbox; re-centre them on the origin so
    # `pos` (the bbox centre) is where the whole assembly's local frame actually sits, matching
    # how catalog fixtures are centred (ifc/fixtures.py::_parts).
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    parts = [ShapePart(shape=p.shape, x=_r(p.x - cx), y=_r(p.y - cy), z=p.z, w=p.w, d=p.d, h=p.h) for p in cs.parts]
    return CustomFixture(id=cs.id, name=f"{cs.name} in {room.name}", level=room.level, position=(_r(pos[0]), _r(pos[1])),
                         rotation=cs.rotation if cs.rotation is not None else rot, parts=parts)


def _balcony(b, design: Design, infos: dict[str, RoomInfo], level: Level, els: list) -> None:
    what = f"balcony '{b.id}'"
    room = design.room(b.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{b.room}'")
    wall, side = _exterior_wall(infos[room.id], b.side, what)
    x0, y0, x1, y1 = room.box
    (ax, ay), (bx, by) = wall.start, wall.end
    if wall.horizontal:
        ax, bx = max(ax, x0), min(bx, x1)
        y = y0 - b.depth if side == "S" else y1
        rect = [(ax, y), (bx, y), (bx, y + b.depth), (ax, y + b.depth)]
        rail = [(ax, y0), (ax, y), (bx, y), (bx, y0)] if side == "S" else [(ax, y1), (ax, y1 + b.depth), (bx, y1 + b.depth), (bx, y1)]
    else:
        ay, by = max(ay, y0), min(by, y1)
        x = x0 - b.depth if side == "W" else x1
        rect = [(x, ay), (x + b.depth, ay), (x + b.depth, by), (x, by)]
        rail = [(x0, ay), (x, ay), (x, by), (x0, by)] if side == "W" else [(x1, ay), (x1 + b.depth, ay), (x1 + b.depth, by), (x1, by)]
    inset = 0.05
    rail = [(_r(px + (inset if px < (rail[0][0] + rail[2][0]) / 2 else -inset)), _r(py + (inset if py < (rail[0][1] + rail[2][1]) / 2 else -inset))) for px, py in rail]
    els.append(Slab(id=b.id, name=f"{room.name} balcony", level=room.level, outline=[(_r(px), _r(py)) for px, py in rect], thickness=0.2))
    els.append(Railing(id=f"{b.id}-railing", name=f"{room.name} balcony railing", level=room.level, path=rail, height=1.05))


def _mep(design: Design, levels: list[Level], els: list) -> None:
    """Electrical and plumbing rough-in — always added, on top of whatever furniture/fixtures the
    design already specified: every room gets a ceiling light and two outlets, wired back to one
    riser; a kitchen or bathroom also gets a plumbing riser. Not a routed network, see ifc/mep.py."""
    ground = levels[0]
    ground_rooms = design.rooms_on(ground.id)
    if ground_rooms:
        gx0, gy0, _, _ = ground_rooms[0].box
        riser_xy = (_r(gx0 + 0.3), _r(gy0 + 0.3))
    else:
        riser_xy = (0.3, 0.3)

    wet_pos: tuple[float, float] | None = None
    wet_level: str | None = None
    for level in levels:
        for room in design.rooms_on(level.id):
            x0, y0, x1, y1 = room.box
            cx, cy = _r((x0 + x1) / 2), _r((y0 + y1) / 2)
            sid = room.id
            els.append(LightFixture(id=f"{level.id}-light-{sid}", name=f"{room.name} light", level=level.id, position=(cx, cy)))
            inset = min(0.3, (x1 - x0) / 4, (y1 - y0) / 4)
            outlets = [(_r(x0 + inset), _r(y0 + inset)), (_r(x1 - inset), _r(y1 - inset))]
            for i, pos in enumerate(outlets, 1):
                els.append(Outlet(id=f"{level.id}-outlet-{sid}-{i}", name=f"{room.name} outlet", level=level.id, position=pos))
            # A run whose device sits exactly at the riser tap (the ground-floor reference room's own
            # corner can coincide with riser_xy) would be a zero-length path; skip it, nothing to draw.
            if math.dist(riser_xy, (cx, cy)) > 0.05:
                els.append(Wire(id=f"{level.id}-wire-{sid}-light", level=level.id, path=[riser_xy, (cx, cy)]))
            for i, pos in enumerate(outlets, 1):
                if math.dist(riser_xy, pos) > 0.05:
                    els.append(Wire(id=f"{level.id}-wire-{sid}-outlet-{i}", level=level.id, path=[riser_xy, pos]))
            if room.kind in ("kitchen", "bathroom") and wet_pos is None:
                wet_pos, wet_level = (cx, cy), level.id

    els.append(Panel(id="electrical-panel", name="Electrical panel", level=ground.id, position=riser_xy))
    els.append(Pipe(id="electrical-riser", name="Electrical riser", kind="electrical", bottom_level=ground.id,
                    top_level=levels[-1].id, position=riser_xy, diameter=0.08))
    if wet_pos:
        els.append(Pipe(id="plumbing-riser", name="Main riser", kind="water", bottom_level=ground.id,
                        top_level=wet_level or levels[-1].id, position=wet_pos))


def _porch(design: Design, polys: list[Polygon], els: list) -> None:
    p = design.porch
    if p is None or not polys:
        return
    union = unary_union(polys)
    minx, miny, maxx, maxy = union.bounds
    pts = [(_r(x), _r(y)) for poly in polys for x, y in poly.exterior.coords]
    if p.side in ("S", "N"):
        edge = miny if p.side == "S" else maxy
        xs = [x for x, y in pts if y == _r(edge)]
        a, b = min(xs), max(xs)
        y0, y1 = (edge - p.depth, edge) if p.side == "S" else (edge, edge + p.depth)
        deck = [(a, y0), (b, y0), (b, y1), (a, y1)]
        n = max(2, round((b - a) / 3) + 1)
        cy = y0 + 0.2 if p.side == "S" else y1 - 0.2
        cols = [(_r(a + 0.25 + i * (b - a - 0.5) / (n - 1)), _r(cy)) for i in range(n)]
    else:
        edge = minx if p.side == "W" else maxx
        ys = [y for x, y in pts if x == _r(edge)]
        a, b = min(ys), max(ys)
        x0, x1 = (edge - p.depth, edge) if p.side == "W" else (edge, edge + p.depth)
        deck = [(x0, a), (x1, a), (x1, b), (x0, b)]
        n = max(2, round((b - a) / 3) + 1)
        cx = x0 + 0.2 if p.side == "W" else x1 - 0.2
        cols = [(_r(cx), _r(a + 0.25 + i * (b - a - 0.5) / (n - 1))) for i in range(n)]
    deck = [(_r(x), _r(y)) for x, y in deck]
    els.append(Slab(id="porch-deck", name="Porch deck", level="L1", outline=deck, thickness=0.15))
    els.append(Roof(id="porch-roof", name="Porch roof", level="L1", outline=deck, thickness=0.2))
    for i, (x, y) in enumerate(cols, 1):
        els.append(Column(id=f"porch-col-{i}", name="Porch column", level="L1", position=(x, y), width=0.25, depth=0.25))


# --- the whole thing ----------------------------------------------------------

def _outline(poly: Polygon, grow: float = 0.0) -> list[tuple[float, float]]:
    if grow:
        poly = poly.buffer(grow, join_style="mitre")
    coords = list(poly.exterior.coords)[:-1]
    if poly.exterior.is_ccw is False:
        coords = coords[::-1]
    return [(_r(x), _r(y)) for x, y in coords]


def _polys(poly) -> list[Polygon]:
    if poly.is_empty:
        return []
    polys = [poly] if isinstance(poly, Polygon) else [g for g in poly.geoms if isinstance(g, Polygon) and g.area > 0.5]
    return [p.simplify(0) for p in polys]  # drop collinear vertices so only real corners count as corners


def analyze(design: Design, prune: bool = False) -> Derived:
    """Derive the spec, and per-room adjacency/exterior information for prompts and checks.

    With `prune=True` (used after structural steps: a room moved, a level removed …) openings, stairs,
    fixtures and balconies that no longer fit are dropped with a note instead of failing the design."""
    notes: list[str] = []
    pruned: list[str] = []
    design = design.model_copy(deep=True)
    if not design.levels:
        design.levels = [LevelDef(id="L1")]
    level_ids = {l.id for l in design.levels}
    for r in design.rooms:
        if r.level not in level_ids:
            raise DesignError(f"room '{r.id}' is on unknown level '{r.level}' (levels: {', '.join(sorted(level_ids))})")
    names = {r.id: r.name for r in design.rooms}
    levels = [Level(id=l.id, name=l.display, height=l.height) for l in sorted(design.levels, key=lambda l: l.index)]
    level_by_id = {l.id: l for l in levels}
    els: list = []
    infos: dict[str, RoomInfo] = {}
    footprints: dict[str, list[Polygon]] = {}
    all_walls: dict[str, list[WallSeg]] = {}

    for level in levels:
        rooms = design.rooms_on(level.id)
        unplaced = [r for r in rooms if r.rect is None]
        if unplaced:
            placed = place_rooms([r.rect for r in rooms if r.rect], unplaced)
            for r in unplaced:
                r.rect = placed[r.id]
                notes.append(f"{r.name}: placed automatically at {list(r.rect)}")
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                inter = shp_box(*a.box).intersection(shp_box(*b.box)).area
                if inter > 0.01:
                    raise DesignError(f"room '{a.id}' {list(a.rect)} overlaps room '{b.id}' {list(b.rect)} on {level.id} "
                                      f"by {inter:.1f} m²; rooms on a storey must not overlap (they may share edges)")
        polys = _polys(unary_union([shp_box(*r.box) for r in rooms])) if rooms else []
        footprints[level.id] = polys
        if len(polys) > 1:
            notes.append(f"{level.id}: rooms form {len(polys)} separate blocks")
        vertices = {(_r(x), _r(y)) for p in polys for x, y in p.exterior.coords}
        walls = _walls_for_level(level.id, rooms, vertices, design.wall_material)
        all_walls[level.id] = walls
        for r in rooms:
            infos[r.id] = RoomInfo(r, {}, {})
        for w in walls:
            if w.external:
                infos[w.rooms[0]].exterior.setdefault(w.side, []).append(w)
            else:
                a, b = w.rooms
                infos[a].partitions.setdefault(b, []).append(w)
                infos[b].partitions.setdefault(a, []).append(w)
        for i, poly in enumerate(polys, 1):
            sid = f"{level.id}-floor" if i == 1 else f"{level.id}-floor-{i}"
            els.append(Slab(id=sid, name=f"{level.name} slab", level=level.id, outline=_outline(poly, EXT_T / 2), thickness=0.2))
        for r in rooms:
            x0, y0, x1, y1 = r.box
            els.append(Space(id=f"{level.id}-space-{r.id}", name=r.name, level=level.id,
                             outline=[(x0 + 0.06, y0 + 0.06), (x1 - 0.06, y0 + 0.06), (x1 - 0.06, y1 - 0.06), (x0 + 0.06, y1 - 0.06)]))

    for level in levels:
        for w in all_walls[level.id]:
            els.append(_wall_element(w, level, names, design.wall_material))

    # A ring beam along every exterior wall, hanging from the top of its level — the same wall
    # geometry already computed above, just a structural member instead of a partition. Interior
    # partitions are assumed non-bearing, matching the "deliberately simple" solver (see README).
    for level in levels:
        for w in all_walls[level.id]:
            if w.external:
                els.append(Beam(id=f"{w.id}-beam", name=f"Beam over {names[w.rooms[0]]} {_side_name(w.side)} wall",
                                level=level.id, start=w.start, end=w.end))

    # Roofs: whatever a storey covers that the storey above does not.
    for i, level in enumerate(levels):
        above = unary_union(footprints[levels[i + 1].id]) if i + 1 < len(levels) and footprints[levels[i + 1].id] else None
        here = unary_union(footprints[level.id]) if footprints[level.id] else None
        if here is None:
            continue
        uncovered = here.difference(above) if above is not None else here
        for j, poly in enumerate(_polys(uncovered), 1):
            rid = ("roof" if i == len(levels) - 1 else f"{level.id}-roof") + ("" if j == 1 else f"-{j}")
            outline = _outline(poly, design.roof.overhang)
            shape = design.roof.kind
            if shape != "flat" and not is_axis_rectangle(outline):
                notes.append(f"{rid}: {shape} roofs need a rectangular footprint; this part got a flat roof")
                shape = "flat"
            els.append(Roof(id=rid, name=f"Roof over {level.name}", level=level.id, outline=outline, thickness=0.25 if shape == "flat" else 0.2,
                            shape=shape, pitch=design.roof.pitch))

    # Garages get a garage door if the model forgot one.
    for r in design.rooms:
        if r.kind == "garage" and not any(d.room == r.id and d.kind == "garage" for d in design.doors):
            design.doors.append(DoorDef(id=design.unique_id(f"door-{r.id}-garage"), room=r.id, to="outside", kind="garage", width=2.5))
            notes.append(f"{r.name}: added a garage door")

    def each(attr: str, build):
        kept = []
        for item in getattr(design, attr):
            room = design.room(item.room)
            level = level_by_id[room.level] if room else levels[0]
            try:
                out = build(item, level)
                if out is not None:
                    els.append(out)
                kept.append(item)
            except DesignError as exc:
                if not prune:
                    raise
                pruned.append(f"removed {attr[:-1]} {item.id}: {exc}")
        setattr(design, attr, kept)

    each("doors", lambda d, level: _door(d, design, infos, level))
    each("windows", lambda w, level: _window(w, design, infos, level))
    each("stairs", lambda st, level: _stair(st, design, level))
    each("fixtures", lambda f, level: _fixture(f, design, level))
    each("custom_shapes", lambda cs, level: _custom_shape(cs, design, level))
    each("balconies", lambda b, level: _balcony(b, design, infos, level, els))
    for c in design.columns:
        if c.level not in level_by_id:
            raise DesignError(f"column '{c.id}': unknown level '{c.level}'")
        els.append(Column(id=c.id, level=c.level, position=(_r(c.x), _r(c.y)), width=c.size, depth=c.size))
    _porch(design, footprints[levels[0].id], els)
    _mep(design, levels, els)

    try:
        spec = BuildingSpec(building={"name": design.name, "description": design.description}, levels=levels, elements=els)
    except ValueError as exc:
        raise DesignError(str(exc)) from exc

    if design.overrides:
        from core.ops import OpError, apply_ops  # local: core.ops imports schemas only, but keep derive import-light
        from schemas.ops import op_adapter
        for raw in design.overrides:
            try:
                spec, cascade = apply_ops(spec, [op_adapter.validate_python(raw)])
                notes.extend(cascade)
            except (OpError, ValueError) as exc:
                notes.append(f"override {raw.get('op')} {raw.get('id', '')} skipped: {exc}")
    return Derived(spec, notes + pruned, infos, footprints, design if prune else None, pruned)


def derive(design: Design) -> tuple[BuildingSpec, list[str]]:
    d = analyze(design)
    return d.spec, d.notes
