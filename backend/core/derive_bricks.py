"""Placed library bricks (Design.bricks) → Asset elements.

Where a brick goes follows its host (bricks/model.py::HOSTS): on the floor of a room, fixed to one of
its walls, under its ceiling, on the top roof, free-standing, spanning two points, or outside on the
site clear of the building. Its evaluated parts are re-centred on the footprint, like catalogue
fixtures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import assert_never

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from bricks import Brick, given_fields, library
from core.rooms import DesignError, RoomInfo, fits, place_piece, r2, rect_at
from schemas.bim import Asset, Level, ShapePart
from schemas.design import BrickDef, Design, Pt, RoofDef, RoomDef

SLAB_T = 0.2           # slab of the storey above, hanging below its level line
ROOF_T = 0.25          # flat roof thickness
MAX_PARTS = 24
WET_PORTS = ("water_cold", "water_hot", "drain")


@dataclass
class Site:
    """What brick placement needs to know about the building beyond one room."""

    levels: dict[str, Level]
    footprints: dict[str, list[Polygon]]
    ground: Level
    top: Level
    roof: RoofDef


@dataclass
class _Placed:
    position: Pt
    rotation: float             # degrees
    width: float                # footprint along the brick's x (the length, for spans)
    depth: float


def needs_water(brick_id: str) -> bool:
    brick = library().get(brick_id)
    return brick is not None and any(k in brick.needs for k in WET_PORTS)


def derive_brick(b: BrickDef, design: Design, infos: dict[str, RoomInfo], site: Site) -> Asset:
    what = f"brick '{b.id}' ({b.brick})"
    brick = library().get(b.brick)
    if brick is None:
        raise DesignError(f"{what}: not in the brick library")
    problem = brick.placement_error(given_fields(b))
    if problem:
        raise DesignError(f"{what}: {problem}")
    room = design.room(b.room) if b.room else None
    if b.room and room is None:
        raise DesignError(f"{what}: unknown room '{b.room}'")
    level = site.levels.get(room.level if room else (b.level or site.ground.id))
    if level is None:
        raise DesignError(f"{what}: unknown level '{b.level}'")
    if brick.host == "roof":
        level = site.top
    try:
        values = brick.resolve(b.params)
    except ValueError as exc:
        raise DesignError(f"{what}: {exc}") from exc
    values["level_h"] = level.height
    if brick.full_height and "h" not in b.params:
        values["h"] = level.height
    w, h = values["w"], values["h"]
    placed = _place(what, b, brick, room, infos, site, level, w, values.get("d", w))
    if brick.spans:
        values["length"] = placed.width
    elevation, note = _elevation(what, brick, values, level, site, h)
    try:
        solids = brick.solids(values)
    except ValueError as exc:
        raise DesignError(f"{what}: {exc}") from exc
    cx, cy = placed.width / 2, placed.depth / 2
    parts = [ShapePart(shape=s, x=r2(x - cx), y=r2(y - cy), z=r2(z), w=r2(pw), d=r2(pd), h=r2(ph)) for s, x, y, z, pw, pd, ph in solids]
    if len(parts) > MAX_PARTS:
        raise DesignError(f"{what}: evaluates to {len(parts)} parts; at most {MAX_PARTS}")
    return Asset(id=b.id, name=brick.name + (f" in {room.name}" if room else ""), level=level.id, brick=brick.id,
                 ifc_class=brick.ifc_class, predefined_type=brick.predefined_type, discipline=brick.discipline,
                 phase=brick.phase, finish=brick.finish, host=brick.host, room=room.id if room else None,
                 position=(r2(placed.position[0]), r2(placed.position[1])), rotation=r2(placed.rotation % 360),
                 elevation=r2(elevation), size=(r2(placed.width), r2(placed.depth), r2(h)), parts=parts,
                 params={k: v for k, v in values.items() if k != "level_h"}, ports=brick.ports,
                 structural=brick.structural, overlap_ok=brick.rules.overlap_ok, clearance=brick.rules.clearance, note=note)


def _place(what: str, b: BrickDef, brick: Brick, room: RoomDef | None, infos: dict[str, RoomInfo], site: Site, level: Level,
           w: float, d: float) -> _Placed:
    """Footprint centre, rotation and size; `placement_error` has already checked the fields each host needs."""
    match brick.host:
        case "floor" | "ceiling":
            return _in_room(what, b, room, infos[room.id], w, d)
        case "wall":
            info = infos[room.id]
            if not info.walls:
                raise DesignError(f"{what}: room '{room.id}' has no walls to fix it to")
            near = b.near
            if near is None and b.side == "center":
                straight = [s for s in info.walls if s.straight] or info.walls
                near = max(straight, key=lambda s: s.length).mid
            pos, rot = place_piece(what, room, info, b.side, near, b.at, w, d)
            return _Placed(pos, b.rotation if b.rotation is not None else rot, w, d)
        case "roof":
            return _on_roof(what, b, site, w, d)
        case "free":
            if b.position is None:
                return _in_room(what, b, room, infos[room.id], w, d)
            rot = b.rotation or 0.0
            if room is not None and not fits(infos[room.id].polygon, rect_at(b.position[0], b.position[1], w, d, math.radians(rot))):
                raise DesignError(f"{what}: at {list(b.position)} it is not inside room '{room.id}'")
            return _Placed(b.position, rot, w, d)
        case "site":
            rot = b.rotation or 0.0
            _clear_of_building(what, Polygon(rect_at(b.position[0], b.position[1], w, d, math.radians(rot))), site, level,
                               f"stands outside, but at {list(b.position)} it overlaps")
            return _Placed(b.position, rot, w, d)
        case "span":
            return _span(what, b, w)
        case "site_span":
            placed = _span(what, b, w)
            _clear_of_building(what, LineString([b.start, b.end]).buffer(w / 2), site, level,
                               f"runs outside, but from {list(b.start)} to {list(b.end)} it crosses")
            return placed
        case _:
            assert_never(brick.host)


def _span(what: str, b: BrickDef, w: float) -> _Placed:
    (x0, y0), (x1, y1) = b.start, b.end
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 0.2:
        raise DesignError(f"{what}: start and end are {length:.2f} m apart; a span needs two distinct points")
    return _Placed(((x0 + x1) / 2, (y0 + y1) / 2), math.degrees(math.atan2(y1 - y0, x1 - x0)), length, w)


def _in_room(what: str, b: BrickDef, room: RoomDef, info: RoomInfo, w: float, d: float) -> _Placed:
    if b.position is None:
        pos, rot = place_piece(what, room, info, b.side, b.near, b.at, w, d)
        return _Placed(pos, b.rotation if b.rotation is not None else rot, w, d)
    rot = b.rotation or 0.0
    if not fits(info.polygon, rect_at(b.position[0], b.position[1], w, d, math.radians(rot))):
        x0, y0, x1, y1 = room.box
        raise DesignError(f"{what}: a {w:.2f} x {d:.2f} m footprint at {list(b.position)} is not inside room '{room.id}' "
                          f"(x {x0:g}..{x1:g}, y {y0:g}..{y1:g})")
    return _Placed(b.position, rot, w, d)


def _on_roof(what: str, b: BrickDef, site: Site, w: float, d: float) -> _Placed:
    polys = site.footprints.get(site.top.id) or []
    if not polys:
        raise DesignError(f"{what}: there is no roof yet; add rooms first")
    top = unary_union(polys)
    rot = b.rotation or 0.0
    if b.position is None:
        c = top.centroid if top.contains(top.centroid) else top.representative_point()
        pos = (c.x, c.y)
    else:
        pos = b.position
    if not fits(top, rect_at(pos[0], pos[1], w, d, math.radians(rot))):
        x0, y0, x1, y1 = top.bounds
        raise DesignError(f"{what}: a {w:.1f} x {d:.1f} m footprint at [{pos[0]:.1f}, {pos[1]:.1f}] is off the roof of {site.top.id} "
                          f"(x {x0:.1f}..{x1:.1f}, y {y0:.1f}..{y1:.1f}); use a smaller size or another position")
    return _Placed(pos, rot, w, d)


def _clear_of_building(what: str, shape, site: Site, level: Level, where: str) -> None:
    building = unary_union(site.footprints.get(level.id) or [])
    if not building.is_empty and shape.intersects(building.buffer(-0.05)):
        x0, y0, x1, y1 = building.bounds
        raise DesignError(f"{what}: {where} the building on {level.id} "
                          f"(footprint x {x0:.1f}..{x1:.1f}, y {y0:.1f}..{y1:.1f}); move it clear of the rooms")


def _elevation(what: str, brick: Brick, values: dict[str, float], level: Level, site: Site, h: float) -> tuple[float, str | None]:
    """Height of the brick's base above its level, and a note when it had to be approximated."""
    ceiling = level.height - SLAB_T
    match brick.host:
        case "roof":
            if site.roof.kind == "flat":
                return level.height + ROOF_T, None
            x0, y0, x1, y1 = unary_union(site.footprints[level.id]).bounds
            rise = math.tan(math.radians(site.roof.pitch)) * min(x1 - x0, y1 - y0) / 2
            return level.height + 0.2 + rise / 2, f"on a {site.roof.kind} roof: set at mid-slope"
        case "floor" | "wall" | "ceiling" | "free" | "span" | "site" | "site_span":
            mount = None if brick.host == "ceiling" else brick.mount_height(values)
            if mount is None:
                if ceiling - h < 0:
                    raise DesignError(f"{what}: {h:g} m tall does not fit under a {level.height:g} m ceiling")
                return ceiling - h, None
            if brick.host in ("floor", "wall") and mount + h > ceiling + 0.01 and not brick.full_height:
                raise DesignError(f"{what}: top at {mount + h:.2f} m is above the {ceiling:.2f} m ceiling of {level.id}")
            return mount, None
        case _:
            assert_never(brick.host)
