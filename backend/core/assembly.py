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
from core.clash import clashes
from core.derive import DesignError, Derived, analyze
from core.issues import Issue
from schemas.bim import Asset
from schemas.design import Design, RoomDef
from schemas.steps import Step, StepError, apply_step

PLANT_ROOMS = ("utility", "garage", "storage")
SERVICE_WORDS = {"water_hot": "hot water", "water_cold": "cold water", "air_supply": "supply air", "air_return": "return air",
                 "fire_water": "sprinkler water"}


def providers(kind: str) -> list[Brick]:
    """Bricks providing `kind`, self-sufficient ones (needing only base services) first."""
    found = [b for b in library().bricks.values() if kind in b.provides]
    return sorted(found, key=lambda b: (len(set(b.needs) - set(BASE_SERVICES)), b.discipline != _home(kind), b.id))


def _home(kind: str) -> str:
    return {"data": "data", "fire_water": "fire", "power": "energy"}.get(kind, "hvac" if kind in ("air_supply", "air_return", "heating", "refrigerant", "flue") else "plumbing")


def candidates(brick: Brick, design: Design, derived: Derived, near_room: str | None = None, slot: int = 0,
               room_kind: str | None = None) -> list[dict]:
    """Arguments of `brick` steps that would place it sensibly, best first (empty when nowhere fits its rules)."""
    if brick.host == "roof":
        return [{}]
    polys = derived.footprints.get("L1") or next((p for p in derived.footprints.values() if p), [])
    if brick.host == "span" and brick.rules.exterior:
        if not polys:
            return []
        x0, y0, x1, y1 = unary_union(polys).bounds
        g = 2.0 + slot * 1.5
        lines = [((x0 - g, y1 + g), (x1 + g, y1 + g)), ((x1 + g, y0 - g), (x1 + g, y1 + g)),
                 ((x0 - g, y0 - g), (x0 - g, y1 + g)), ((x0 - g, y0 - g), (x1 + g, y0 - g))]
        return [{"start": [round(a[0], 2), round(a[1], 2)], "end": [round(b[0], 2), round(b[1], 2)]} for a, b in lines]
    if brick.rules.exterior or (brick.host == "free" and not design.rooms):
        if not polys:
            return []
        x0, y0, x1, y1 = unary_union(polys).bounds
        v = brick.resolve()
        gap = 1.0 + max(v["w"], v.get("d", v["w"])) / 2
        spots = []
        for k in range(slot, slot + 4):
            t = 0.25 + 0.5 * (k % 2)
            spots += [[x1 + gap, y0 + (y1 - y0) * t], [x0 - gap, y0 + (y1 - y0) * t], [x0 + (x1 - x0) * t, y1 + gap],
                      [x0 + (x1 - x0) * t, y0 - gap - 1.0]]
        return [{"position": [round(x, 2), round(y, 2)]} for x, y in spots]
    if brick.host == "span":
        return []
    enclosed = [r for r in design.rooms if r.enclosed and (not brick.rules.ground_only or r.level == "L1")]
    if room_kind:
        enclosed = [r for r in enclosed if r.kind == room_kind] or enclosed
    # Rules name where a brick usually goes; with no such room, any room will do (the rule check warns).
    rooms = [r for r in enclosed if not brick.rules.rooms or r.kind in brick.rules.rooms] or enclosed
    rooms.sort(key=lambda r: (r.id != near_room, r.kind not in PLANT_ROOMS, -r.area_m2))
    sides = [("N", "E", "S", "W")[(slot + i) % 4] for i in range(4)]
    out: list[dict] = []
    for room in rooms:
        if brick.host == "ceiling":
            out.append({"room": room.id})
            continue
        for at in (0.5, 0.15, 0.85):
            out += [{"room": room.id, "side": side, "at": at} for side in sides]
        out.append({"room": room.id, "side": "center"})
    return out


def first_fit(brick: Brick, design: Design, options: list[dict], limit: int = 40) -> tuple[dict, Design] | None:
    """The first placement that applies, derives and clashes with nothing, with the design it makes."""
    for args in options[:limit]:
        step = {"step": "brick", "brick": brick.id, **args}
        try:
            candidate, _ = apply_step(design, Step(**step))
            derived = analyze(candidate)
        except (StepError, DesignError, ValueError):
            continue
        if not [i for i in clashes(derived.spec, {candidate.bricks[-1].id}) if i.severity == "error"]:
            return args, candidate
    return None


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
            fit = first_fit(brick, design, candidates(brick, design, derived, users[0].room, slot))
            if fit is not None:
                steps.append({"step": "brick", "brick": brick.id, **fit[0]})
                design = fit[1]
                derived = analyze(design)
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
