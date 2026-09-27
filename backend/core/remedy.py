"""Design steps that clear failing clauses of the code review.

`remedies(checks, spec, design)` maps each failing check id to the steps that would fix it in the
semantic design: widen an exit door, add a remote exterior exit, add or widen a stair, place WCs.
A model gets them as hints next to the clause; the offline planner applies them as they are.

Every candidate is tried against the design before it is suggested — a door that would land on a
window, or a flight too long for its wall, is skipped for the next best place — and the steps that
are kept accumulate, so the second WC knows where the first one went.
"""
from __future__ import annotations

import math
import re
from typing import Iterable

from pydantic import ValidationError
from shapely.affinity import rotate
from shapely.geometry import Polygon, box

from core.derive import DesignError, analyze
from core.review import TOILET, Model, opening_width
from schemas.bim import BuildingSpec, Fixture
from schemas.design import Design, DoorDef, RoomDef, StairDef
from schemas.steps import Step, StepError, apply_step

EXIT_LEAF = 1.8
STAIR_WIDTH = 1.2
QUIET = {"bathroom", "storage", "plant", "server", "utility", "garage", "bedroom"}
SIDES = ("N", "E", "S", "W")
COMPASS = {"N": "north", "S": "south", "E": "east", "W": "west"}
EDGE = 0.05


class _Trial:
    """The design as the suggested steps so far leave it."""

    def __init__(self, design: Design):
        self.design = design

    def first(self, candidates: Iterable[dict]) -> dict | None:
        for step in candidates:
            try:
                candidate, _ = apply_step(self.design, Step.model_validate(step))
                derived = analyze(candidate)
            except (StepError, DesignError, ValidationError, ValueError):
                continue
            if step["step"] == "furniture" and _crowded(derived.spec, step["id"]):
                continue
            self.design = candidate
            return step
        return None


def _footprint(f: Fixture) -> Polygon:
    return rotate(box(f.position[0] - f.width / 2, f.position[1] - f.depth / 2,
                      f.position[0] + f.width / 2, f.position[1] + f.depth / 2), f.rotation)


def _crowded(spec: BuildingSpec, fid: str) -> bool:
    """Whether the fixture `fid` overlaps another piece already standing on its storey."""
    pieces = [e for e in spec.elements if isinstance(e, Fixture)]
    new = next((f for f in pieces if f.id == fid), None)
    if new is None:
        return False
    shape = _footprint(new)
    return any(f.id != fid and f.level == new.level and _footprint(f).intersection(shape).area > 0.01 for f in pieces)


def _door(d: DoorDef, **change) -> dict:
    if d.wall and not d.room:
        return {"step": "door", "id": d.id, "wall": d.wall, "at": d.at, "kind": d.kind, **change}
    step = {"step": "door", "id": d.id, "room": d.room, "to": d.to, "at": d.at, "kind": d.kind}
    if d.side:
        step["side"] = d.side
    if d.near:
        step["near"] = list(d.near)
    return {**step, **change}


def _stair(s: StairDef, **change) -> dict:
    step = {"step": "stair", "id": s.id, "room": s.room, "width": s.width}
    if s.side:
        step["side"] = s.side
    if s.near:
        step["near"] = list(s.near)
    if s.to_level:
        step["to_level"] = s.to_level
    return {**step, **change}


def _centre(r: RoomDef) -> tuple[float, float]:
    x0, y0, x1, y1 = r.box
    return (x0 + x1) / 2, (y0 + y1) / 2


def _outer(room: RoomDef, box: tuple[float, float, float, float]) -> list[tuple[str, tuple[float, float]]]:
    """The sides of a room that lie on the plate's outer edge, with their midpoints."""
    x0, y0, x1, y1 = room.box
    bx0, by0, bx1, by1 = box
    edges = (("S", abs(y0 - by0), ((x0 + x1) / 2, y0)), ("N", abs(y1 - by1), ((x0 + x1) / 2, y1)),
             ("W", abs(x0 - bx0), (x0, (y0 + y1) / 2)), ("E", abs(x1 - bx1), (x1, (y0 + y1) / 2)))
    return [(side, mid) for side, gap, mid in edges if gap < EDGE]


def _plate(design: Design, level: str) -> list[RoomDef]:
    return [r for r in design.rooms if r.level == level and r.is_rect and r.enclosed]


def _box(rooms: list[RoomDef]) -> tuple[float, float, float, float]:
    boxes = [r.box for r in rooms]
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def _need(check: dict) -> int | None:
    m = re.search(r"≥\s*(\d+)", check.get("target", ""))
    return int(m.group(1)) if m else None


def _need_width(check: dict) -> float:
    """The total exit width a door-width clause asks for, in metres (0 when it states none)."""
    m = re.search(r"≥\s*([\d,]+) mm total", check.get("target", ""))
    return int(m.group(1).replace(",", "")) / 1000 if m else 0.0


