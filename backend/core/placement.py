"""Finding a spot for a brick: candidate placements from its mount and tags, best first, and the first of
them that applies, derives and clashes with nothing.

Used wherever a placement has to be proposed rather than checked — the mock and template planner
placing bricks a prompt names, and coordination suggesting the brick that would fix an issue. Tags
steer it: "roof" puts a brick on the roof, "outdoor" outside the building, and a tag naming a room kind
("kitchen", "utility") prefers rooms of that kind.
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

MAX_TRIES = 40
SIDES = ("N", "E", "S", "W")


def candidates(brick: Brick, design: Design, derived: Derived, near_room: str | None = None, slot: int = 0,
               room_kind: str | None = None) -> list[dict]:
    """Arguments of `brick` steps that would place it sensibly, best first. `slot` spreads several bricks
    of a kind over different sides; `near_room` / `room_kind` prefer a room."""
    ground = design.ground_level().id
    footprint = derived.footprints.get(ground) or next((p for p in derived.footprints.values() if p), [])
    bounds = unary_union(footprint).bounds if footprint else None
    tags = set(brick.tags)
    outdoor = "outdoor" in tags or not design.rooms
    match brick.mount:
        case "path":
            if outdoor:
                return _around(bounds, slot) if bounds else []
            return _across_largest_room(design, derived)
        case "rest" | "fix" | "hang":
            if "roof" in tags:
                return [{"ref": "roof"}]
            if outdoor:
                return _beside(slot) if bounds else []
            return _in_rooms(brick, design, near_room, slot, room_kind)
        case _:
            assert_never(brick.mount)


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
    return [{"ref": "site", "start": [round(a[0], 2), round(a[1], 2)], "end": [round(b[0], 2), round(b[1], 2)]} for a, b in lines]


def _beside(slot: int) -> list[dict]:
    """Against each outer face of the building, a quarter and three quarters along it."""
    sides = [SIDES[(slot + i) % 4] for i in range(4)]
    return [{"ref": "site", "side": side, "at": at} for at in (0.25, 0.75) for side in sides]


def _across_largest_room(design: Design, derived: Derived) -> list[dict]:
    rooms = [r for r in design.rooms if r.id in derived.rooms and r.enclosed]
    if not rooms:
        return []
    room = max(rooms, key=lambda r: derived.rooms[r.id].polygon.area)
    a, b = beam_line(derived.rooms[room.id].polygon.bounds)
    return [{"ref": room.id, "start": list(a), "end": list(b)}]


def _in_rooms(brick: Brick, design: Design, near_room: str | None, slot: int, room_kind: str | None) -> list[dict]:
    rooms = [r for r in design.rooms if r.enclosed]
    if room_kind:
        rooms = [r for r in rooms if r.kind == room_kind] or rooms
    tags = set(brick.tags)
    rooms.sort(key=lambda r: (r.id != near_room, r.kind not in tags, -r.area_m2))
    if brick.mount == "hang":
        return [{"ref": room.id} for room in rooms]
    sides = [SIDES[(slot + i) % 4] for i in range(4)]
    out: list[dict] = []
    for room in rooms:
        for at in (0.5, 0.15, 0.85):
            out += [{"ref": room.id, "side": side, "at": at} for side in sides]
        if brick.mount == "rest":
            out.append({"ref": room.id})
    return out
