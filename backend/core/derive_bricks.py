"""Placed bricks (Design.bricks) → Asset elements, through the generic placement kernel (bricks/place.py).

This is where the building meets the kernel. What derivation has produced so far becomes frames:
each room is a void from its floor to its ceiling with its derived walls as sides; each wall, slab,
roof, column, beam, fixture and stair is a solid; "site" is the ground around the building, with the
building's outer faces as its sides; each level id is a bare datum. The design's bricks are then placed
in dependency order, and each placed brick becomes a solid frame too, so bricks can stand on, hang
from or fix to one another.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from bricks import Brick
from bricks.place import Frame, Frames, PlacementError, Side, outline_sides, place, solid_frame
from core.clash import solid
from core.rooms import CLEAR, DesignError, RoomInfo
from schemas.bim import Asset, Beam, Column, Level, Roof, Slab, Wall
from schemas.design import BrickDef, Design

SLAB_T = 0.2           # slab of the storey above, hanging below its level line
ROOF_T = 0.25          # flat roof thickness
SITE_SIZE = 1000.0     # plan extent of the "site" frame around the building
SITE_HEIGHT = 50.0
WET = ("water_cold", "water_hot", "drain")


def needs_water(design: Design, brick_id: str) -> bool:
    brick = design.find_brick(brick_id)
    return brick is not None and any(k in brick.needs for k in WET)


def building_frames(levels: list[Level], ground: Level, infos: dict[str, RoomInfo], footprints: dict[str, list[Polygon]],
                    els: list, wall_face: float) -> Frames:
    """Frames for everything derived so far; `wall_face` is how far exterior wall faces sit outside the outline."""
    heights = {l.id: l.height for l in levels}
    frames = Frames(heights, ground.id)
    for info in infos.values():
        room = info.room
        sides = [Side(w.line, _flip(w.inward(info.polygon)), w.id) for w in info.walls]
        frames.add(Frame(room.id, room.level, 0.0, heights[room.level] - SLAB_T, info.polygon, True, sides, CLEAR))
    frames.add(_site(ground, footprints.get(ground.id) or [], wall_face))
    for el in els:
        frame = element_frame(el, heights)
        if frame is not None:
            frames.add(frame)
    return frames


def _flip(v: tuple[float, float]) -> tuple[float, float]:
    return (-v[0], -v[1])


def _site(ground: Level, polys: list[Polygon], wall_face: float) -> Frame:
    hint = "outside the building"
    if not polys:
        return Frame("site", ground.id, 0.0, SITE_HEIGHT, None, True, hint=hint)
    building = unary_union(polys)
    c = building.centroid
    area = box(c.x - SITE_SIZE / 2, c.y - SITE_SIZE / 2, c.x + SITE_SIZE / 2, c.y + SITE_SIZE / 2).difference(building.buffer(-0.05))
    sides = [Side(s.line, _flip(s.outward), face=s.compass) for p in polys for s in outline_sides(p)]
    return Frame("site", ground.id, 0.0, SITE_HEIGHT, area, True, sides, wall_face, hint)


def element_frame(el, heights: dict[str, float]) -> Frame | None:
    """A solid frame for a derived element that has a body; None for everything else."""
    if isinstance(el, Wall):
        outline = LineString(el.axis).buffer(el.thickness / 2, cap_style="flat", join_style="mitre")
        return solid_frame(el.id, el.level, outline, 0.0, el.height or heights[el.level])
    if isinstance(el, Slab):
        return solid_frame(el.id, el.level, Polygon(el.outline), -el.thickness, 0.0)
    if isinstance(el, Roof):
        return _roof(el, heights[el.level])
    if isinstance(el, Column):
        x, y = el.position
        outline = box(x - el.width / 2, y - el.depth / 2, x + el.width / 2, y + el.depth / 2)
        return solid_frame(el.id, el.level, outline, 0.0, el.height or heights[el.level])
    if isinstance(el, Beam):
        h = heights[el.level]
        return solid_frame(el.id, el.level, LineString([el.start, el.end]).buffer(el.width / 2, cap_style="flat"), h - el.depth, h)
    s = solid(el, heights)
    if s is None or not isinstance(s.footprint, Polygon):
        return None
    return solid_frame(s.id, s.level, s.footprint, s.z0, s.z1)


def _roof(el: Roof, level_h: float) -> Frame:
    outline = Polygon(el.outline)
    if el.shape == "flat":
        return solid_frame(el.id, el.level, outline, level_h, level_h + el.thickness)
    x0, y0, x1, y1 = outline.bounds
    rise = math.tan(math.radians(el.pitch)) * min(x1 - x0, y1 - y0) / 2
    return solid_frame(el.id, el.level, outline, level_h, level_h + el.thickness + rise / 2,
                       note=f"on a {el.shape} roof: set at mid-slope")


def derive_bricks(design: Design, frames: Frames, prune: bool) -> tuple[list[Asset], list[str]]:
    """Every placed brick as an Asset, in design order. A brick whose `ref` is another brick is placed
    after it. With `prune`, bricks that no longer fit (or stood on one that went) are dropped from
    `design.bricks` with a note instead of failing."""
    ids = {b.id for b in design.bricks}
    pending = list(design.bricks)
    done: dict[str, Asset] = {}
    pruned: list[str] = []
    while pending:
        ready = [b for b in pending if b.ref not in ids or b.ref in done or b.ref not in {p.id for p in pending}]
        if not ready:
            raise DesignError(f"bricks {', '.join(sorted(b.id for b in pending))} are placed on each other in a loop; "
                              f"give one of them a room, level or other ref")
        for b in ready:
            pending.remove(b)
            try:
                if b.ref in ids and b.ref not in done:
                    raise DesignError(f"brick '{b.id}': it was placed on brick '{b.ref}', which was removed")
                asset = derive_brick(b, design, frames)
            except DesignError as exc:
                if not prune:
                    raise
                pruned.append(f"removed brick {b.id}: {exc}")
                continue
            done[b.id] = asset
            frames.add(element_frame(asset, frames.levels))
    design.bricks = [b for b in design.bricks if b.id in done]
    return [done[b.id] for b in design.bricks], pruned


def derive_brick(b: BrickDef, design: Design, frames: Frames) -> Asset:
    what = f"brick '{b.id}' ({b.brick})"
    brick = design.find_brick(b.brick)
    if brick is None:
        raise DesignError(f"{what}: neither in the library nor among the design's own assets")
    room = design.room(b.ref) if b.ref and b.ref not in frames.by_id else None
    p = b.model_copy(update={"ref": room.id}) if room else b
    try:
        placed = place(brick, b.params, p, frames, what)
    except PlacementError as exc:
        raise DesignError(str(exc)) from exc
    room = design.room(p.ref) if p.ref else None
    x, y, z = placed.pose.position
    return Asset(id=b.id, name=brick.name + (f" in {room.name}" if room and room.id == p.ref else ""), level=placed.pose.level,
                 brick=brick.id, ifc_class=brick.ifc_class, predefined_type=brick.predefined_type, tags=brick.tags, ref=p.ref,
                 position=(round(x, 4), round(y, 4)), elevation=round(z, 4), rotation=round(placed.pose.yaw % 360, 3),
                 pitch=round(placed.pose.pitch, 3), bounds=placed.bounds, solids=placed.solids, materials=brick.materials,
                 params=_own(brick, placed.values), connectors=brick.connectors, properties=brick.properties,
                 keepout=placed.keepout, collides=brick.collides, path=placed.path, note=placed.note)


def _own(brick: Brick, values: dict[str, float]) -> dict[str, float]:
    return {p.name: values[p.name] for p in brick.params}