def _exits(design: Design, taken: list[tuple[float, float]]) -> Iterable[dict]:
    """New ground-floor exits, best first: the outer side furthest from the exits already there, a pair of
    leaves mid-wall, then nearer the corners, then a single leaf."""
    ground = design.levels[0].id if design.levels else "L1"
    rooms = _plate(design, ground)
    if not rooms:
        return
    box = _box(rooms)
    places = sorted(((min((math.dist(mid, p) for p in taken), default=0.0), r, side)
                     for r in rooms if r.kind not in QUIET for side, mid in _outer(r, box)),
                    key=lambda x: -x[0])
    for _, room, side in places:
        for kind, width in (("double", EXIT_LEAF), ("single", 1.0)):
            for at in (0.5, 0.2, 0.8):
                yield {"step": "door", "id": design.unique_id(f"door-{room.id}-exit"), "room": room.id, "to": "outside",
                       "side": side, "at": at, "kind": kind, "width": width,
                       "why": f"a second, remote way out on the {COMPASS[side]} side, so one fire cannot block both exits"}


def _stairs(design: Design, below: str, lid: str, away: list[tuple[float, float]]) -> Iterable[dict]:
    """A flight from `below` up to `lid`, in the room furthest from the stairs already there."""
    rooms = [r for r in _plate(design, below) if r.kind not in QUIET]
    if away:
        rooms.sort(key=lambda r: -min(math.dist(_centre(r), p) for p in away))
    else:
        rooms.sort(key=lambda r: (r.kind != "hall", -r.area_m2))
    why = "a second, remote exit stair" if away else f"a stair up to {lid} so the storey has a way out"
    for room in rooms:
        x0, y0, x1, y1 = room.box
        for side in sorted(SIDES, key=lambda s: -(x1 - x0 if s in "NS" else y1 - y0)):
            yield {"step": "stair", "id": design.unique_id(f"stair-{room.id}-{lid.lower()}"), "room": room.id,
                   "side": side, "to_level": lid, "width": STAIR_WIDTH, "why": why}


def _toilets(design: Design) -> Iterable[dict]:
    baths = [r for r in design.rooms if r.kind == "bathroom" and r.placed]
    used = {(f.room, f.side, round(f.at, 2)) for f in design.fixtures}
    for at in (0.5, 0.2, 0.8):
        for side in SIDES:
            for room in baths:
                if (room.id, side, at) in used:
                    continue
                yield {"step": "furniture", "id": design.unique_id(f"toilet-{room.id}-{side.lower()}"), "room": room.id,
                       "kind": "toilet", "side": side, "at": at,
                       "why": "brings the water closet count up to the plumbing table for this occupant load"}


def remedies(checks: list[dict], spec: BuildingSpec, design: Design) -> dict[str, list[dict]]:
    m = Model(spec, design)
    order = [l.id for l in design.levels]
    doors = {d.id: d for d in design.doors}
    stairs = {s.id: s for s in design.stairs}
    taken = [m.point(d) for d in m.exterior_doors(order[0] if order else None)]
    trial = _Trial(design)
    out: dict[str, list[dict]] = {}
    for c in checks:
        if c["status"] != "fail":
            continue
        cid, steps = c["id"], []
        if cid in ("egress.door-width", "access.entrance"):
            widened = set()
            for e in c["elements"]:
                if e in doors:
                    step = trial.first([_door(doors[e], kind="double", width=EXIT_LEAF,
                                              why="a pair of leaves so the exit clears the width its occupant load needs")])
                    steps.append(step)
                    if step:
                        widened.add(e)
            need = _need_width(c)
            ext = m.exterior_doors(order[0] if order else None)
            capacity = sum(EXIT_LEAF - 0.1 if d.id in widened else opening_width(d) for d in ext)
            while need and capacity < need - 1e-6:
                step = trial.first(_exits(trial.design, taken))
                if not step:
                    break
                steps.append(step)
                taken.append(_centre(trial.design.room(step["room"])))
                capacity += step["width"] - (0.1 if step["kind"] == "double" else 0.09)
        elif cid == "egress.exits":
            for _ in range(max(0, (_need(c) or 0) - len(taken))):
                step = trial.first(_exits(trial.design, taken))
                steps.append(step)
                if step:
                    room = trial.design.room(step["room"])
                    taken.append(_centre(room))
        elif cid.startswith("egress.stairs."):
            lid = cid.rsplit(".", 1)[1]
            if lid in order and order.index(lid) > 0:
                existing = [tuple(s.position) for s in m.down(lid)]
                steps.append(trial.first(_stairs(trial.design, order[order.index(lid) - 1], lid, existing)))
        elif cid.startswith("stairs."):
            sid = cid.split(".", 1)[1]
            if sid in stairs and "width" in c["detail"]:
                steps.append(trial.first([_stair(stairs[sid], width=max(STAIR_WIDTH, stairs[sid].width),
                                                 why="widened to the clear width the storeys above need")]))
        elif cid == "plumbing.wc":
            placed = sum(1 for f in m.fixtures if f.kind == "toilet") + sum(1 for a in m.assets if TOILET.search(a.brick))
            for _ in range(max(0, (_need(c) or 0) - placed)):
                steps.append(trial.first(_toilets(trial.design)))
        steps = [s for s in steps if s]
        if steps:
            out[cid] = steps
    return out
