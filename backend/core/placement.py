"""Finding a spot for a brick: the candidate placements its host and rules allow, best first, and the
first of them that applies, derives and clashes with nothing.

Used wherever a placement has to be proposed rather than checked — the mock and template planner
placing bricks a prompt names, and coordination suggesting the brick that would fix an issue.
"""

from __future__ import annotations

from typing import assert_never

from shapely.ops import unary_union

from bricks import Brick
from core.clash import new_brick_clashes
from core.derive import DesignError, Derived, analyze
from core.structure import beam_line
from schemas.design import Design
from schemas.steps import Step, StepError, apply_step

PLANT_ROOMS = ("utility", "garage", "storage")
MAX_TRIES = 40


def candidates(brick: Brick, design: Design, derived: Derived, near_room: str | None = None, slot: int = 0,
               room_kind: str | None = None) -> list[dict]:
    """Arguments of `brick` steps that would place it sensibly, best first (empty when nowhere fits its rules).
    `slot` spreads several bricks of a kind over different sides; `near_room` / `room_kind` prefer a room."""
    ground = design.ground_level().id
    footprint = derived.footprints.get(ground) or next((p for p in derived.footprints.values() if p), [])
    bounds = unary_union(footprint).bounds if footprint else None
    match brick.host:
        case "roof":
            return [{}]
        case "site_span":
            return _around(bounds, slot) if bounds else []
        case "site":
            return _beside(brick, bounds, slot) if bounds else []
        case "span":
            return _across_largest_room(design, derived)
        case "free" if not design.rooms:
            return _beside(brick, bounds, slot) if bounds else []
        case "floor" | "wall" | "ceiling" | "free":
            return _in_rooms(brick, design, ground, near_room, slot, room_kind)
        case _:
            assert_never(brick.host)


def first_fit(brick: Brick, design: Design, options: list[dict]) -> tuple[dict, Design, Derived] | None:
    """The first placement that applies, derives and clashes with nothing, with the design it makes."""
    for args in options[:MAX_TRIES]:
        try:
            candidate, _ = apply_step(design, Step(step="brick", brick=brick.id, **args))
            derived = analyze(candidate)
        except (StepError, DesignError, ValueError):
            continue
        if not new_brick_clashes(design, candidate, derived.spec):
            return args, candidate, derived
    return None


def _around(bounds, slot: int) -> list[dict]:
    """Lines along the four sides of the building, `2 + 1.5·slot` m out (hedges, fences)."""
    x0, y0, x1, y1 = bounds
    g = 2.0 + slot * 1.5
    lines = [((x0 - g, y1 + g), (x1 + g, y1 + g)), ((x1 + g, y0 - g), (x1 + g, y1 + g)),
             ((x0 - g, y0 - g), (x0 - g, y1 + g)), ((x0 - g, y0 - g), (x1 + g, y0 - g))]
    return [{"start": [round(a[0], 2), round(a[1], 2)], "end": [round(b[0], 2), round(b[1], 2)]} for a, b in lines]


def _beside(brick: Brick, bounds, slot: int) -> list[dict]:
    """Spots a metre clear of the building on each side, at a quarter and three quarters along it."""
    x0, y0, x1, y1 = bounds
    v = brick.resolve()
    gap = 1.0 + max(v["w"], v.get("d", v["w"])) / 2
    spots = []
    for k in range(slot, slot + 4):
        t = 0.25 + 0.5 * (k % 2)
        spots += [[x1 + gap, y0 + (y1 - y0) * t], [x0 - gap, y0 + (y1 - y0) * t], [x0 + (x1 - x0) * t, y1 + gap],
                  [x0 + (x1 - x0) * t, y0 - gap - 1.0]]
    return [{"position": [round(x, 2), round(y, 2)]} for x, y in spots]


def _across_largest_room(design: Design, derived: Derived) -> list[dict]:
    rooms = [r for r in design.rooms if r.id in derived.rooms and r.enclosed]
    if not rooms:
        return []
    room = max(rooms, key=lambda r: derived.rooms[r.id].polygon.area)
    a, b = beam_line(derived.rooms[room.id].polygon.bounds)
    return [{"level": room.level, "start": list(a), "end": list(b)}]


def _in_rooms(brick: Brick, design: Design, ground: str, near_room: str | None, slot: int, room_kind: str | None) -> list[dict]:
    enclosed = [r for r in design.rooms if r.enclosed and (not brick.rules.ground_only or r.level == ground)]
    if room_kind:
        enclosed = [r for r in enclosed if r.kind == room_kind] or enclosed
    # Rules name where a brick usually goes; with no such room, any room will do (the rule check warns).
    rooms = [r for r in enclosed if not brick.rules.rooms or r.kind in brick.rules.rooms] or enclosed
    rooms.sort(key=lambda r: (r.id != near_room, r.kind not in PLANT_ROOMS, -r.area_m2))
    if brick.host == "ceiling":
        return [{"room": room.id} for room in rooms]
    sides = [("N", "E", "S", "W")[(slot + i) % 4] for i in range(4)]
    out: list[dict] = []
    for room in rooms:
        for at in (0.5, 0.15, 0.85):
            out += [{"room": room.id, "side": side, "at": at} for side in sides]
        out.append({"room": room.id, "side": "center"})
    return out
