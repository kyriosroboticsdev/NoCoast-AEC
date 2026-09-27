"""Design → BuildingSpec. Deterministic: the same design always yields the same
elements with the same ids, so GlobalIds survive edits.

Walls come from room outlines (rectangles or polygons, arcs faceted): the
boundaries of all rooms on a storey are noded against each other; a piece touched
by one room is an exterior wall, a piece shared by two rooms a partition. Open
edges get columns instead of a wall, unroofed rooms (courtyards, terraces) get a
railing on their free edges and are left out of the roof. Doors and windows are
then placed along those walls (named by compass side or by a nearby point), stairs
and fixtures inside the rooms, slabs and roofs over the union of the rooms on each
storey; free-standing elements are added as they are. Raw ops stored as
`overrides` are replayed at the end.

Everything that can go wrong raises DesignError with a message written for the
model ("kitchen has no exterior wall on side N; its exterior sides are S, W").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, MultiLineString, Point as ShpPoint, Polygon
from shapely.ops import unary_union

from core.derive_bricks import ROOF_T, SLAB_T, building_frames, derive_bricks, needs_water
from core.rooms import (CLEAR, DesignError, RoomInfo, WallSeg, compass, exterior_walls, fits, pick_wall, place_piece,
                        r2, rect_at, side_name)
from ifc.fixtures import default_size
from schemas.bim import (Asset, Beam, BuildingSpec, Column, CustomFixture, Door, Fixture, Level, LightFixture, Outlet, Panel,
                         Pipe, Railing, Roof, ShapePart, Slab, Space, Stair, Wall, Window, Wire, is_axis_rectangle)
from schemas.design import (CustomShapeDef, Design, DoorDef, FixtureDef, FreeDef, LevelDef, Pt, RoomDef, Segment, Side,
                            StairDef, WindowDef)
from solver.layout import place_rooms

EXT_T, INT_T = 0.3, 0.12
MARGIN = 0.15          # openings keep this far from wall ends
COLUMN_EVERY = 4.0     # open edges get a column at least this often
DOOR_SIZES = {"single": (0.9, 2.1), "double": (1.6, 2.1), "sliding": (1.8, 2.1), "french": (1.6, 2.1), "garage": (2.4, 2.2)}
WINDOW_SIZES = {"standard": (1.2, 1.2, 0.9), "large": (2.0, 1.6, 0.6), "floor": (2.0, 2.2, 0.1), "small": (0.6, 0.6, 1.5)}
ROUGH_IN = ("water_cold", "drain", "power")   # connector kinds the derived services supply once there are rooms



@dataclass
class Derived:
    spec: BuildingSpec
    notes: list[str]
    rooms: dict[str, RoomInfo]
    footprints: dict[str, list[Polygon]]
    design: Design | None = None   # the design actually built (with pruned items removed) when prune=True
    pruned: list[str] = field(default_factory=list)
    sides: dict[str, Side] = field(default_factory=dict)  # opening/balcony id -> compass side of its wall
    provided: tuple[str, ...] = ()                        # connector kinds the building itself supplies



# --- walls ------------------------------------------------------------------

@dataclass
class _Piece:
    a: Pt
    b: Pt
    seg: Segment
    others: list[tuple[str, Segment]]   # other rooms that own this piece, with their segment


def _room_pieces(room: RoomDef, others: list[RoomDef], noded: list[LineString]) -> list[_Piece]:
    """The noded pieces of `room`'s boundary, in boundary order, each tagged with the other rooms sharing it."""
    out: list[_Piece] = []
    other_segs = [(o.id, s) for o in others for s in o.segments()]
    for seg in room.segments():
        line = LineString([seg.a, seg.b])
        on: list[tuple[float, Pt, Pt]] = []
        for piece in noded:
            coords = list(piece.coords)
            for a, b in zip(coords, coords[1:]):
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if line.distance(ShpPoint(mid)) < 1e-6 and line.distance(ShpPoint(a)) < 1e-6 and line.distance(ShpPoint(b)) < 1e-6:
                    ta, tb = line.project(ShpPoint(a)), line.project(ShpPoint(b))
                    if ta > tb:
                        a, b, ta, tb = b, a, tb, ta
                    on.append((ta, (r2(a[0]), r2(a[1])), (r2(b[0]), r2(b[1]))))
        on.sort()
        for _, a, b in on:
            mid = ShpPoint((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            owners = [(oid, s) for oid, s in other_segs if LineString([s.a, s.b]).distance(mid) < 1e-6]
            out.append(_Piece(a, b, seg, owners))
    return out


def _walls_for_level(level_id: str, rooms: list[RoomDef], polys: dict[str, Polygon], corners: set[Pt],
                     els: list, notes: list[str], open_sides: dict[str, set[Side]]) -> list[WallSeg]:
    """Derive the wall network of one storey from its room outlines.

    Every room boundary is noded against the others; runs of consecutive pieces with the same
    classification are merged into one wall (chords of one arc into one faceted wall)."""
    if not rooms:
        return []
    all_lines = [LineString([s.a, s.b]) for r in rooms for s in r.segments()]
    noded = unary_union(all_lines)
    noded = list(noded.geoms) if isinstance(noded, MultiLineString) else [noded]
    walls: list[WallSeg] = []
    counts: dict[str, int] = {}
    by_id = {r.id: r for r in rooms}

    def wall_id(base: str) -> str:
        counts[base] = counts.get(base, 0) + 1
        return base if counts[base] == 1 else f"{base}-{counts[base]}"

    for room in rooms:
        others = [o for o in rooms if o.id != room.id]
        pieces = _room_pieces(room, others, noded)
        # Classify each piece: ("ext", None) exterior wall of this room; ("part", other) partition;
        # ("open", None) open edge; ("rail", None) railing (unroofed room's free edge); ("skip", other)
        # the other room emits it; ("none", None) nothing at all.
        runs: list[list] = []
        for p in pieces:
            mine_open = p.seg.open or not room.enclosed
            if p.others:
                oid, oseg = p.others[0]
                other = by_id[oid]
                theirs_open = oseg.open or not other.enclosed
                if mine_open and theirs_open:
                    kind, arg = "none", None
                elif mine_open:
                    kind, arg = "skip", oid          # the neighbour's exterior wall
                elif theirs_open:
                    kind, arg = "ext", None          # my wall faces their open space
                elif not room.roofed and other.roofed:
                    kind, arg = "skip", oid          # a roofed neighbour's exterior wall faces my courtyard
                elif room.roofed and not other.roofed:
                    kind, arg = "ext", None
                elif not room.roofed and not other.roofed:
                    kind, arg = "none", None
                elif room.id < oid:
                    kind, arg = "part", oid
                else:
                    kind, arg = "skip", oid
            else:
                kind, arg = ("open", None) if mine_open else ("rail", None) if not room.roofed else ("ext", None)
            same = runs and runs[-1][0] == (kind, arg, p.seg.edge if p.seg.arc else None) and runs[-1][2][-1] == p.a and (
                p.seg.arc or _collinear(runs[-1][2][-2], runs[-1][2][-1], p.b))
            if same:
                runs[-1][2].append(p.b)
                runs[-1][3].append(p)
            else:
                runs.append([(kind, arg, p.seg.edge if p.seg.arc else None), p.seg, [p.a, p.b], [p]])

        poly = polys[room.id]
        for (kind, arg, _), seg, path, ps in runs:
            if kind in ("skip", "none"):
                continue
            path = _dedupe(path)
            if len(path) < 2:
                continue
            probe = WallSeg("", level_id, path, True, (room.id,), None, seg.arc)
            ix, iy = probe.inward(poly)
            side = compass(-ix, -iy)
            radius = _arc_radius(room, seg.edge) if seg.arc else None
            if kind == "ext":
                wid = wall_id(f"{level_id}-wall-{room.id}-{side}")
                if not seg.arc:
                    path = _extend(path, corners, EXT_T / 2)
                walls.append(WallSeg(wid, level_id, path, True, (room.id,), side, seg.arc, radius))
            elif kind == "part":
                pair = tuple(sorted((room.id, arg)))
                wid = wall_id(f"{level_id}-wall-{pair[0]}+{pair[1]}")
                walls.append(WallSeg(wid, level_id, path, False, pair, None, seg.arc, radius))
            elif kind == "rail":
                rid = wall_id(f"{level_id}-rail-{room.id}-{side}")
                els.append(Railing(id=rid, name=f"{room.name} railing", level=level_id, path=[(r2(x), r2(y)) for x, y in path], height=1.05))
            elif kind == "open":
                # Columns along the open edge, and a beam over it carrying the roof.
                open_sides.setdefault(room.id, set()).add(side)
                line = LineString(path)
                n = max(2, math.ceil(line.length / COLUMN_EVERY) + 1)
                for i in range(n):
                    p = line.interpolate(i / (n - 1), normalized=True)
                    cid = wall_id(f"{level_id}-col-{room.id}-{side}")
                    els.append(Column(id=cid, name=f"{room.name} column", level=level_id, position=(r2(p.x), r2(p.y)), width=0.25, depth=0.25))
                if room.roofed:
                    for a, b in zip(path, path[1:]):
                        bid = wall_id(f"{level_id}-beam-{room.id}-{side}")
                        els.append(Beam(id=bid, name=f"{room.name} beam", level=level_id, start=a, end=b, width=0.25, depth=0.3))
    return walls




def _dedupe(path: list[Pt]) -> list[Pt]:
    out: list[Pt] = []
    for p in path:
        if not out or math.dist(out[-1], p) > 1e-6:
            out.append(p)
    return out


def _collinear(a: Pt, b: Pt, c: Pt) -> bool:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-6


def _extend(path: list[Pt], corners: set[Pt], by: float) -> list[Pt]:
    """Push a straight exterior wall's ends out by `by` where they sit on an outline corner, so
    perpendicular walls overlap at the corner instead of leaving a notch."""
    (ax, ay), (bx, by_) = path[0], path[-1]
    d = math.dist(path[0], path[-1]) or 1.0
    ux, uy = (bx - ax) / d, (by_ - ay) / d
    a, b = path[0], path[-1]
    if (r2(ax), r2(ay)) in corners:
        a = (r2(ax - ux * by), r2(ay - uy * by))
    if (r2(bx), r2(by_)) in corners:
        b = (r2(bx + ux * by), r2(by_ + uy * by))
    return [a, b]


def _arc_radius(room: RoomDef, edge: int) -> float | None:
    edges = room.edges()
    e = edges[edge]
    if not e.through:
        return None
    a, m, b = edges[edge - 1].to, e.through, e.to
    d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
    if abs(d) < 1e-9:
        return None
    ux = ((a[0] ** 2 + a[1] ** 2) * (m[1] - b[1]) + (m[0] ** 2 + m[1] ** 2) * (b[1] - a[1]) + (b[0] ** 2 + b[1] ** 2) * (a[1] - m[1])) / d
    uy = ((a[0] ** 2 + a[1] ** 2) * (b[0] - m[0]) + (m[0] ** 2 + m[1] ** 2) * (a[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (m[0] - a[0])) / d
    return r2(math.hypot(a[0] - ux, a[1] - uy))


def _wall_element(w: WallSeg, names: dict[str, str], material) -> Wall:
    if not w.rooms:
        name = w.id
    elif w.external:
        name = f"{names[w.rooms[0]]} {side_name(w.side)} wall"
    else:
        name = f"{names[w.rooms[0]]} / {names[w.rooms[1]]} partition"
    return Wall(id=w.id, name=name, level=w.level, start=w.start, end=w.end, path=w.path if len(w.path) > 2 else None,
                thickness=EXT_T if w.external else INT_T, external=w.external, material=material if w.external else None,
                radius=w.radius)




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
    return r2(min(max(wanted, lo), hi))




def _host(item, design: Design, infos: dict[str, RoomInfo], free_walls: dict[str, WallSeg], what: str,
          exterior_only: bool) -> tuple[WallSeg, float, RoomDef | None]:
    """Resolve the wall a door/window sits on and the fraction along it."""
    if item.wall:
        w = free_walls.get(item.wall)
        if w is None:
            raise DesignError(f"{what}: unknown free wall '{item.wall}' (free walls: {', '.join(free_walls) or 'none'})")
        at = item.at
        if item.near is not None:
            at = w.line.project(ShpPoint(item.near), normalized=True)
        return w, at, None
    if not item.room:
        raise DesignError(f"{what}: needs a `room` (or `wall` for a free-standing wall)")
    room = design.room(item.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{item.room}' (rooms: {', '.join(r.id for r in design.rooms)})")
    info = infos[room.id]
    if exterior_only:
        cands = exterior_walls(info)
        if not cands:
            extra = f" (its open sides: {', '.join(info.open_sides)})" if info.open_sides else ""
            raise DesignError(f"{what}: room '{room.id}' has no exterior wall at all{extra}")
        wall, at = pick_wall(cands, item.near, item.side, what, room, info.sides)
    else:
        wall, at = pick_wall(info.walls, item.near, item.side, what, room, info.sides)
    return wall, item.at if at is None else at, room


def _door(d: DoorDef, design: Design, infos: dict[str, RoomInfo], free_walls: dict[str, WallSeg], levels: dict[str, Level],
          sides: dict[str, Side]) -> Door:
    what = f"door '{d.id}'"
    width, height = DOOR_SIZES[d.kind]
    width, height = d.width or width, d.height or height
    outside = d.to.lower() in ("outside", "exterior", "out", "outdoors", "garden", "street")
    if d.wall or outside:
        wall, at, room = _host(d, design, infos, free_walls, what, exterior_only=not d.wall)
        other = None
    else:
        room = design.room(d.room) if d.room else None
        if room is None:
            raise DesignError(f"{what}: unknown room '{d.room}' (rooms: {', '.join(r.id for r in design.rooms)})")
        other = design.room(d.to)
        if other is None:
            raise DesignError(f"{what}: unknown room '{d.to}' (rooms: {', '.join(r.id for r in design.rooms)})")
        if other.level != room.level:
            raise DesignError(f"{what}: '{room.id}' ({room.level}) and '{other.id}' ({other.level}) are on different storeys")
        shared = infos[room.id].partitions.get(other.id)
        if not shared:
            raise DesignError(f"{what}: '{room.id}' and '{other.id}' do not share a wall "
                              f"('{room.id}' touches: {', '.join(infos[room.id].neighbours) or 'nothing'})")
        wall, at = pick_wall(shared, d.near, None, what, room)
        at = d.at if at is None else at
    level = levels[wall.level]
    wall_h = wall.height or level.height
    if height > wall_h - 0.05:
        height = r2(wall_h - 0.1)
    offset = _place(wall, width, at, what)
    wall.openings.append((offset, width, d.id))
    if wall.side:
        sides[d.id] = wall.side
    if room is None:
        name = f"Door in {wall.id}"
    elif other is None:
        name = f"{room.name} entrance"
    else:
        name = f"{room.name} / {other.name} door"
    return Door(id=d.id, name=name, wall=wall.id, offset=offset, width=width, height=height, kind=d.kind)


def _window(w: WindowDef, design: Design, infos: dict[str, RoomInfo], free_walls: dict[str, WallSeg], levels: dict[str, Level],
            sides: dict[str, Side]) -> Window:
    what = f"window '{w.id}'"
    if w.room and not w.wall:
        room = design.room(w.room)
        if room is None:
            raise DesignError(f"{what}: unknown room '{w.room}' (rooms: {', '.join(r.id for r in design.rooms)})")
        if design.level(room.level).below_ground:
            raise DesignError(f"{what}: room '{room.id}' is on {room.level}, which is below ground; basement rooms cannot have windows")
    wall, at, room = _host(w, design, infos, free_walls, what, exterior_only=True)
    level = levels[wall.level]
    wall_h = wall.height or level.height
    width, height, sill = WINDOW_SIZES[w.kind]
    width, height, sill = w.width or width, w.height or height, w.sill if w.sill is not None else sill
    if sill + height > wall_h - 0.1:
        height = r2(max(0.4, wall_h - 0.1 - sill))
    if sill + height > wall_h:
        raise DesignError(f"{what}: wall {wall.id} is only {wall_h:.2f} m high")
    offset = _place(wall, width, at, what)
    wall.openings.append((offset, width, w.id))
    if wall.side:
        sides[w.id] = wall.side
    name = f"{room.name} {side_name(wall.side)} window" if room and wall.side else f"Window in {wall.id}"
    return Window(id=w.id, name=name, wall=wall.id, offset=offset, width=width, height=height, sill_height=sill)


# --- things inside rooms ----------------------------------------------------





def _stair(s: StairDef, design: Design, infos: dict[str, RoomInfo], level: Level) -> Stair:
    what = f"stair '{s.id}'"
    room = design.room(s.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{s.room}'")
    info = infos[room.id]
    above = design.level_above(room.level)
    to_level = s.to_level or (above.id if above else None)
    if to_level and design.level(to_level) is None:
        raise DesignError(f"{what}: unknown to_level '{to_level}'")
    stair = Stair(id=s.id, name=f"Stair in {room.name}", level=room.level, position=(0, 0), width=s.width, to_level=to_level)
    run = stair.run(level.height)
    need = run + 0.4
    straight = [w for w in info.walls if w.straight]
    if not straight:
        raise DesignError(f"{what}: room '{room.id}' has no straight wall for a flight")
    if s.near is None and s.side is None:
        wall = max(straight, key=lambda w: w.length)
    else:
        wall, _ = pick_wall(straight, s.near, s.side, what, room, None, info.polygon)
    if wall.length < need:
        raise DesignError(f"{what}: wall {wall.id} of room '{room.id}' is {wall.length:.2f} m long but a straight flight "
                          f"needs {need:.2f} m; use a longer wall or enlarge the room")
    # Run along the wall from its start, inset from the wall by CLEAR + half the width.
    poly = info.polygon
    ux, uy = wall.unit()
    ix, iy = wall.inward(poly)
    # Start at whichever end of the wall the flight fits from (the wall may have been emitted by a neighbour);
    # prefer ascending towards +x/+y so rectangular rooms keep their familiar layout.
    options = [((wall.start[0], wall.start[1]), (ux, uy)), ((wall.end[0], wall.end[1]), (-ux, -uy))]
    options.sort(key=lambda o: -(o[1][0] + o[1][1]))
    for (sx, sy), (dx, dy) in options:
        x0 = sx + dx * 0.3 + ix * (CLEAR + s.width / 2)
        y0 = sy + dy * 0.3 + iy * (CLEAR + s.width / 2)
        cx, cy = x0 + dx * run / 2, y0 + dy * run / 2
        angle = math.atan2(dy, dx)
        if fits(poly, rect_at(cx, cy, s.width, run, angle - math.pi / 2)):
            stair.position, stair.direction = (r2(x0), r2(y0)), r2(math.degrees(angle) % 360)
            return stair
    raise DesignError(f"{what}: a {run:.2f} × {s.width} m flight along wall {wall.id} does not fit inside room '{room.id}'")




def _fixture(f: FixtureDef, design: Design, infos: dict[str, RoomInfo], level: Level) -> Fixture:
    what = f"{f.kind} '{f.id}'"
    room = design.room(f.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{f.room}'")
    w, d, h = default_size(f.kind)
    w, d, h = f.width or w, f.depth or d, f.height or h
    pos, rot = place_piece(what, room, infos[room.id], f.side, f.near, f.at, w, d)
    return Fixture(id=f.id, name=f"{f.kind.replace('_', ' ')} in {room.name}", level=room.level, kind=f.kind,
                   position=pos, rotation=f.rotation if f.rotation is not None else rot, width=w, depth=d, height=h)


def _custom_shape(cs: CustomShapeDef, design: Design, infos: dict[str, RoomInfo], level: Level) -> CustomFixture:
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
    w, d = x1 - x0, y1 - y0
    if w <= 0 or d <= 0:
        raise DesignError(f"{what}: parts have no footprint")
    pos, rot = place_piece(what, room, infos[room.id], cs.side, cs.near, cs.at, w, d)
    # Parts are given relative to their own min-corner bbox; re-centre them on the origin so
    # `pos` (the bbox centre) is where the whole assembly's local frame actually sits, matching
    # how catalog fixtures are centred (ifc/fixtures.py::_parts).
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    parts = [ShapePart(shape=p.shape, x=r2(p.x - cx), y=r2(p.y - cy), z=p.z, w=p.w, d=p.d, h=p.h) for p in cs.parts]
    return CustomFixture(id=cs.id, name=f"{cs.name} in {room.name}", level=room.level, position=pos,
                         rotation=cs.rotation if cs.rotation is not None else rot, parts=parts)




def _balcony(b, design: Design, infos: dict[str, RoomInfo], level: Level, els: list, sides: dict[str, Side]) -> None:
    what = f"balcony '{b.id}'"
    room = design.room(b.room)
    if room is None:
        raise DesignError(f"{what}: unknown room '{b.room}'")
    info = infos[room.id]
    cands = [w for w in exterior_walls(info) if w.straight]
    if not cands:
        raise DesignError(f"{what}: room '{room.id}' has no straight exterior wall")
    wall, _ = pick_wall(cands, b.near, b.side, what, room, info.sides)
    sides[b.id] = wall.side
    ux, uy = wall.unit()
    ix, iy = wall.inward(info.polygon)
    ox, oy = -ix, -iy
    # Deck along the room's own edge (the wall may be extended at corners), pushed out by the depth.
    line = LineString([wall.start, wall.end])
    edge = info.polygon.exterior.intersection(line.buffer(0.01))
    a, c = (wall.start, wall.end) if edge.is_empty else (edge.bounds[0:2], edge.bounds[2:4])
    if edge.is_empty or math.dist(a, c) < 0.5:
        a, c = wall.start, wall.end
    if (c[0] - a[0]) * ux + (c[1] - a[1]) * uy < 0:
        a, c = c, a
    deck = [a, c, (c[0] + ox * b.depth, c[1] + oy * b.depth), (a[0] + ox * b.depth, a[1] + oy * b.depth)]
    inset = 0.05
    rail = [(a[0] + ux * inset, a[1] + uy * inset),
            (a[0] + ux * inset + ox * (b.depth - inset), a[1] + uy * inset + oy * (b.depth - inset)),
            (c[0] - ux * inset + ox * (b.depth - inset), c[1] - uy * inset + oy * (b.depth - inset)),
            (c[0] - ux * inset, c[1] - uy * inset)]
    els.append(Slab(id=b.id, name=f"{room.name} balcony", level=room.level, outline=[(r2(px), r2(py)) for px, py in deck], thickness=0.2))
    els.append(Railing(id=f"{b.id}-railing", name=f"{room.name} balcony railing", level=room.level,
                       path=[(r2(px), r2(py)) for px, py in rail], height=1.05))


def _free(e: FreeDef, design: Design, levels: dict[str, Level], els: list, free_walls: dict[str, WallSeg]) -> None:
    what = f"{e.kind} '{e.id}'"
    if e.level not in levels:
        raise DesignError(f"{what}: unknown level '{e.level}' (levels: {', '.join(levels)})")
    name = e.name or e.id
    if e.kind == "wall":
        segs = e.path_segments()
        pts = _dedupe([segs[0].a] + [s.b for s in segs]) if segs else []
        if len(pts) < 2:
            raise DesignError(f"{what}: path has no length")
        w = WallSeg(e.id, e.level, pts, True, (), None, any(s.arc for s in segs), height=e.height)
        free_walls[e.id] = w
        els.append(Wall(id=e.id, name=name, level=e.level, start=pts[0], end=pts[-1], path=pts if len(pts) > 2 else None,
                        thickness=e.thickness or 0.2, height=e.height, external=True, material=design.wall_material))
    elif e.kind == "slab":
        els.append(Slab(id=e.id, name=name, level=e.level, outline=e.outline(), thickness=e.thickness or 0.2))
    elif e.kind == "roof":
        els.append(Roof(id=e.id, name=name, level=e.level, outline=e.outline(), thickness=e.thickness or 0.2, shape="flat"))
    elif e.kind == "column":
        size = e.width or 0.3
        els.append(Column(id=e.id, name=name, level=e.level, position=e.at, width=size, depth=e.depth or size, height=e.height))
    elif e.kind == "beam":
        els.append(Beam(id=e.id, name=name, level=e.level, start=e.start, end=e.end, width=e.width or 0.2, depth=e.depth or 0.3))


def _mep(design: Design, levels: list[Level], infos: dict[str, RoomInfo], els: list) -> None:
    """Electrical and plumbing rough-in — always added, on top of whatever furniture/fixtures the
    design already specified: every enclosed room gets a ceiling light and two outlets, wired back to
    one riser; every kitchen or bathroom also gets its own plumbing riser. Not a routed network, see
    ifc/mep.py."""
    if not design.rooms:
        return  # nothing to wire yet
    ground = next((l for l in levels if design.level(l.id).index >= 0), levels[0])
    ground_rooms = design.rooms_on(ground.id)
    # A utility/garage/storage room is where a panel actually belongs; only fall back to "the first
    # room's corner" when the design has none of those, so the panel doesn't land in a bedroom or
    # living room.
    utility = next((r for r in ground_rooms if r.kind in ("utility", "garage", "storage")), None)
    corner_of = utility or (ground_rooms[0] if ground_rooms else None)
    if corner_of:
        gx0, gy0, _, _ = corner_of.box
        riser_xy = (r2(gx0 + 0.3), r2(gy0 + 0.3))
    else:
        riser_xy = (0.3, 0.3)

    wet_rooms = {a.ref for a in els if isinstance(a, Asset) and a.ref and needs_water(design, a.brick)}
    wet_risers: list[tuple[tuple[float, float], str]] = []
    for level in levels:
        for room in design.rooms_on(level.id):
            if not room.roofed:
                continue
            poly = infos[room.id].polygon
            c = poly.centroid if poly.contains(poly.centroid) else poly.representative_point()
            cx, cy = r2(c.x), r2(c.y)
            sid = room.id
            els.append(LightFixture(id=f"{level.id}-light-{sid}", name=f"{room.name} light", level=level.id, position=(cx, cy)))
            outlets: list[Pt] = []
            if room.enclosed:
                x0, y0, x1, y1 = room.box
                inset = min(0.3, (x1 - x0) / 4, (y1 - y0) / 4)
                for pos in ((r2(x0 + inset), r2(y0 + inset)), (r2(x1 - inset), r2(y1 - inset))):
                    if poly.contains(ShpPoint(pos)):
                        outlets.append(pos)
            outlet_objs: list[Outlet] = []
            for i, pos in enumerate(outlets, 1):
                outlet = Outlet(id=f"{level.id}-outlet-{sid}-{i}", name=f"{room.name} outlet", level=level.id, position=pos)
                outlet_objs.append(outlet)
                els.append(outlet)
            # A run whose device sits exactly at the riser tap (the ground-floor reference room's own
            # corner can coincide with riser_xy) would be a zero-length path; skip it, nothing to draw.
            if math.dist(riser_xy, (cx, cy)) > 0.05:
                els.append(Wire(id=f"{level.id}-wire-{sid}-light", level=level.id, path=[riser_xy, (cx, cy)]))
            for i, outlet in enumerate(outlet_objs, 1):
                if math.dist(riser_xy, outlet.position) > 0.05:
                    # Run at the outlet's own height, not the ceiling: a ceiling-height run reads as a
                    # wire floating with no connection down to an outlet mounted near the floor.
                    els.append(Wire(id=f"{level.id}-wire-{sid}-outlet-{i}", level=level.id,
                                    path=[riser_xy, outlet.position], elevation=outlet.height))
            if room.kind in ("kitchen", "bathroom") or room.id in wet_rooms:
                wet_risers.append(((cx, cy), level.id))

    els.append(Panel(id="electrical-panel", name="Electrical panel", level=ground.id, position=riser_xy))
    els.append(Pipe(id="electrical-riser", name="Electrical riser", kind="electrical", bottom_level=ground.id,
                    top_level=levels[-1].id, position=riser_xy, diameter=0.08))
    below = {l.id for l in levels if design.level(l.id).index < 0}
    for i, (pos, wet_level) in enumerate(wet_risers, 1):
        suffix = "" if i == 1 else f"-{i}"
        bottom, top = (wet_level, ground.id) if wet_level in below else (ground.id, wet_level)
        els.append(Pipe(id=f"plumbing-riser{suffix}", name="Main riser" if i == 1 else f"Riser {i}", kind="water",
                        bottom_level=bottom, top_level=top, position=pos))


def _porch(design: Design, polys: list[Polygon], els: list, ground: str = "L1") -> None:
    p = design.porch
    if p is None or not polys:
        return
    union = unary_union(polys)
    minx, miny, maxx, maxy = union.bounds
    pts = [(r2(x), r2(y)) for poly in polys for x, y in poly.exterior.coords]
    if p.side in ("S", "N"):
        edge = miny if p.side == "S" else maxy
        xs = [x for x, y in pts if abs(y - r2(edge)) < 0.01]
        a, b = min(xs), max(xs)
        y0, y1 = (edge - p.depth, edge) if p.side == "S" else (edge, edge + p.depth)
        deck = [(a, y0), (b, y0), (b, y1), (a, y1)]
        n = max(2, round((b - a) / 3) + 1)
        cy = y0 + 0.2 if p.side == "S" else y1 - 0.2
        cols = [(r2(a + 0.25 + i * (b - a - 0.5) / (n - 1)), r2(cy)) for i in range(n)]
    else:
        edge = minx if p.side == "W" else maxx
        ys = [y for x, y in pts if abs(x - r2(edge)) < 0.01]
        a, b = min(ys), max(ys)
        x0, x1 = (edge - p.depth, edge) if p.side == "W" else (edge, edge + p.depth)
        deck = [(x0, a), (x1, a), (x1, b), (x0, b)]
        n = max(2, round((b - a) / 3) + 1)
        cx = x0 + 0.2 if p.side == "W" else x1 - 0.2
        cols = [(r2(cx), r2(a + 0.25 + i * (b - a - 0.5) / (n - 1))) for i in range(n)]
    if b - a < 1.0:
        return
    deck = [(r2(x), r2(y)) for x, y in deck]
    els.append(Slab(id="porch-deck", name="Porch deck", level=ground, outline=deck, thickness=0.15))
    els.append(Roof(id="porch-roof", name="Porch roof", level=ground, outline=deck, thickness=0.2))
    for i, (x, y) in enumerate(cols, 1):
        els.append(Column(id=f"porch-col-{i}", name="Porch column", level=ground, position=(x, y), width=0.25, depth=0.25))


# --- the whole thing ----------------------------------------------------------

def space_id(level_id: str, room_id: str) -> str:
    return f"{level_id}-space-{room_id}"


def _outline(poly: Polygon, grow: float = 0.0) -> list[tuple[float, float]]:
    if grow:
        poly = poly.buffer(grow, join_style="mitre")
    coords = list(poly.exterior.coords)[:-1]
    if poly.exterior.is_ccw is False:
        coords = coords[::-1]
    return [(r2(x), r2(y)) for x, y in coords]


def _polys(poly) -> list[Polygon]:
    if poly.is_empty:
        return []
    polys = [poly] if isinstance(poly, Polygon) else [g for g in poly.geoms if isinstance(g, Polygon) and g.area > 0.5]
    return [p.simplify(0) for p in polys]  # drop collinear vertices so only real corners count as corners


def _space_outline(poly: Polygon) -> list[Pt]:
    inner = poly.buffer(-0.06, join_style="mitre")
    if inner.is_empty or not isinstance(inner, Polygon):
        inner = poly
    return _outline(inner)


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
    # Storeys stack upward from the ground floor at 0; basements stack downward from it.
    ordered = design.ordered_levels()
    elevations: dict[str, float] = {}
    z = 0.0
    for l in ordered:
        if l.index >= 0:
            elevations[l.id] = r2(z)
            z += l.height
    z = 0.0
    for l in reversed([l for l in ordered if l.index < 0]):
        z -= l.height
        elevations[l.id] = r2(z)
    levels = [Level(id=l.id, name=l.display, height=l.height, elevation=elevations[l.id]) for l in ordered]
    level_by_id = {l.id: l for l in levels}
    ground = next((l for l in levels if design.level(l.id).index >= 0), levels[0])
    below_ground = {l.id for l in ordered if l.below_ground}
    els: list = []
    infos: dict[str, RoomInfo] = {}
    footprints: dict[str, list[Polygon]] = {}
    roofprints: dict[str, list[Polygon]] = {}
    all_walls: dict[str, list[WallSeg]] = {}
    sides: dict[str, Side] = {}

    for level in levels:
        rooms = design.rooms_on(level.id)
        unplaced = [r for r in rooms if not r.placed]
        if unplaced:
            placed = place_rooms([r.rect for r in rooms if r.is_rect], unplaced)
            for r in unplaced:
                r.rect = placed[r.id]
                notes.append(f"{r.name}: placed automatically at {list(r.rect)}")
        polys_by_room = {r.id: r.polygon() for r in rooms}
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                inter = polys_by_room[a.id].intersection(polys_by_room[b.id]).area
                if inter > 0.01:
                    raise DesignError(f"room '{a.id}' overlaps room '{b.id}' on {level.id} by {inter:.1f} m²; "
                                      f"rooms on a storey must not overlap (they may share edges)")
        polys = _polys(unary_union(list(polys_by_room.values()))) if rooms else []
        footprints[level.id] = polys
        roofprints[level.id] = _polys(unary_union([polys_by_room[r.id] for r in rooms if r.roofed])) if any(r.roofed for r in rooms) else []
        if len(polys) > 1:
            notes.append(f"{level.id}: rooms form {len(polys)} separate blocks")
        corners = {(r2(x), r2(y)) for p in polys for x, y in p.exterior.coords}
        open_sides: dict[str, set[Side]] = {}
        walls = _walls_for_level(level.id, rooms, polys_by_room, corners, els, notes, open_sides)
        all_walls[level.id] = walls
        for r in rooms:
            infos[r.id] = RoomInfo(r, polys_by_room[r.id], {}, {}, sorted(open_sides.get(r.id, ())))
        for w in walls:
            if w.external:
                infos[w.rooms[0]].exterior.setdefault(w.side, []).append(w)
            else:
                a, b = w.rooms
                infos[a].partitions.setdefault(b, []).append(w)
                infos[b].partitions.setdefault(a, []).append(w)
        slab_polys = polys
        ground_courtyards = [polys_by_room[r.id] for r in rooms if r.kind == "courtyard" and level.id == ground.id]
        if ground_courtyards:
            slab_polys = _polys(unary_union(list(polys_by_room.values())).difference(unary_union(ground_courtyards)))
        for i, poly in enumerate(slab_polys, 1):
            sid = f"{level.id}-floor" if i == 1 else f"{level.id}-floor-{i}"
            els.append(Slab(id=sid, name=f"{level.name} slab", level=level.id, outline=_outline(poly, EXT_T / 2), thickness=SLAB_T))
        for r in rooms:
            els.append(Space(id=space_id(level.id, r.id), name=r.name, level=level.id, outline=_space_outline(polys_by_room[r.id])))

    for level in levels:
        for w in all_walls[level.id]:
            els.append(_wall_element(w, names, design.wall_material))

    # A ring beam along every exterior wall, hanging from the top of its level — the same wall
    # geometry already computed above, just a structural member instead of a partition. Interior
    # partitions are assumed non-bearing, matching the "deliberately simple" solver (see README).
    for level in levels:
        for w in all_walls[level.id]:
            if w.external and w.rooms:
                for a, b in zip(w.path, w.path[1:]):
                    bid = f"{w.id}-beam" if len(w.path) == 2 else f"{w.id}-beam-{w.path.index(a) + 1}"
                    els.append(Beam(id=bid, name=f"Beam over {names[w.rooms[0]]} {side_name(w.side)} wall", level=level.id, start=a, end=b))

    # Roofs: whatever a storey's roofed rooms cover that the storey above does not. Basements get none.
    for i, level in enumerate(levels):
        if level.id in below_ground:
            continue
        above = unary_union(footprints[levels[i + 1].id]) if i + 1 < len(levels) and footprints[levels[i + 1].id] else None
        here = unary_union(roofprints[level.id]) if roofprints[level.id] else None
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
            els.append(Roof(id=rid, name=f"Roof over {level.name}", level=level.id, outline=outline, thickness=ROOF_T if shape == "flat" else 0.2,
                            shape=shape, pitch=design.roof.pitch))

    # Free-standing elements (walls first: doors and windows may sit on them).
    free_walls: dict[str, WallSeg] = {}
    for e in design.elements:
        _free(e, design, level_by_id, els, free_walls)

    # Garages get a garage door if the model forgot one.
    for r in design.rooms:
        if r.kind == "garage" and not any(d.room == r.id and d.kind == "garage" for d in design.doors):
            design.doors.append(DoorDef(id=design.unique_id(f"door-{r.id}-garage"), room=r.id, to="outside", kind="garage", width=2.5))
            notes.append(f"{r.name}: added a garage door")

    def each(attr: str, build):
        kept = []
        for item in getattr(design, attr):
            room = design.room(item.room) if getattr(item, "room", None) else None
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

    each("doors", lambda d, level: _door(d, design, infos, free_walls, level_by_id, sides))
    each("windows", lambda w, level: _window(w, design, infos, free_walls, level_by_id, sides))
    each("stairs", lambda st, level: _stair(st, design, infos, level))
    each("fixtures", lambda f, level: _fixture(f, design, infos, level))
    each("custom_shapes", lambda cs, level: _custom_shape(cs, design, infos, level))
    each("balconies", lambda b, level: _balcony(b, design, infos, level, els, sides))
    for c in design.columns:
        if c.level not in level_by_id:
            raise DesignError(f"column '{c.id}': unknown level '{c.level}'")
        els.append(Column(id=c.id, level=c.level, position=(r2(c.x), r2(c.y)), width=c.size, depth=c.size))
    _porch(design, footprints[ground.id], els, ground.id)
    frames = building_frames(levels, ground, infos, footprints, els, EXT_T / 2)
    assets, dropped = derive_bricks(design, frames, prune)
    els.extend(assets)
    pruned.extend(dropped)
    _mep(design, levels, infos, els)

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
    return Derived(spec, notes + pruned, infos, footprints, design if prune else None, pruned, sides,
                   ROUGH_IN if design.rooms else ())


def derive(design: Design) -> tuple[BuildingSpec, list[str]]:
    d = analyze(design)
    return d.spec, d.notes
