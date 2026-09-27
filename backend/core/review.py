"""Design review of a built version: the numbers an architect checks before a model leaves the office.

`review(spec, design)` reads the compiled `BuildingSpec` (plus the semantic `Design`, when there is one,
for room kinds) and returns plain JSON:

- `rooms` / `levels`: an area schedule — every room numbered the way a US drawing set numbers them
  (101, 102 … on the first floor, 201 … on the second), with net area, perimeter, clear height,
  glazing and window-to-floor ratio, occupant load, and GIA / NIA / efficiency per storey.
- `occupancy`: the IBC occupancy classification the rooms add up to, and the design occupant load.
- `checks`: an indicative code review against named clauses of the IBC 2021, IRC 2021 and the 2010
  ADA Standards — egress, travel distance, stairs, headroom, daylight, ventilation, emergency escape
  openings, accessibility and plumbing fixture counts. Every check names the clause, the measured
  value, the requirement and the elements involved, so it can be traced in the model or exported
  as a BCF issue.

It is a design-stage screen, not a permit review: it reads geometry the model actually contains and
states its assumptions (open stairs, no sprinklers, 50 % of glazing openable) where the model is
silent.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from shapely.geometry import Point, Polygon

from schemas.bim import Asset, BuildingSpec, Door, Fixture, Space, Stair, Wall, Window, polygon_area
from schemas.design import Design, guess_kind

DWELLING = {"living", "kitchen", "dining", "bedroom", "bathroom", "hall", "garage", "utility", "storage", "office"}
HABITABLE = {"living", "kitchen", "dining", "bedroom", "office", "classroom", "meeting", "ward", "clinic",
             "reception", "cafe", "lab", "retail", "gym", "auditorium", "workshop"}
OUTDOOR = {"courtyard", "terrace", "carport", "pergola"}
ACCESSORY = {"hall", "bathroom", "utility", "storage", "plant", "server"}

# IBC 2021 Table 1004.5: floor area per occupant (m², converted from ft²) and whether it is net or gross.
LOAD_FACTORS: dict[str, tuple[float, str]] = {
    "residential": (18.6, "gross"), "office": (13.9, "gross"), "reception": (13.9, "gross"),
    "meeting": (1.4, "net"), "classroom": (1.9, "net"), "lab": (4.6, "net"), "clinic": (9.3, "gross"),
    "ward": (22.3, "gross"), "retail": (5.6, "gross"), "cafe": (1.4, "net"), "gym": (4.6, "gross"),
    "auditorium": (0.65, "net"), "workshop": (9.3, "gross"), "warehouse": (27.9, "gross"),
    "storage": (27.9, "gross"), "plant": (27.9, "gross"), "server": (27.9, "gross"), "parking": (18.6, "gross"),
    "garage": (18.6, "gross"), "barn": (27.9, "gross"), "stable": (27.9, "gross"), "kitchen": (18.6, "gross"),
    "other": (13.9, "gross"),
}

# IBC chapter 3 occupancy groups by room kind (non-dwelling use).
GROUPS: dict[str, str] = {
    "office": "B", "reception": "B", "meeting": "B", "clinic": "B", "lab": "B", "server": "B",
    "classroom": "E", "ward": "I-2", "retail": "M", "cafe": "A-2", "gym": "A-3", "auditorium": "A-1",
    "workshop": "F-1", "warehouse": "S-1", "storage": "S-1", "plant": "S-1", "parking": "S-2",
    "barn": "U", "stable": "U", "garage": "U",
}
GROUP_NAMES = {
    "R-3": "Residential R-3 — one- and two-family dwelling", "B": "Business B", "E": "Educational E",
    "I-2": "Institutional I-2 — health care", "M": "Mercantile M", "A-1": "Assembly A-1 — fixed seating",
    "A-2": "Assembly A-2 — food and drink", "A-3": "Assembly A-3 — recreation", "F-1": "Factory F-1",
    "S-1": "Storage S-1", "S-2": "Storage S-2 — parking", "U": "Utility and miscellaneous U",
}
# IBC Table 2902.1: occupants per water closet (first tier).
WC_RATIO = {"B": 25, "E": 50, "I-2": 10, "M": 500, "A-1": 125, "A-2": 75, "A-3": 125, "F-1": 100,
            "S-1": 100, "S-2": 100, "U": 100}
# IBC Table 1017.2, unsprinklered, metres (sprinklered values in brackets for the note).
TRAVEL_LIMIT = {"R-3": None, "B": (61.0, 91.4), "E": (61.0, 76.2), "I-2": (45.7, 61.0), "M": (61.0, 76.2),
                "A-1": (61.0, 76.2), "A-2": (61.0, 76.2), "A-3": (61.0, 76.2), "F-1": (61.0, 76.2),
                "S-1": (61.0, 76.2), "S-2": (61.0, 76.2), "U": (91.4, 122.0)}

SLAB = 0.2
MM = 1000
LEAF_MIN = 0.813             # IBC 1010.1.1 / IRC R311.2: 32 in clear per leaf
EXIT_PER_OCCUPANT = 0.00508  # IBC 1005.3.2: 0.2 in of exit width per occupant (unsprinklered)


def ft(m: float) -> str:
    return f"{m * 3.28084:,.0f} ft"


def sf(m2: float) -> str:
    return f"{m2 * 10.7639:,.0f} sf"


@dataclass
class RoomData:
    id: str
    number: str
    name: str
    kind: str
    level: str
    level_name: str
    polygon: Polygon
    height: float
    windows: list[Window] = field(default_factory=list)
    doors: list[Door] = field(default_factory=list)
    exits: list[Door] = field(default_factory=list)
    occupants: int = 0

    @property
    def area(self) -> float:
        return self.polygon.area

    @property
    def glazing(self) -> float:
        return sum(w.width * w.height for w in self.windows)

    @property
    def min_dim(self) -> float:
        x0, y0, x1, y1 = self.polygon.bounds
        return min(x1 - x0, y1 - y0)

    def json(self) -> dict:
        wfr = self.glazing / self.area if self.area else 0.0
        return {"id": self.id, "number": self.number, "name": self.name, "kind": self.kind, "level": self.level,
                "level_name": self.level_name, "area": round(self.area, 2), "perimeter": round(self.polygon.length, 2),
                "min_dimension": round(self.min_dim, 2), "clear_height": round(self.height, 2),
                "glazing": round(self.glazing, 2), "window_floor_ratio": round(wfr, 3),
                "windows": len(self.windows), "doors": len(self.doors), "occupants": self.occupants}


def _check(cid: str, category: str, title: str, reference: str, status: str, value: str, target: str,
           detail: str, elements: list[str] | None = None, advice: str = "") -> dict:
    return {"id": cid, "category": category, "title": title, "reference": reference, "status": status,
            "value": value, "target": target, "detail": detail, "elements": elements or [], "advice": advice}


LIFT = re.compile(r"elevator|(^|_)(platform_)?lift(_|$)")
TOILET = re.compile(r"(^|_)(wc|toilet|water_closet)(_|$)")


def lifts(spec: BuildingSpec) -> list[list[Asset]]:
    """Lift cars placed from the brick library, grouped by shaft (a lift is often placed once per storey)."""
    shafts: dict[tuple[float, float], list[Asset]] = {}
    for a in spec.elements:
        if isinstance(a, Asset) and LIFT.search(a.brick) and "stair_lift" not in a.brick:
            shafts.setdefault((round(a.position[0], 0), round(a.position[1], 0)), []).append(a)
    return list(shafts.values())


class Model:
    """The spec indexed for review: rooms with their openings, stairs, exits."""

    def __init__(self, spec: BuildingSpec, design: Design | None):
        self.spec = spec
        self.levels = {l.id: l for l in spec.levels}
        self.order = [l.id for l in spec.levels]
        self.walls = {e.id: e for e in spec.elements if isinstance(e, Wall)}
        self.doors = [e for e in spec.elements if isinstance(e, Door)]
        self.windows = [e for e in spec.elements if isinstance(e, Window)]
        self.stairs = [e for e in spec.elements if isinstance(e, Stair)]
        self.fixtures = [e for e in spec.elements if isinstance(e, Fixture)]
        self.assets = [e for e in spec.elements if isinstance(e, Asset)]
        kinds: dict[str, str] = {}
        if design is not None:
            for r in design.rooms:
                kinds[f"{r.level}-space-{r.id}"] = r.kind
        self.rooms: list[RoomData] = []
        counters: Counter[str] = Counter()
        slab_levels = {e.level for e in spec.elements if e.type == "slab"}
        for el in spec.elements:
            if not isinstance(el, Space) or len(el.outline) < 3:
                continue
            level = self.levels[el.level]
            idx = self.order.index(el.level)
            counters[el.level] += 1
            number = f"{idx + 1}{counters[el.level]:02d}"
            above = self.order[idx + 1] if idx + 1 < len(self.order) else None
            slab = SLAB if (above in slab_levels or above is not None) else 0.0
            kind = kinds.get(el.id) or guess_kind(el.name or el.id)
            self.rooms.append(RoomData(id=el.id, number=number, name=el.name or el.id, kind=kind, level=el.level,
                                       level_name=level.name, polygon=Polygon(el.outline).buffer(0),
                                       height=(el.height or level.height) - slab))
        self._attach()
        self.dwelling = bool(self.rooms) and all(r.kind in DWELLING | OUTDOOR for r in self.rooms) and \
            any(r.kind in ("bedroom", "living") for r in self.rooms)

    def _anchor(self, item: Door | Window) -> tuple[Wall, tuple[float, float]] | None:
        wall = self.walls.get(item.wall)
        if wall is None:
            return None
        pt, _ = wall.frame_at(item.offset + item.width / 2)
        return wall, pt

    def _attach(self) -> None:
        by_level: dict[str, list[RoomData]] = defaultdict(list)
        for r in self.rooms:
            by_level[r.level].append(r)
        for item in [*self.doors, *self.windows]:
            found = self._anchor(item)
            if found is None:
                continue
            wall, pt = found
            reach = wall.thickness / 2 + 0.2
            near = [r for r in by_level[wall.level] if r.polygon.distance(Point(pt)) <= reach]
            for r in near:
                (r.windows if isinstance(item, Window) else r.doors).append(item)
                if isinstance(item, Door) and (wall.external or len(near) == 1):
                    r.exits.append(item)

    def arrives(self, s: Stair) -> str | None:
        """The storey a flight climbs to: its egress route down from that storey."""
        if s.to_level:
            return s.to_level
        idx = self.order.index(s.level) if s.level in self.order else -1
        return self.order[idx + 1] if 0 <= idx < len(self.order) - 1 else None

    def down(self, level: str) -> list[Stair]:
        return [s for s in self.stairs if self.arrives(s) == level]

    def level_of(self, item: Door | Window) -> str | None:
        wall = self.walls.get(item.wall)
        return wall.level if wall else None

    def exterior_doors(self, level: str | None = None) -> list[Door]:
        out = []
        for d in self.doors:
            wall = self.walls.get(d.wall)
            if wall is not None and wall.external and (level is None or wall.level == level):
                out.append(d)
        return out

    def point(self, d: Door) -> tuple[float, float]:
        found = self._anchor(d)
        return found[1] if found else (0.0, 0.0)

    def gross(self, level: str) -> float:
        slabs = [e for e in self.spec.elements if e.type == "slab" and e.level == level]
        if slabs:
            return sum(polygon_area(s.outline) for s in slabs)
        rooms = [r.polygon.buffer(0.15, join_style="mitre") for r in self.rooms if r.level == level]
        if not rooms:
            return 0.0
        union = rooms[0]
        for p in rooms[1:]:
            union = union.union(p)
        return union.area


def opening_width(d: Door) -> float:
    """Clear width of the whole opening, for egress capacity: both leaves of a pair count."""
    if d.kind in ("double", "french"):
        return d.width - 0.1
    return _clear_width(d)


def _clear_width(d: Door) -> float:
    if d.kind in ("double", "french", "sliding"):
        return d.width / 2 - 0.05
    if d.kind in ("garage", "roller"):
        return d.width - 0.05
    if d.kind == "revolving":
        return 0.0
    return d.width - 0.09


def _occupancy(m: Model) -> tuple[str, dict[str, float]]:
    if m.dwelling:
        return "R-3", {"R-3": sum(r.area for r in m.rooms)}
    areas: Counter[str] = Counter()
    for r in m.rooms:
        g = GROUPS.get(r.kind)
        if g:
            areas[g] += r.area
    if not areas:
        return "B", {"B": sum(r.area for r in m.rooms)}
    return areas.most_common(1)[0][0], dict(areas)


def _load(m: Model, group: str) -> None:
    for r in m.rooms:
        if r.kind in OUTDOOR or (r.kind in ACCESSORY and r.kind not in ("storage", "plant", "server")):
            r.occupants = 0
            continue
        if group == "R-3":
            factor, _ = LOAD_FACTORS["residential"]
        else:
            factor, _ = LOAD_FACTORS.get(r.kind, LOAD_FACTORS["other"])
        r.occupants = max(1, math.ceil(r.area / factor)) if r.area > 1 else 0


def _exits_required(load: int) -> int:
    return 1 if load <= 49 else 2 if load <= 500 else 3 if load <= 1000 else 4


def _manhattan(a, b) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _travel(m: Model) -> list[tuple[RoomData, float]]:
    """Worst-case travel from each occupied room to an exterior exit door: rectilinear from the room's
    far corner, via the stair for upper storeys (stairs are open, so travel continues to the door)."""
    ground = m.order[0]
    exits = [m.point(d) for d in m.exterior_doors(ground)] or [m.point(d) for d in m.exterior_doors()]
    out: list[tuple[RoomData, float]] = []
    if not exits:
        return out
    for r in m.rooms:
        if r.kind in OUTDOOR:
            continue
        corners = list(r.polygon.exterior.coords)
        idx = m.order.index(r.level)
        if idx == 0:
            dist = max(min(_manhattan(c, e) for e in exits) for c in corners)
        else:
            flights = m.down(r.level)
            if not flights:
                continue
            best = math.inf
            for s in flights:
                run = s.run(m.levels[s.level].height)
                head = (s.position[0] + math.cos(math.radians(s.direction)) * run,
                        s.position[1] + math.sin(math.radians(s.direction)) * run)
                up = max(min(_manhattan(c, head), _manhattan(c, s.position)) for c in corners)
                down = min(_manhattan(s.position, e) for e in exits)
                best = min(best, up + math.hypot(run, m.levels[s.level].height) * idx + down)
            dist = best
        out.append((r, dist))
    return out


def _level_rows(m: Model) -> list[dict]:
    rows = []
    for lid in m.order:
        level = m.levels[lid]
        rooms = [r for r in m.rooms if r.level == lid]
        nia = sum(r.area for r in rooms if r.kind not in OUTDOOR)
        circ = sum(r.area for r in rooms if r.kind == "hall")
        gia = m.gross(lid) or nia
        rows.append({"id": lid, "name": level.name, "elevation": round(level.elevation or 0.0, 3),
                     "height": level.height, "gia": round(gia, 2), "nia": round(nia, 2),
                     "circulation": round(circ, 2), "efficiency": round(nia / gia, 3) if gia else 0.0,
                     "rooms": len(rooms), "occupants": sum(r.occupants for r in rooms)})
    return rows


def _checks(m: Model, group: str, load: int) -> list[dict]:
    checks: list[dict] = []
    residential = group == "R-3"
    code = "IRC 2021" if residential else "IBC 2021"
    ground = m.order[0]

    # --- egress -------------------------------------------------------------
    ext = m.exterior_doors(ground)
    per_level = defaultdict(int)
    for r in m.rooms:
        per_level[r.level] += r.occupants
    need = 1 if residential else _exits_required(per_level.get(ground, 0) + sum(
        v for k, v in per_level.items() if k != ground))
    checks.append(_check(
        "egress.exits", "Egress", "Exits from the building",
        "IRC R311.1" if residential else "IBC 1006.3.3", "pass" if len(ext) >= need else "fail",
        f"{len(ext)} exterior door{'s' if len(ext) != 1 else ''}", f"≥ {need}",
        (f"Design occupant load {load}; " if not residential else "") +
        f"{len(ext)} exterior exit door{'s' if len(ext) != 1 else ''} on {m.levels[ground].name}.",
        [d.id for d in ext] or [ground],
        "" if len(ext) >= need else f"Add {need - len(ext)} exterior exit door(s), remote from each other "
                                    f"(at least half the building diagonal apart, IBC 1007.1.1)."))
    if len(ext) >= 2 and not residential:
        pts = [m.point(d) for d in ext]
        spread = max(math.dist(a, b) for a in pts for b in pts)
        x0, y0, x1, y1 = _extent(m)
        diag = math.hypot(x1 - x0, y1 - y0)
        ok = spread >= diag / 2
        checks.append(_check("egress.remoteness", "Egress", "Exit separation", "IBC 1007.1.1",
                             "pass" if ok else "warn", f"{spread:.1f} m apart", f"≥ {diag / 2:.1f} m (½ diagonal)",
                             "Exit doors measured centre to centre against half the overall diagonal.",
                             [d.id for d in ext],
                             "" if ok else "Move one exit to the opposite end of the plan so one fire can't block both."))

    for lid in m.order[1:]:
        flights = m.down(lid)
        need = 1 if residential else (1 if per_level.get(lid, 0) <= 29 else 2)
        name = m.levels[lid].name
        checks.append(_check(
            f"egress.stairs.{lid}", "Egress", f"Means of egress from {name}",
            "IRC R311.7" if residential else "IBC 1006.3.4", "pass" if len(flights) >= need else "fail",
            f"{len(flights)} stair{'s' if len(flights) != 1 else ''}", f"≥ {need}",
            f"{per_level.get(lid, 0)} occupants on {name}." if not residential else f"{name} is served by "
            f"{len(flights)} stair{'s' if len(flights) != 1 else ''}.",
            [s.id for s in flights] or [lid],
            "" if len(flights) >= need else (
                "Add a stair: an upper storey with no stair has no way out." if not flights else
                "A second exit stair is needed above 29 occupants per storey (IBC Table 1006.3.4(1))."))
        )

    if ext:
        # IBC 1010.1.1: every leaf clears 32 in; IBC 1005.3.2: the exits together clear 0.2 in per occupant.
        worst = min(ext, key=_clear_width)
        leaf_ok = _clear_width(worst) >= LEAF_MIN - 1e-6
        capacity = sum(opening_width(d) for d in ext)
        need_cap = 0.0 if residential else load * EXIT_PER_OCCUPANT
        cap_ok = capacity >= need_cap - 1e-6
        advice = []
        if not leaf_ok:
            advice.append(f"widen {worst.id} to a leaf of at least {(LEAF_MIN + 0.09) * MM:.0f} mm")
        if not cap_ok:
            advice.append(f"find {(need_cap - capacity) * MM:,.0f} mm more exit width: make the exits pairs of "
                          f"1,800 mm leaves or add another exit")
        narrow = [d.id for d in ext if opening_width(d) < 1.7] if not cap_ok else []
        checks.append(_check(
            "egress.door-width", "Egress", "Exit door clear width", "IRC R311.2" if residential else "IBC 1005.3.2 / 1010.1.1",
            "pass" if leaf_ok and cap_ok else "fail",
            f"{_clear_width(worst) * MM:.0f} mm narrowest leaf" + ("" if residential else f", {capacity * MM:,.0f} mm in total"),
            f"≥ {LEAF_MIN * MM:.0f} mm per leaf" + ("" if residential else f", ≥ {need_cap * MM:,.0f} mm total for {load} occupants"),
            "Clear width is the leaf less stops and the open leaf (90 mm for a single leaf, 50 mm per leaf for a pair); "
            "a pair counts both leaves towards capacity.",
            ([worst.id] if not leaf_ok else []) + [i for i in narrow if i != worst.id] or [worst.id],
            (advice[0][0].upper() + "; ".join(advice)[1:] + ".") if advice else ""))

    travel = _travel(m)
    limits = TRAVEL_LIMIT.get(group)
    if travel:
        worst_room, worst = max(travel, key=lambda x: x[1])
        if limits is None:
            checks.append(_check("egress.travel", "Egress", "Exit access travel distance", "IRC (no limit)", "info",
                                 f"{worst:.1f} m ({ft(worst)}) from {worst_room.number} {worst_room.name}", "—",
                                 "Dwellings have no travel-distance limit; reported for information.", [worst_room.id]))
        else:
            unspr, spr = limits
            status = "pass" if worst <= unspr else "warn" if worst <= spr else "fail"
            checks.append(_check(
                "egress.travel", "Egress", "Exit access travel distance", "IBC Table 1017.2", status,
                f"{worst:.1f} m ({ft(worst)}) from {worst_room.number} {worst_room.name}",
                f"≤ {unspr:.0f} m unsprinklered ({spr:.0f} m sprinklered)",
                "Rectilinear path from the room's furthest corner, via open stairs, to the nearest exterior door.",
                [worst_room.id], "" if status == "pass" else
                "Sprinkler the building (NFPA 13) or add an exit nearer this room." if status == "warn" else
                "Add an exit: the path is too long even with sprinklers."))

    # --- stairs -------------------------------------------------------------
    ref = "IRC R311.7.5 / R311.7.1" if residential else "IBC 1011.5.2 / 1011.2"

    def height_of(lid: str) -> float:
        return (m.levels[lid].elevation or 0.0) if lid in m.levels else 0.0

    for s in m.stairs:
        # IBC 1011.2: 44 in wide, or 36 in when the stair serves fewer than 50 occupants (the storeys above it).
        served = sum(v for lid, v in per_level.items() if height_of(lid) > height_of(s.level) + 1e-6)
        max_riser, min_tread, min_width = (0.196, 0.254, 0.914) if residential else (0.178, 0.279, 0.914 if served < 50 else 1.118)
        rise = s.rise or m.levels[s.level].height
        riser = rise / s.steps(rise)
        issues, fixes = [], []
        if riser > max_riser + 1e-6:
            issues.append(f"riser {riser * MM:.0f} > {max_riser * MM:.0f} mm")
            n = math.ceil(rise / max_riser - 1e-9)
            fixes.append(f"use {n} risers of {rise / n * MM:.0f} mm (the flight grows by {(n - s.steps(rise)) * s.going * MM:,.0f} mm)")
        if s.going < min_tread - 1e-6:
            issues.append(f"tread {s.going * MM:.0f} < {min_tread * MM:.0f} mm")
            fixes.append(f"deepen the going to {min_tread * MM:.0f} mm")
        if s.width < min_width - 1e-6:
            issues.append(f"width {s.width * MM:.0f} < {min_width * MM:.0f} mm")
            fixes.append(f"widen the flight to {min_width * MM:,.0f} mm clear")
        checks.append(_check(
            f"stairs.{s.id}", "Stairs", f"Stair geometry — {s.name or s.id}", ref, "fail" if issues else "pass",
            f"{s.steps(rise)} risers × {riser * MM:.0f} mm, {s.going * MM:.0f} mm tread, {s.width * MM:.0f} mm wide",
            f"riser ≤ {max_riser * MM:.0f}, tread ≥ {min_tread * MM:.0f}, width ≥ {min_width * MM:.0f} mm",
            "; ".join(issues) if issues else f"2R + G = {(2 * riser + s.going) * MM:.0f} mm, within the 550–700 mm comfort band.",
            [s.id], (fixes[0][0].upper() + "; ".join(fixes)[1:] + ".") if fixes else ""))

    # --- headroom -----------------------------------------------------------
    min_h = 2.134 if residential else 2.286
    low = [r for r in m.rooms if r.kind not in OUTDOOR and r.height < min_h - 1e-6]
    lowest = min((r.height for r in m.rooms if r.kind not in OUTDOOR), default=0.0)
    checks.append(_check(
        "space.ceiling", "Space", "Ceiling height", "IRC R305.1" if residential else "IBC 1208.2",
        "fail" if low else "pass", f"{lowest * MM:,.0f} mm lowest clear", f"≥ {min_h * MM:,.0f} mm",
        "Floor-to-floor less a 200 mm floor zone above.", [r.id for r in low],
        "Raise the floor-to-floor height of the storey." if low else ""))

    # --- daylight and ventilation ------------------------------------------
    hab = [r for r in m.rooms if r.kind in HABITABLE and r.area > 0]
    if hab:
        dark = [r for r in hab if r.glazing < 0.08 * r.area - 1e-6]
        ratios = sorted(hab, key=lambda r: r.glazing / r.area)
        worst = ratios[0]
        checks.append(_check(
            "light.natural", "Daylight", "Natural light to habitable rooms", "IRC R303.1" if residential else "IBC 1204.2",
            "pass" if not dark else "warn", f"{worst.glazing / worst.area:.0%} lowest ({worst.number} {worst.name})",
            "glazing ≥ 8 % of floor area",
            f"{len(hab) - len(dark)} of {len(hab)} habitable rooms meet 8 %." +
            (" Rooms below: " + ", ".join(f"{r.number} {r.name} {r.glazing / r.area:.0%}" for r in dark) + "." if dark else ""),
            [r.id for r in dark],
            "Add or enlarge windows, or provide artificial light to 10 fc (IBC 1204.3)." if dark else ""))
        stuffy = [r for r in hab if 0.5 * r.glazing < 0.04 * r.area - 1e-6]
        checks.append(_check(
            "air.natural", "Ventilation", "Natural ventilation openings", "IRC R303.1" if residential else "IBC 1202.5.1",
            "pass" if not stuffy else "warn", f"{len(hab) - len(stuffy)} of {len(hab)} rooms",
            "openable area ≥ 4 % of floor area",
            "Assumes half of each window opens." + (
                " Mechanical ventilation needed in: " + ", ".join(f"{r.number} {r.name}" for r in stuffy) + "." if stuffy else ""),
            [r.id for r in stuffy], "Provide mechanical ventilation per IMC 403 where openings fall short." if stuffy else ""))

    # --- emergency escape (sleeping rooms) ---------------------------------
    sleeping = [r for r in m.rooms if r.kind in ("bedroom", "ward")]
    if sleeping and (residential or group in ("R-3",)):
        bad = []
        for r in sleeping:
            ok = any(w.width * w.height * 0.8 >= (0.465 if r.level == ground else 0.53) and w.sill_height <= 1.118
                     and w.width >= 0.508 and w.height >= 0.61 for w in r.windows)
            if not ok:
                bad.append(r)
        checks.append(_check(
            "egress.eero", "Egress", "Emergency escape openings in sleeping rooms", "IRC R310.2",
            "fail" if bad else "pass", f"{len(sleeping) - len(bad)} of {len(sleeping)} bedrooms",
            "net clear ≥ 0.53 m² (5.7 sf), sill ≤ 1,118 mm",
            "Net clear opening taken as 80 % of the frame (casement)." +
            (" Missing in: " + ", ".join(f"{r.number} {r.name}" for r in bad) + "." if bad else ""),
            [r.id for r in bad], "Give each bedroom an openable window of at least 0.9 × 0.9 m with a sill ≤ 1.1 m." if bad else ""))

    # --- habitable room size ------------------------------------------------
    if residential:
        small = [r for r in m.rooms if r.kind in ("living", "bedroom", "dining", "office")
                 and (r.area < 6.5 or r.min_dim < 2.134)]
        checks.append(_check(
            "space.min-room", "Space", "Minimum habitable room size", "IRC R304.1 / R304.2",
            "fail" if small else "pass", f"{min((r.area for r in m.rooms if r.kind in ('living', 'bedroom')), default=0):.1f} m² smallest",
            "≥ 6.5 m² (70 sf), ≥ 2,134 mm in any direction",
            "Kitchens are exempt." + (" Undersized: " + ", ".join(f"{r.number} {r.name}" for r in small) + "." if small else ""),
            [r.id for r in small], "Enlarge the room or reclassify it as storage." if small else ""))

    # --- accessibility ------------------------------------------------------
    if not residential:
        accessible = [d for d in ext if _clear_width(d) >= 0.813]
        checks.append(_check(
            "access.entrance", "Accessibility", "Accessible entrance", "IBC 1105.1 / ADA 404.2.3",
            "pass" if accessible else "fail", f"{len(accessible)} of {len(ext)} entrances",
            "≥ 60 % of public entrances, 815 mm (32 in) clear",
            "Clear width measured with the door open 90°.", [d.id for d in ext if d not in accessible],
            "" if accessible else "Widen the main entrance leaf to at least 915 mm."))
        interior = [d for d in m.doors if d not in ext]
        narrow = [d for d in interior if _clear_width(d) < 0.813 - 1e-6]
        checks.append(_check(
            "access.doors", "Accessibility", "Door clear widths on accessible routes", "ADA 404.2.3",
            "pass" if not narrow else "warn", f"{len(interior) - len(narrow)} of {len(interior)} interior doors",
            "≥ 815 mm (32 in) clear", f"{len(narrow)} doors narrower than 815 mm clear.",
            [d.id for d in narrow], "Use 915 mm (3'-0\") leaves throughout." if narrow else ""))
        wcs = [r for r in m.rooms if r.kind == "bathroom"]
        turning = [r for r in wcs if r.min_dim >= 1.525]
        checks.append(_check(
            "access.toilet", "Accessibility", "Accessible toilet room", "ADA 213.2 / 304.3.1",
            "pass" if turning else ("fail" if wcs else "fail"),
            f"{len(turning)} of {len(wcs)} toilet rooms fit a 1,525 mm turning circle", "≥ 1",
            "Turning space checked against each toilet room's smallest plan dimension.",
            [r.id for r in wcs if r not in turning] or ([] if wcs else [ground]),
            "" if turning else "Make one toilet room at least 1.6 × 2.2 m with a 1,525 mm turning circle."))
        shafts = lifts(m.spec)
        if len(m.order) > 1 and shafts:
            first = shafts[0][0]
            checks.append(_check(
                "access.vertical", "Accessibility", "Accessible route between storeys", "IBC 1104.4 / ADA 206.2.3",
                "pass", f"{len(shafts)} {'lift' if len(shafts) == 1 else 'lifts'} ({first.name or first.brick.replace('_', ' ')})",
                "elevator or platform lift", "Every storey is on an accessible route.", [a.id for s in shafts for a in s], ""))
        elif len(m.order) > 1:
            checks.append(_check(
                "access.vertical", "Accessibility", "Accessible route between storeys", "IBC 1104.4 / ADA 206.2.3",
                "warn", "stairs only", "elevator or platform lift",
                "No elevator in the model. Two-storey buildings under 3,000 sf per storey are exempt for some "
                "occupancies (IBC 1104.4 exc. 1); confirm with the AHJ.", m.order[1:],
                "Allow a 2.0 × 2.2 m shaft for a MRL elevator next to the stair."))

    # --- plumbing fixtures --------------------------------------------------
    toilets = [f for f in m.fixtures if f.kind == "toilet"] + [
        a for a in m.assets if TOILET.search(a.brick)]
    count = len(toilets) or sum(1 for r in m.rooms if r.kind == "bathroom")
    if residential:
        need = 1
        ref = "IRC R306.1"
    else:
        ratio = WC_RATIO.get(group, 50)
        need = max(1, math.ceil(min(load, 50) / ratio) + (math.ceil(max(0, load - 50) / (ratio * 2)) if load > 50 else 0))
        ref = "IBC Table 2902.1"
    checks.append(_check(
        "plumbing.wc", "Plumbing", "Water closets", ref, "pass" if count >= need else "fail",
        f"{count} provided", f"≥ {need}" + ("" if residential else f" for {load} occupants"),
        ("Counted from placed toilets." if toilets else "No toilets placed; counted one per toilet room."),
        [f.id for f in toilets] or [r.id for r in m.rooms if r.kind == "bathroom"],
        "" if count >= need else f"Add {need - count} WC(s); separate facilities per sex above 15 occupants (IBC 2902.2)."))
    return checks


def _extent(m: Model) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for r in m.rooms:
        x0, y0, x1, y1 = r.polygon.bounds
        xs += [x0, x1]
        ys += [y0, y1]
    for w in m.walls.values():
        for p in w.axis:
            xs.append(p[0])
            ys.append(p[1])
    return (min(xs, default=0), min(ys, default=0), max(xs, default=0), max(ys, default=0))


def review(spec: BuildingSpec, design: Design | None = None) -> dict:
    m = Model(spec, design)
    group, areas = _occupancy(m)
    _load(m, group)
    load = sum(r.occupants for r in m.rooms)
    levels = _level_rows(m)
    checks = _checks(m, group, load)
    counts = Counter(c["status"] for c in checks)
    gia = sum(l["gia"] for l in levels)
    nia = sum(l["nia"] for l in levels)
    mixed = sorted(g for g in areas if g != group and areas[g] > 0.1 * sum(areas.values()))
    return {
        "code": "IRC 2021" if group == "R-3" else "IBC 2021 + 2010 ADA Standards",
        "occupancy": {"group": group, "name": GROUP_NAMES.get(group, group), "load": load, "mixed": mixed,
                      "construction": "Type V-B (combustible, unprotected)" if group in ("R-3", "U") else
                                      "Type II-B assumed (non-combustible, unprotected)",
                      "sprinklered": False},
        "totals": {"gia": round(gia, 2), "nia": round(nia, 2), "gia_sf": round(gia * 10.7639),
                   "efficiency": round(nia / gia, 3) if gia else 0.0, "rooms": len(m.rooms), "storeys": len(levels),
                   "height": round(sum(l.height for l in spec.levels), 2)},
        "levels": levels,
        "rooms": [r.json() for r in m.rooms],
        "checks": checks,
        "score": {"pass": counts["pass"], "warn": counts["warn"], "fail": counts["fail"], "info": counts["info"],
                  "total": len(checks)},
        "assumptions": [
            "Design-stage screen from model geometry; not a substitute for plan review by the AHJ.",
            "Unsprinklered, open (unenclosed) stairs, 200 mm floor zone, half of each window openable.",
            "Occupant loads from IBC Table 1004.5 using each room's own function.",
        ],
    }
