"""Does the assembly work as a system? Service ports and placement rules of the placed bricks.

Every brick lists the services it needs (`in` ports) and provides (`out` ports). Once a building has
rooms the derived rough-in supplies cold water, drainage and power everywhere (`BASE_SERVICES`); any
other need — hot water, heating, supply air, data, gas, a flue, sprinkler water, refrigerant — must be
provided by some brick in the design, or it is an issue that names the bricks that would provide it
and suggests a step placing the best one. Placement rules (which room kinds a brick belongs in, the
room area it needs) are reported as warnings.
"""

from __future__ import annotations

from bricks import BASE_SERVICES, Brick, library
from core.derive import Derived
from core.issues import Issue
from core.placement import candidates, first_fit
from schemas.bim import Asset
from schemas.brick_types import PortKind
from schemas.design import Design, RoomDef

SERVICE_WORDS = {"water_hot": "hot water", "water_cold": "cold water", "air_supply": "supply air", "air_return": "return air",
                 "fire_water": "sprinkler water"}


def providers(kind: str) -> list[Brick]:
    """Bricks providing `kind`, self-sufficient ones (needing only base services) first."""
    found = [b for b in library().bricks.values() if kind in b.provides]
    return sorted(found, key=lambda b: (len(set(b.needs) - set(BASE_SERVICES)), b.discipline != _home(kind), b.id))


def _home(kind: str) -> str:
    return {"data": "data", "fire_water": "fire", "power": "energy"}.get(kind, "hvac" if kind in ("air_supply", "air_return", "heating", "refrigerant", "flue") else "plumbing")


def services(design: Design, derived: Derived) -> list[Issue]:
    """An error per service some brick needs that nothing provides, each with the provider brick that fits."""
    assets = [e for e in derived.spec.elements if isinstance(e, Asset)]
    provided = set(BASE_SERVICES) if design.rooms else set()
    provided |= {p.kind for a in assets for p in a.ports if p.direction == "out"}
    missing: dict[PortKind, list[Asset]] = {}
    for a in assets:
        for p in a.ports:
            if p.direction == "in" and p.kind not in provided:
                missing.setdefault(p.kind, []).append(a)
    gaps = [(kind, users, providers(kind)) for kind, users in sorted(missing.items())]
    issues = []
    for kind, users, offer in gaps:
        names = ", ".join(f"{u.brick} '{u.id}'" for u in users[:4]) + (" …" if len(users) > 4 else "")
        hint = f"; add one of: {', '.join(b.id for b in offer[:4])}" if offer else ""
        issues.append(Issue("service", "error", f"{names} need{'s' if len(users) == 1 else ''} {SERVICE_WORDS.get(kind, kind)}, "
                                                f"but nothing in the design provides it{hint}", [u.id for u in users]))
    _suggest_providers(issues, [(offer, users[0].room) for _, users, offer in gaps], design, derived)
    return issues


def _suggest_providers(issues: list[Issue], wanted: list[tuple[list[Brick], str | None]], design: Design, derived: Derived) -> None:
    """Attach to each issue a step placing its first provider that fits. Placed one after the other on
    the same design, so the suggestions can all be applied together without clashing."""
    for slot, (issue, (offer, near_room)) in enumerate(zip(issues, wanted)):
        for brick in offer:
            fit = first_fit(brick, design, candidates(brick, design, derived, near_room, slot))
            if fit is not None:
                args, design, derived = fit
                issue.suggestions.append({"step": "brick", "brick": brick.id, **args})
                break


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
