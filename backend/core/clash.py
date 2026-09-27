"""Hard clashes between placed pieces, and keep-out volumes around them.

Every placed brick (Asset) is tested against the other bricks, catalogue fixtures, custom shapes and
stair flights on its storey: a clash is a plan overlap whose height ranges also overlap, so a ceiling
diffuser above a bed or a footing below a column is fine. Assets with `collides: false` (rugs, a
light over a table) and load-bearing-on-load-bearing contacts (a beam landing on a column) are
skipped. Pairs without a brick are left alone: catalogue furniture was placed without this check and
the existing designs rely on that. A brick's keep-out volumes (access space, door swing) warn when
something else stands in them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Polygon

from bricks.place import Pose, world_box
from core.issues import Issue
from schemas.bim import Asset, BuildingSpec, CustomFixture, Fixture, Stair
from schemas.design import Design

MIN_AREA = 0.01     # m² of plan overlap that counts
MIN_Z = 0.02        # m of height overlap that counts


@dataclass
class Solid:
    id: str
    level: str
    footprint: Polygon
    z0: float
    z1: float
    asset: Asset | None = None

    @property
    def label(self) -> str:
        return f"{self.asset.brick} '{self.id}'" if self.asset else f"'{self.id}'"


def _rect(cx: float, cy: float, w: float, d: float, deg: float) -> Polygon:
    """w × d rectangle centred at (cx, cy), turned `deg` degrees."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return Polygon([(cx + px * c - py * s, cy + px * s + py * c) for px, py in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))])


def pose_of(a: Asset) -> Pose:
    return Pose(a.level, (a.position[0], a.position[1], a.elevation), a.rotation, a.pitch)


def solid(el, heights: dict[str, float]) -> Solid | None:
    """The plan footprint and height range of a placed piece, or None for anything else."""
    if isinstance(el, Asset):
        outline, z0, z1 = world_box(el.bounds, pose_of(el))
        return Solid(el.id, el.level, outline, z0, z1, el)
    if isinstance(el, Fixture):
        return Solid(el.id, el.level, _rect(el.position[0], el.position[1], el.width, el.depth, el.rotation), 0.0, el.height)
    if isinstance(el, CustomFixture):
        x0 = min(p.x for p in el.parts)
        y0 = min(p.y for p in el.parts)
        x1 = max(p.x + p.w for p in el.parts)
        y1 = max(p.y + (p.w if p.shape == "round" else p.d) for p in el.parts)
        top = max(p.z + p.h for p in el.parts)
        return Solid(el.id, el.level, _rect(el.position[0], el.position[1], x1 - x0, y1 - y0, el.rotation), 0.0, top)
    if isinstance(el, Stair):
        rise = el.rise or heights.get(el.level, 3.0)
        run = el.run(rise)
        a = math.radians(el.direction)
        cx, cy = el.position[0] + math.cos(a) * run / 2, el.position[1] + math.sin(a) * run / 2
        return Solid(el.id, el.level, _rect(cx, cy, el.width, run, el.direction - 90), 0.0, rise)
    return None


def solids(spec: BuildingSpec) -> list[Solid]:
    heights = {l.id: l.height for l in spec.levels}
    return [s for s in (solid(el, heights) for el in spec.elements) if s is not None]


def _skip(a: Solid, b: Solid) -> bool:
    if a.asset is None and b.asset is None:
        return True
    if (a.asset and not a.asset.collides) or (b.asset and not b.asset.collides):
        return True
    return bool(a.asset and b.asset and a.asset.load_bearing and b.asset.load_bearing)


def new_brick_clashes(before: Design, after: Design, spec: BuildingSpec) -> list[Issue]:
    """Hard clashes of the bricks `after` adds or changes compared to `before` (`spec` derived from `after`)."""
    changed = {b.id for b in after.bricks if b not in before.bricks}
    return [i for i in clashes(spec, changed) if i.severity == "error"] if changed else []


def clashes(spec: BuildingSpec, only: set[str] | None = None) -> list[Issue]:
    """Clash and keep-out issues; `only` limits them to pairs involving those element ids."""
    by_level: dict[str, list[Solid]] = {}
    for s in solids(spec):
        by_level.setdefault(s.level, []).append(s)
    issues: list[Issue] = []
    for level, group in by_level.items():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if only is not None and a.id not in only and b.id not in only:
                    continue
                if _skip(a, b) or min(a.z1, b.z1) - max(a.z0, b.z0) < MIN_Z:
                    continue
                overlap = a.footprint.intersection(b.footprint).area
                if overlap >= MIN_AREA:
                    issues.append(Issue("clash", "error", f"{a.label} and {b.label} overlap by {overlap:.2f} m² on {level}; "
                                                          f"move one (another side, `near`, or `position`) or make it smaller",
                                        [a.id, b.id]))
        for a in group:
            if a.asset is None or not a.asset.keepout or (only is not None and a.id not in only):
                continue
            for zone in a.asset.keepout:
                outline, z0, z1 = world_box(zone, pose_of(a.asset))
                for b in group:
                    if b is a or (b.asset and not b.asset.collides) or min(z1, b.z1) - max(z0, b.z0) < MIN_Z:
                        continue
                    if outline.intersection(b.footprint).area >= MIN_AREA:
                        issues.append(Issue("clearance", "warning", f"{b.label} stands in the keep-out space of {a.label}", [a.id, b.id]))
    return issues
