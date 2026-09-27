"""Hard clashes between placed pieces, and clearance zones in front of them.

Every placed brick (Asset) is tested against the other bricks, catalogue fixtures, custom shapes and
stair flights on its storey: a clash is a footprint overlap whose height ranges also overlap, so a
ceiling diffuser above a bed or a footing below a column is fine. Bricks marked `overlap_ok` (rugs,
wall-mounted items over a counter) and structural-on-structural contacts (a beam landing on a column)
are skipped. Pairs without a brick are left alone: catalogue furniture was placed without this check
and the existing designs rely on that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Polygon

from core.issues import Issue
from schemas.bim import Asset, BuildingSpec, CustomFixture, Fixture, Stair

MIN_AREA = 0.01     # m² of footprint overlap that counts
MIN_Z = 0.02        # m of height overlap that counts
FLOOR_BAND = 1.0    # clearance zones only care about pieces that start below this height


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


def _rect(cx: float, cy: float, w: float, d: float, deg: float, dy: float = 0.0) -> Polygon:
    """w × d rectangle centred at (cx, cy) + dy along its own depth axis, turned `deg` degrees."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    pts = []
    for px, py in ((-w / 2, -d / 2 + dy), (w / 2, -d / 2 + dy), (w / 2, d / 2 + dy), (-w / 2, d / 2 + dy)):
        pts.append((cx + px * c - py * s, cy + px * s + py * c))
    return Polygon(pts)


def solids(spec: BuildingSpec) -> list[Solid]:
    heights = {l.id: l.height for l in spec.levels}
    out: list[Solid] = []
    for el in spec.elements:
        if isinstance(el, Asset):
            w, d, h = el.size
            out.append(Solid(el.id, el.level, _rect(el.position[0], el.position[1], w, d, el.rotation), el.elevation, el.elevation + h, el))
        elif isinstance(el, Fixture):
            out.append(Solid(el.id, el.level, _rect(el.position[0], el.position[1], el.width, el.depth, el.rotation), 0.0, el.height))
        elif isinstance(el, CustomFixture):
            x0 = min(p.x for p in el.parts)
            y0 = min(p.y for p in el.parts)
            x1 = max(p.x + p.w for p in el.parts)
            y1 = max(p.y + (p.w if p.shape == "round" else p.d) for p in el.parts)
            top = max(p.z + p.h for p in el.parts)
            box = _rect(el.position[0], el.position[1], x1 - x0, y1 - y0, el.rotation)  # derive centres the parts
            out.append(Solid(el.id, el.level, box, 0.0, top))
        elif isinstance(el, Stair):
            rise = el.rise or heights.get(el.level, 3.0)
            run = el.run(rise)
            a = math.radians(el.direction)
            cx, cy = el.position[0] + math.cos(a) * run / 2, el.position[1] + math.sin(a) * run / 2
            out.append(Solid(el.id, el.level, _rect(cx, cy, el.width, run, el.direction - 90), 0.0, rise))
    return out


def _skip(a: Solid, b: Solid) -> bool:
    if a.asset is None and b.asset is None:
        return True
    if (a.asset and a.asset.overlap_ok) or (b.asset and b.asset.overlap_ok):
        return True
    return bool(a.asset and b.asset and a.asset.structural and b.asset.structural)


def clashes(spec: BuildingSpec, only: set[str] | None = None) -> list[Issue]:
    """Clash and clearance issues; `only` limits them to pairs involving those element ids."""
    items = solids(spec)
    by_level: dict[str, list[Solid]] = {}
    for s in items:
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
            if a.asset is None or not a.asset.clearance or a.z0 > FLOOR_BAND:
                continue
            if only is not None and a.id not in only:
                continue
            w, d, _ = a.asset.size
            zone = _rect(a.asset.position[0], a.asset.position[1], w, a.asset.clearance, a.asset.rotation, d / 2 + a.asset.clearance / 2)
            for b in group:
                if b is a or b.z0 > FLOOR_BAND or (b.asset and b.asset.overlap_ok):
                    continue
                if zone.intersection(b.footprint).area >= MIN_AREA:
                    issues.append(Issue("clearance", "warning", f"{b.label} stands in the {a.asset.clearance:g} m clear zone in front of {a.label}",
                                        [a.id, b.id]))
    return issues
