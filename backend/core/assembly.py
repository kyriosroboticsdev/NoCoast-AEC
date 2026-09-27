"""Does the assembly work as a system? Service ports and placement rules of the placed bricks.

Every brick lists the services it needs (`in` ports) and provides (`out` ports). Once a building has
rooms the derived rough-in supplies cold water, drainage and power everywhere (`BASE_SERVICES`); any
other need — hot water, heating, supply air, data, gas, a flue, sprinkler water, refrigerant — must be
provided by some brick in the design, or it is an issue that names the bricks that would provide it
and suggests a step placing the best one. Placement rules (which room kinds a brick belongs in, the
room area it needs) are reported as warnings.
"""

from __future__ import annotations

from shapely.ops import unary_union

from bricks import BASE_SERVICES, Brick, library
from core.derive import Derived
from core.issues import Issue
from schemas.bim import Asset
from schemas.design import Design, RoomDef

PLANT_ROOMS = ("utility", "garage", "storage")
SERVICE_WORDS = {"water_hot": "hot water", "water_cold": "cold water", "air_supply": "supply air", "air_return": "return air",
                 "fire_water": "sprinkler water"}


def providers(kind: str) -> list[Brick]:
    """Bricks providing `kind`, self-sufficient ones (needing only base services) first."""
    found = [b for b in library().bricks.values() if kind in b.provides]
    return sorted(found, key=lambda b: (len(set(b.needs) - set(BASE_SERVICES)), b.discipline != _home(kind), b.id))


def _home(kind: str) -> str:
    return {"data": "data", "fire_water": "fire", "power": "energy"}.get(kind, "hvac" if kind in ("air_supply", "air_return", "heating", "refrigerant", "flue") else "plumbing")


def placement_for(brick: Brick, design: Design, derived: Derived, near_room: str | None = None, slot: int = 0) -> dict | None:
    """Arguments of a `brick` step that would place `brick` sensibly, or None when there is no room for it."""
    if brick.host == "roof":
        return {}
    if brick.rules.exterior or (brick.host == "free" and not design.rooms):
        polys = derived.footprints.get("L1") or next((p for p in derived.footprints.values() if p), [])
        if not polys:
            return None
        x0, y0, x1, y1 = unary_union(polys).bounds
        w = brick.resolve()["w"]
        return {"position": [round(x1 + 1.0 + w / 2, 2), round(y0 + 1.0 + slot * 2.0, 2)]}
    if brick.host == "span":
        return None
    rooms = [r for r in design.rooms if r.enclosed and (not brick.rules.rooms or r.kind in brick.rules.rooms)]
    if brick.rules.ground_only:
        rooms = [r for r in rooms if r.level == "L1"]
    if not rooms:
        return None
    pick = (next((r for r in rooms if r.id == near_room), None) if near_room else None) \
        or next((r for r in rooms if r.kind in PLANT_ROOMS), None) or rooms[0]
    args: dict = {"room": pick.id}
    if brick.host in ("floor", "wall"):
        args["side"] = ("N", "E", "S", "W")[slot % 4]
    return args


def services(design: Design, derived: Derived) -> list[Issue]:
    assets = [e for e in derived.spec.elements if isinstance(e, Asset)]
    provided = set(BASE_SERVICES) if design.rooms else set()
    for a in assets:
        provided |= {p.split(":")[0] for p in a.ports if p.endswith(":out")}
    missing: dict[str, list[Asset]] = {}
    for a in assets:
        for p in a.ports:
            kind, direction = p.split(":")
            if direction == "in" and kind not in provided:
                missing.setdefault(kind, []).append(a)
    issues = []
    for slot, (kind, users) in enumerate(sorted(missing.items())):
        offer = providers(kind)
        names = ", ".join(f"{u.brick} '{u.id}'" for u in users[:4]) + (" …" if len(users) > 4 else "")
        steps = []
        for brick in offer:
            args = placement_for(brick, design, derived, users[0].room, slot)
            if args is not None:
                steps.append({"step": "brick", "brick": brick.id, **args})
                break
        hint = f"; add one of: {', '.join(b.id for b in offer[:4])}" if offer else ""
        issues.append(Issue("service", "error", f"{names} need{'s' if len(users) == 1 else ''} {SERVICE_WORDS.get(kind, kind)}, "
                                                f"but nothing in the design provides it{hint}",
                            [u.id for u in users], steps))
    return issues


def rules(design: Design, derived: Derived) -> list[Issue]:
    issues = []
    for a in (e for e in derived.spec.elements if isinstance(e, Asset)):
        brick = library().get(a.brick)
        room: RoomDef | None = design.room(a.room) if a.room else None
        if brick is None or room is None:
            continue
        if brick.rules.rooms and room.kind not in brick.rules.rooms:
            issues.append(Issue("rule", "warning", f"{a.brick} '{a.id}' usually belongs in a {' / '.join(brick.rules.rooms)} room, "
                                                   f"not a {room.kind} ({room.id})", [a.id]))
        if brick.rules.min_room_area and room.area_m2 < brick.rules.min_room_area:
            issues.append(Issue("rule", "warning", f"{a.brick} '{a.id}' wants a room of at least {brick.rules.min_room_area:g} m²; "
                                                   f"{room.id} is {room.area_m2:.0f} m²", [a.id]))
    return issues
