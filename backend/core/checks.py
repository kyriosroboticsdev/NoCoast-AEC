"""Deterministic verification of a design against its requirements.

Each requirement kind maps to a check on the derived design (room list, adjacency,
exterior sides, openings, fixtures, roof …). The result is a list of `CheckResult`s;
unmet ones are fed back to the model as a fix round and shown to the user, and the
evaluation script scores a model by the fraction met.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bricks import library
from core import structure
from core.derive import Derived
from schemas.design import Design, RoomDef, guess_kind, slug
from schemas.requirements import Requirement

KIND_SYNONYMS = {
    "bedroom": "bedroom", "bed": "bedroom", "bedrooms": "bedroom", "bathroom": "bathroom", "bath": "bathroom", "wc": "bathroom",
    "toilet": "bathroom", "ensuite": "bathroom", "en-suite": "bathroom", "kitchen": "kitchen", "living": "living", "lounge": "living",
    "living room": "living", "dining": "dining", "dining room": "dining", "office": "office", "study": "office", "hall": "hall",
    "hallway": "hall", "entry": "hall", "garage": "garage", "utility": "utility", "laundry": "utility", "storage": "storage",
    "pantry": "storage", "closet": "storage",
}
FURNITURE_SYNONYMS = {
    "bed": ("bed", "double_bed", "bunk_bed"), "double bed": ("double_bed",), "bunk bed": ("bunk_bed",), "sofa": ("sofa",),
    "couch": ("sofa",), "table": ("dining_table", "coffee_table", "desk"), "dining table": ("dining_table",),
    "coffee table": ("coffee_table",), "desk": ("desk",), "wardrobe": ("wardrobe",), "closet": ("wardrobe",),
    "counter": ("kitchen_counter", "island"), "kitchen counter": ("kitchen_counter",), "island": ("island",),
    "fridge": ("fridge",), "refrigerator": ("fridge",), "oven": ("oven",), "stove": ("oven",), "sink": ("sink", "washbasin"),
    "dishwasher": ("dishwasher",), "washing machine": ("washing_machine",), "toilet": ("toilet",), "shower": ("shower",),
    "bathtub": ("bathtub",), "bath": ("bathtub",), "tub": ("bathtub",), "washbasin": ("washbasin",), "basin": ("washbasin",),
    "fireplace": ("fireplace",), "car": ("car",), "tv": ("tv_stand",), "bookshelf": ("bookshelf",), "shelf": ("bookshelf",),
    "armchair": ("armchair",), "chair": ("chair", "armchair"), "dresser": ("dresser",),
}


@dataclass
class CheckResult:
    requirement: Requirement
    status: str        # met | unmet | unsupported | skipped
    detail: str

    @property
    def ok(self) -> bool:
        return self.status in ("met", "skipped")

    def line(self) -> str:
        mark = {"met": "[met]", "unmet": "[UNMET]", "unsupported": "[unsupported]", "skipped": "[not checked]"}[self.status]
        return f"{mark} {self.requirement.text} — {self.detail}"


def _match_rooms(design: Design, ref: str | None, level: str | None = None) -> list[RoomDef]:
    """Rooms matching a name ('Master Bedroom'), an id, or a kind keyword ('bedroom')."""
    rooms = [r for r in design.rooms if level is None or r.level == level]
    if not ref:
        return rooms
    key = ref.strip().lower()
    exact = [r for r in rooms if r.id == slug(key) or r.name.lower() == key]
    if exact:
        return exact
    kind = KIND_SYNONYMS.get(key) or (guess_kind(key) if guess_kind(key) != "other" else None)
    by_kind = [r for r in rooms if kind and r.kind == kind]
    by_name = [r for r in rooms if key in r.name.lower() or all(w in r.name.lower() for w in key.split())]
    return list({r.id: r for r in by_name + by_kind}.values())


def _fixtures_for(item: str | None) -> tuple[str, ...]:
    if not item:
        return ()
    key = item.strip().lower().replace("_", " ")
    if key in FURNITURE_SYNONYMS:
        return FURNITURE_SYNONYMS[key]
    norm = key.replace(" ", "_")
    return (norm,)


def check(design: Design, derived: Derived, requirements: list[Requirement]) -> list[CheckResult]:
    out: list[CheckResult] = []
    for req in requirements:
        if not req.supported:
            out.append(CheckResult(req, "unsupported", "not supported by the builder"))
            continue
        try:
            out.append(_check_one(design, derived, req))
        except Exception as exc:  # noqa: BLE001 - a check must never break the pipeline
            out.append(CheckResult(req, "skipped", f"check failed: {exc}"))
    return out


def _check_one(design: Design, d: Derived, req: Requirement) -> CheckResult:
    k = req.kind
    n = int(req.value) if req.value else 1

    if k == "storeys":
        have = design.storeys()
        return CheckResult(req, "met" if have == n else "unmet", f"{have} storey(s), wanted {n}")

    if k == "room":
        rooms = _match_rooms(design, req.room, req.level)
        where = f" on {req.level}" if req.level else ""
        if len(rooms) >= n:
            return CheckResult(req, "met", f"{', '.join(r.name for r in rooms[:6])}{where}")
        return CheckResult(req, "unmet", f"found {len(rooms)} '{req.room}' room(s){where}, wanted {n}")

    if k == "room_level":
        rooms = _match_rooms(design, req.room)
        if not rooms:
            return CheckResult(req, "unmet", f"no room matches '{req.room}'")
        on = [r for r in rooms if r.level == req.level]
        return CheckResult(req, "met" if on else "unmet", f"{rooms[0].name} is on {rooms[0].level}" if not on else f"{on[0].name} on {req.level}")

    if k == "area":
        rooms = _match_rooms(design, req.room)
        if not rooms or not req.value:
            return CheckResult(req, "unmet" if not rooms else "skipped", f"no room matches '{req.room}'" if not rooms else "no target area")
        r = rooms[0]
        area = r.area_m2
        ok = abs(area - req.value) <= 0.25 * req.value
        return CheckResult(req, "met" if ok else "unmet", f"{r.name} is {area:.0f} m², wanted {req.value:.0f} m²")

    if k == "adjacent":
        a, b = _match_rooms(design, req.room), _match_rooms(design, req.room2)
        if not a or not b:
            return CheckResult(req, "unmet", f"no room matches '{req.room if not a else req.room2}'")
        for ra in a:
            for rb in b:
                if rb.id in d.rooms[ra.id].neighbours:
                    return CheckResult(req, "met", f"{ra.name} shares a wall with {rb.name}")
        return CheckResult(req, "unmet", f"{a[0].name} touches {', '.join(d.rooms[a[0].id].neighbours) or 'nothing'}")

    if k == "orientation":
        rooms = _match_rooms(design, req.room)
        if not rooms:
            return CheckResult(req, "unmet", f"no room matches '{req.room}'")
        for r in rooms:
            info = d.rooms[r.id]
            if req.side in info.sides:
                return CheckResult(req, "met", f"{r.name} has an exterior {req.side} wall")
            if req.side in info.open_sides:
                return CheckResult(req, "met", f"{r.name} is open to the {req.side}")
        info = d.rooms[rooms[0].id]
        have = info.sides + [s for s in info.open_sides if s not in info.sides]
        return CheckResult(req, "unmet", f"{rooms[0].name}'s exterior sides are {', '.join(have) or 'none'}")

    if k == "window":
        rooms = _match_rooms(design, req.room) if req.room else design.rooms
        if req.room and not rooms:
            return CheckResult(req, "unmet", f"no room matches '{req.room}'")
        ids = {r.id for r in rooms}
        wins = [w for w in design.windows if w.room in ids and (req.side is None or (w.side or d.sides.get(w.id)) == req.side)]
        return CheckResult(req, "met" if len(wins) >= n else "unmet", f"{len(wins)} window(s)" + (f" on side {req.side}" if req.side else "") + f", wanted {n}")

    if k == "door":
        a = _match_rooms(design, req.room)
        if not a:
            # A gate in a garden wall: a door hosted by a free-standing wall element named like the "room".
            key = (req.room or "").lower()
            walls = [e for e in design.elements if e.kind == "wall" and e.name and (key in e.name.lower() or e.name.lower() in key)]
            gates = [d for d in design.doors if d.wall and d.wall in {w.id for w in walls}]
            if gates:
                return CheckResult(req, "met", f"door {gates[0].id} in {walls[0].name}")
            if walls:
                return CheckResult(req, "unmet", f"{walls[0].name} has no door")
            return CheckResult(req, "unmet", f"no room matches '{req.room}'")
        to_out = (req.room2 or "outside").lower() in ("outside", "exterior", "garden", "street")
        b = [] if to_out else _match_rooms(design, req.room2)
        for ra in a:
            for door in design.doors:
                if to_out and door.room == ra.id and door.to == "outside":
                    return CheckResult(req, "met", f"{ra.name} has an exterior door")
                if not to_out and any((door.room == ra.id and door.to == rb.id) or (door.room == rb.id and door.to == ra.id) for rb in b):
                    return CheckResult(req, "met", f"door between {ra.name} and {req.room2}")
        return CheckResult(req, "unmet", f"no door from {a[0].name} to {req.room2 or 'outside'}")

    if k == "stair":
        stairs = design.stairs
        if req.room:
            ids = {r.id for r in _match_rooms(design, req.room)}
            stairs = [s for s in stairs if s.room in ids]
        return CheckResult(req, "met" if stairs else "unmet", f"{len(stairs)} stair(s)" + (f" in {req.room}" if req.room else ""))

    if k == "furniture":
        kinds = _fixtures_for(req.item)
        fx = [(f, f.room) for f in design.fixtures if f.kind in kinds]
        fx += [(b, b.ref) for b in design.bricks if b.brick in kinds or _fixture_kind(design, b.brick) in kinds]
        if req.room:
            ids = {r.id for r in _match_rooms(design, req.room)}
            fx = [(f, room) for f, room in fx if room in ids]
        return CheckResult(req, "met" if len(fx) >= n else "unmet", f"{len(fx)} {req.item}(s)" + (f" in {req.room}" if req.room else "") + f", wanted {n}")

    if k == "asset":
        own = {b.id for b in design.library if req.item.strip().lower().replace(" ", "_") in (b.id, b.name.lower().replace(" ", "_"))}
        wanted = own or library().resolve(req.item)
        if not wanted:
            return CheckResult(req, "unmet", f"no brick in the library or the design's assets matches '{req.item}'")
        placed = [b for b in design.bricks if b.brick in wanted]
        if req.room:
            ids = {r.id for r in _match_rooms(design, req.room)}
            placed = [b for b in placed if b.ref in ids]
        where = f" in {req.room}" if req.room else ""
        return CheckResult(req, "met" if len(placed) >= n else "unmet",
                           f"{len(placed)} of {'/'.join(sorted(wanted)[:3])}{where}, wanted {n}")

    if k == "structure":
        found = structure.report(design, d)
        if found:
            return CheckResult(req, "unmet", "; ".join(i.message for i in found[:3]))
        return CheckResult(req, "met", f"spans within {structure.span_limit(design):g} m or supported, no unsupported overhangs")

    if k == "roof":
        want = (req.item or "").lower()
        want = {"pitched": "gable", "gabled": "gable", "hipped": "hip"}.get(want, want)
        return CheckResult(req, "met" if design.roof.kind == want else "unmet", f"roof is {design.roof.kind}, wanted {want}")

    if k == "feature":
        item = (req.item or "").lower()
        if "garage" in item and "carport" not in item:
            have = [r for r in design.rooms if r.kind == "garage"]
            return CheckResult(req, "met" if have else "unmet", "garage present" if have else "no garage room")
        if "porch" in item or "veranda" in item:
            return CheckResult(req, "met" if design.porch else "unmet", "porch present" if design.porch else "no porch")
        if "basement" in item or "cellar" in item or "underground" in item:
            have = design.basements()
            return CheckResult(req, "met" if have else "unmet", f"{have} basement level(s)" if have else "no level below ground")
        for kind, words in (("courtyard", ("courtyard", "patio", "atrium")), ("terrace", ("terrace", "roof deck", "deck")),
                            ("carport", ("carport",)), ("pergola", ("pergola", "loggia", "gazebo"))):
            if any(w in item for w in words):
                rooms = [r for r in design.rooms if r.kind == kind]
                named = [e for e in design.elements if e.name and any(w in e.name.lower() for w in words)]
                if rooms or named:
                    return CheckResult(req, "met", f"{kind} present" + (f" ({rooms[0].name})" if rooms else f" ({named[0].name})"))
                return CheckResult(req, "unmet", f"no {kind} room or element")
        if "curved" in item or "round" in item or "arc" in item:
            arcs = [r for r in design.rooms if r.poly and any(e.through for e in r.poly)] + [e for e in design.elements if e.kind == "wall" and e.path and any(x.through for x in e.path)]
            return CheckResult(req, "met" if arcs else "unmet", f"{len(arcs)} curved wall(s)" if arcs else "no curved walls")
        if "l-shaped" in item or "l shaped" in item or "polygon" in item:
            polys = [r for r in design.rooms if r.poly]
            return CheckResult(req, "met" if polys else "unmet", f"{len(polys)} non-rectangular room(s)" if polys else "all rooms are rectangles")
        named = [e for e in design.elements if e.name and (item in e.name.lower() or e.name.lower() in item)]
        if named:
            return CheckResult(req, "met", f"free element '{named[0].name}'")
        if "balcon" in item or "terrace" in item:
            return CheckResult(req, "met" if design.balconies else "unmet", f"{len(design.balconies)} balcony(ies)")
        if "open" in item:  # open plan: kitchen and living share a wall (best we can do without merged rooms)
            return CheckResult(req, "skipped", "open-plan layouts are approximated by adjacent rooms")
        return CheckResult(req, "skipped", f"feature '{req.item}' has no automatic check")

    if k == "dimension":
        if not req.value or not d.footprints.get("L1"):
            return CheckResult(req, "skipped", "no footprint to compare")
        minx, miny, maxx, maxy = d.footprints["L1"][0].bounds if len(d.footprints["L1"]) == 1 else _bounds(d.footprints["L1"])
        w, dp = maxx - minx, maxy - miny
        want = sorted([req.value, req.value2 or req.value])
        have = sorted([w, dp])
        ok = all(abs(h - x) <= 0.2 * x for h, x in zip(have, want))
        return CheckResult(req, "met" if ok else "unmet", f"footprint {w:.1f} x {dp:.1f} m, wanted {want[0]:.1f} x {want[1]:.1f}")

    if k == "material":
        want = (req.item or "").lower()
        return CheckResult(req, "met" if design.wall_material == want else "unmet", f"walls are {design.wall_material or 'default'}, wanted {want}")

    return CheckResult(req, "skipped", "not automatically checkable")


def _bounds(polys):
    xs = [b for p in polys for b in (p.bounds[0], p.bounds[2])]
    ys = [b for p in polys for b in (p.bounds[1], p.bounds[3])]
    return min(xs), min(ys), max(xs), max(ys)


def score(results: list[CheckResult]) -> tuple[int, int]:
    """(met, checkable) — unsupported and skipped requirements do not count."""
    checkable = [r for r in results if r.status in ("met", "unmet")]
    return sum(1 for r in checkable if r.status == "met"), len(checkable)


def unmet_lines(results: list[CheckResult]) -> list[str]:
    return [f"{r.requirement.text} — {r.detail}" for r in results if r.status == "unmet"]


def is_verifiable(text: str) -> bool:
    return not re.search(r"\b(modern|cozy|cosy|beautiful|nice|elegant|minimal|style|feel|vibe)\b", text.lower())


def _fixture_kind(design: Design, brick_id: str) -> str | None:
    """The catalogue furniture kind a brick stands in for (its `fixture` property), if any."""
    brick = design.find_brick(brick_id)
    kind = brick.properties.get("fixture") if brick else None
    return kind if isinstance(kind, str) else None
