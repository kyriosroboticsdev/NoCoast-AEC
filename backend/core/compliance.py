"""Placement warnings the model can act on: a blocked door, two pieces in the same space,
or an element that is not actually hosted where its mount says it should be.

Hard clashes, missing services and structure stay in their own checks. These are warnings,
and they name the element, what is wrong, and why it matters — not the raw geometry.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point as ShpPoint, Polygon

from core.clash import MIN_AREA, MIN_Z, Solid, pose_of, solid, solids, world_box
from core.issues import Issue
from schemas.bim import Asset, BuildingSpec, CustomFixture, Door, Fixture, Wall, Window
from schemas.design import Design

# A fix-mounted piece whose centre is farther than this past its own depth is not on a wall.
_HOST_EXTRA = 0.4
# Share of a footprint inside a wall that counts as buried rather than seated against the face.
_BURIED = 0.3
# Door swing / approach, in metres. Swinging leaves use the leaf width; others use a standing clearance.
_APPROACH = 0.6
_SWING = ("single", "double", "french")


def compliance(design: Design, spec: BuildingSpec) -> list[Issue]:
    issues = _doors(spec) + _intersections(spec) + _insertion(design, spec)
    issues.sort(key=lambda i: (i.kind, i.message))
    return issues


def _doors(spec: BuildingSpec) -> list[Issue]:
    walls = {el.id: el for el in spec.elements if isinstance(el, Wall)}
    labels = {el.id: _label(el) for el in spec.elements}
    by_level: dict[str, list[Solid]] = {}
    for s in solids(spec):
        by_level.setdefault(s.level, []).append(s)
    issues: list[Issue] = []
    for door in spec.elements:
        if not isinstance(door, Door):
            continue
        wall = walls.get(door.wall)
        if wall is None:
            continue
        group = by_level.get(wall.level, [])
        opening, swing, approach = _door_zones(door, wall)
        for s in group:
            if min(door.height, s.z1) - max(0.0, s.z0) < MIN_Z:
                continue
            if opening.intersection(s.footprint).area >= MIN_AREA:
                how, why = "obstructs the opening", "nothing can pass through the door"
            elif swing is not None and swing.intersection(s.footprint).area >= MIN_AREA:
                how, why = "stands in the door swing", "the leaf cannot open"
            elif approach.intersection(s.footprint).area >= MIN_AREA:
                how, why = "stands in the clearance in front of the door", "the approach is blocked"
            else:
                continue
            issues.append(Issue(
                "clearance", "warning",
                f"door '{door.id}' is blocked: {labels.get(s.id, s.label)} {how} on {wall.level}; {why}. Move {s.id} off the door",
                [door.id, s.id]))
    return issues


def _door_zones(door: Door, wall: Wall) -> tuple[Polygon, Polygon | None, Polygon]:
    a, _ = wall.frame_at(door.offset)
    b, _ = wall.frame_at(min(door.offset + door.width, wall.length))
    depth = door.width if door.kind in _SWING else _APPROACH
    opening = _extrude(a, b, wall.thickness / 2 + 0.02)
    approach = _extrude(a, b, _APPROACH)
    swing = _extrude(a, b, depth) if door.kind in _SWING else None
    return opening, swing, approach


def _extrude(a: tuple[float, float], b: tuple[float, float], depth: float) -> Polygon:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    ring = [
        (a[0] - nx * depth, a[1] - ny * depth), (b[0] - nx * depth, b[1] - ny * depth),
        (b[0] + nx * depth, b[1] + ny * depth), (a[0] + nx * depth, a[1] + ny * depth),
    ]
    return Polygon(ring)


def _intersections(spec: BuildingSpec) -> list[Issue]:
    """Overlaps the hard clash check ignores: two fixtures, a fixture and a stair, and so on."""
    by_level: dict[str, list[tuple[Solid, object]]] = {}
    heights = {lvl.id: lvl.height for lvl in spec.levels}
    for el in spec.elements:
        s = solid(el, heights)
        if s is None:
            continue
        by_level.setdefault(s.level, []).append((s, el))
    issues: list[Issue] = []
    for level, group in by_level.items():
        for i, (a, ea) in enumerate(group):
            for b, eb in group[i + 1:]:
                if a.asset is not None or b.asset is not None:
                    continue  # a brick pair is already an error in core/clash.py when it should be
                z0a, z1a = _zspan(ea, a)
                z0b, z1b = _zspan(eb, b)
                if min(z1a, z1b) - max(z0a, z0b) < MIN_Z:
                    continue
                overlap = a.footprint.intersection(b.footprint).area
                if overlap < MIN_AREA:
                    continue
                issues.append(Issue(
                    "intersection", "warning",
                    f"{_label(ea)} and {_label(eb)} intersect by {overlap:.2f} m² on {level}; they occupy the same "
                    f"space and should not. Move one (another side, `near`, or `position`)",
                    [a.id, b.id]))
    return issues


def _zspan(el, s: Solid) -> tuple[float, float]:
    if isinstance(el, Fixture):
        return el.elevation, el.elevation + el.height
    return s.z0, s.z1


def _insertion(design: Design, spec: BuildingSpec) -> list[Issue]:
    walls = [el for el in spec.elements if isinstance(el, Wall)]
    wall_polys = {w.id: (w, LineString(w.axis).buffer(w.thickness / 2, cap_style="flat", join_style="mitre")) for w in walls}
    levels = {lvl.id: lvl.height for lvl in spec.levels}
    issues: list[Issue] = []
    for el in spec.elements:
        if isinstance(el, Asset):
            issue = _asset_host(design, el, walls, wall_polys, levels.get(el.level, 3.0))
        elif isinstance(el, (Fixture, CustomFixture)):
            issue = _piece_host(el, wall_polys, levels.get(el.level, 3.0))
        else:
            issue = None
        if issue is not None:
            issues.append(issue)
    return issues


def _asset_host(design: Design, asset: Asset, walls: list[Wall], wall_polys: dict, level_h: float) -> Issue | None:
    brick = design.find_brick(asset.brick)
    mount = brick.mount if brick else "rest"
    label = f"{asset.brick} '{asset.id}'"
    footprint, z0, z1 = _asset_box(asset)
    level_walls = [w for w in walls if w.level == asset.level]
    level_polys = {wid: pair for wid, pair in wall_polys.items() if pair[0].level == asset.level}
    if mount == "fix":
        return _fixed(label, asset.id, asset.rotation, footprint, level_walls, level_polys, asset.bounds)
    if mount == "hang" and z1 < level_h - 0.35:
        return Issue(
            "insertion", "warning",
            f"{label} is not hosted on a ceiling or slab: its top is {level_h - z1:.2f} m below the ceiling on "
            f"{asset.level}, so it is floating. Hang it from the ceiling (leave the height unset) or set it on a soffit",
            [asset.id])
    if mount == "rest" and 0.15 < z0 < level_h - 0.35:
        return Issue(
            "insertion", "warning",
            f"{label} is floating {z0:.2f} m above the floor on {asset.level}, not hosted on a slab or the roof. "
            f"Lower it onto the surface it should stand on",
            [asset.id])
    buried = _buried(footprint, level_polys)
    if buried is not None:
        wall, ratio = buried
        return Issue(
            "insertion", "warning",
            f"{label} is partially inserted into wall '{wall.id}': {ratio:.0%} of it is inside the wall on "
            f"{asset.level}. Seat it against the face instead of burying it",
            [asset.id, wall.id])
    return None


def _fixed(label: str, eid: str, rotation: float, footprint: Polygon, walls: list[Wall], wall_polys: dict,
           bounds) -> Issue | None:
    if not walls or footprint.is_empty:
        return None
    center = footprint.centroid
    wall, dist, nearest = _nearest(center, walls)
    half = max(0.05, (bounds[4] - bounds[1]) / 2)
    if wall is None or dist > half + _HOST_EXTRA:
        where = f"{dist:.2f} m from the nearest wall" if wall is not None else "in a room with no walls"
        return Issue(
            "insertion", "warning",
            f"{label} is not hosted in a wall: it is mount fix but {where}, so it is floating. "
            f"Place it with `side` or `near` so its back meets a wall",
            [eid])
    toward = _unit((nearest[0] - center.x, nearest[1] - center.y))
    back = _back(rotation)
    if toward is not None and _dot(back, toward) < 0.5:
        return Issue(
            "insertion", "warning",
            f"{label} has the wrong orientation on wall '{wall.id}': its back faces away from the wall, "
            f"so it is turned relative to its host. Face the back into the wall (leave `rotation` unset)",
            [eid, wall.id])
    buried = _buried(footprint, wall_polys)
    if buried is not None:
        host, ratio = buried
        return Issue(
            "insertion", "warning",
            f"{label} is partially inserted into wall '{host.id}': {ratio:.0%} of it is inside the wall. "
            f"Seat the back against the face instead of burying it",
            [eid, host.id])
    return None


def _piece_host(el: Fixture | CustomFixture, wall_polys: dict, level_h: float) -> Issue | None:
    label = _label(el)
    if 0.15 < el.elevation < level_h - 0.35:
        return Issue(
            "insertion", "warning",
            f"{label} is floating {el.elevation:.2f} m above the floor on {el.level}, not hosted on a slab or the roof. "
            f"Lower it onto the surface it should stand on",
            [el.id])
    s = solid(el, {el.level: level_h})
    if s is None:
        return None
    buried = _buried(s.footprint, {wid: pair for wid, pair in wall_polys.items() if pair[0].level == el.level})
    if buried is not None:
        wall, ratio = buried
        return Issue(
            "insertion", "warning",
            f"{label} is partially inserted into wall '{wall.id}': {ratio:.0%} of it is inside the wall on "
            f"{el.level}. Move it clear so it sits against the face",
            [el.id, wall.id])
    return None


def _buried(footprint: Polygon, wall_polys: dict) -> tuple[Wall, float] | None:
    area = footprint.area
    if area < 1e-4:
        return None
    worst: tuple[Wall, float] | None = None
    for wall, poly in wall_polys.values():
        ratio = poly.intersection(footprint).area / area
        if ratio >= _BURIED and (worst is None or ratio > worst[1]):
            worst = (wall, ratio)
    return worst


def _asset_box(asset: Asset) -> tuple[Polygon, float, float]:
    outline, z0, z1 = world_box(asset.bounds, pose_of(asset))
    return outline, z0, z1


def _nearest(point, walls: list[Wall]) -> tuple[Wall | None, float, tuple[float, float]]:
    best: tuple[Wall, float, tuple[float, float]] | None = None
    pt = ShpPoint(point.x, point.y)
    for wall in walls:
        line = LineString(wall.axis)
        dist = line.distance(pt)
        nearest = line.interpolate(line.project(pt))
        hit = (wall, dist, (nearest.x, nearest.y))
        if best is None or dist < best[1] - 1e-6 or (abs(dist - best[1]) <= 1e-6 and wall.id < best[0].id):
            best = hit
    if best is None:
        return None, float("inf"), (0.0, 0.0)
    return best


def _label(el) -> str:
    if isinstance(el, Asset):
        return f"{el.brick} '{el.id}'"
    if getattr(el, "name", None):
        return f"{el.name} '{el.id}'"
    return f"{el.type} '{el.id}'"


def _back(yaw_deg: float) -> tuple[float, float]:
    """World direction of a brick's back (local -y) at yaw `yaw_deg`."""
    yaw = math.radians(yaw_deg)
    return (math.sin(yaw), -math.cos(yaw))


def _unit(v: tuple[float, float]) -> tuple[float, float] | None:
    n = math.hypot(v[0], v[1])
    if n < 1e-6:
        return None
    return (v[0] / n, v[1] / n)


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]
