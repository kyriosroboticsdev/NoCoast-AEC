"""Deterministic layout solver: Program → BuildingSpec.

Rooms are placed on a two-row grid per storey (front row on the south side, back
row on the north), with a spine wall between the rows and cross walls between
bays. The same Program always produces the same spec, and element ids are derived
from position (L1-wall-S, L2-space-kitchen …) so a redesign that keeps a room
keeps its id — and therefore its IFC GlobalId.
"""

from __future__ import annotations

import math
import re

from schemas.bim import BuildingSpec, Column, Door, Level, Roof, Slab, Space, Wall, Window
from schemas.program import Program, Room

EXT_T, INT_T = 0.3, 0.12  # wall thicknesses
ROW_DEPTH = 4.5
MIN_BAY = 4.0
MAX_BAY = 9.0
GARAGE_W, GARAGE_D = 6.5, 6.5
PUBLIC_KINDS = {"living", "kitchen", "dining", "office", "hall", "other"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _rows(rooms: list[Room]) -> tuple[list[Room], list[Room]]:
    """Public rooms face the street (front row); private rooms go to the back."""
    front = [r for r in rooms if r.kind in PUBLIC_KINDS]
    back = [r for r in rooms if r.kind not in PUBLIC_KINDS]
    cols = max(1, math.ceil(len(rooms) / 2))
    # Rebalance so both rows have at most `cols` rooms.
    while len(front) > cols:
        back.append(front.pop())
    while len(back) > cols:
        front.append(back.pop())
    return front, back


def _bay_width(rooms: list[Room]) -> float:
    areas = [r.area for r in rooms if r.area]
    if not areas:
        return MIN_BAY
    return min(MAX_BAY, max(MIN_BAY, sum(areas) / len(areas) / ROW_DEPTH))


def solve(program: Program) -> BuildingSpec:
    per_level: list[list[Room]] = [[] for _ in range(program.storeys)]
    for room in program.rooms:
        if room.kind == "garage":
            continue  # the garage is a feature, not a grid room
        per_level[room.index].append(room)
    for i, rooms in enumerate(per_level):
        if not rooms:
            rooms.append(Room(name="Room" if i else "Living Room", level=f"L{i + 1}", kind="living" if not i else "other"))

    layouts = [(_rows(rooms)) for rooms in per_level]
    cols_per_level = [max(len(f), len(b), 1) for f, b in layouts]
    cols = max(cols_per_level)
    if program.footprint:
        W, D = program.footprint
    else:
        W = cols * max(_bay_width(rooms) for rooms in per_level)
        D = 2 * ROW_DEPTH

    levels = [Level(id=f"L{i + 1}", name="Ground Floor" if i == 0 else f"Level {i + 1}", height=program.storey_height)
              for i in range(program.storeys)]
    els: list = []
    win_w, win_h = (2.0, 1.6) if program.bright else (1.2, 1.2)
    outline = [(0, 0), (W, 0), (W, D), (0, D)]
    e = EXT_T / 2
    garage = program.garage or any(r.kind == "garage" for r in program.rooms)

    for li, (front, back) in enumerate(layouts):
        L = levels[li].id
        cols_here = cols_per_level[li]
        bay = W / cols_here
        front_names = [r.name for r in front] + ["Hall"] * (cols_here - len(front))
        back_names = [r.name for r in back] + ["Hall"] * (cols_here - len(back))

        els.append(Slab(id=f"{L}-floor", name=f"{levels[li].name} slab", level=L, outline=outline))
        ext = {
            "S": Wall(id=f"{L}-wall-S", name="South wall", level=L, start=(-e, 0), end=(W + e, 0), thickness=EXT_T, external=True),
            "E": Wall(id=f"{L}-wall-E", name="East wall", level=L, start=(W, 0), end=(W, D), thickness=EXT_T, external=True),
            "N": Wall(id=f"{L}-wall-N", name="North wall", level=L, start=(W + e, D), end=(-e, D), thickness=EXT_T, external=True),
            "W": Wall(id=f"{L}-wall-W", name="West wall", level=L, start=(0, D), end=(0, 0), thickness=EXT_T, external=True),
        }
        els += ext.values()

        spine = Wall(id=f"{L}-wall-spine", name="Spine wall", level=L, start=(0, D / 2), end=(W, D / 2), thickness=INT_T)
        els.append(spine)
        for c in range(cols_here):
            els.append(Door(id=f"{L}-door-spine-{c + 1}", wall=spine.id, offset=c * bay + bay / 2 - 0.45))
        for c in range(1, cols_here):
            x = c * bay
            cross = Wall(id=f"{L}-wall-x{c}", name="Partition", level=L, start=(x, 0), end=(x, D), thickness=INT_T)
            els.append(cross)
            els.append(Door(id=f"{L}-door-x{c}", wall=cross.id, offset=D / 4 - 0.45))

        hall_n = 0
        for c in range(cols_here):
            x0, x1 = c * bay, (c + 1) * bay
            for name, y0, y1 in ((front_names[c], 0, D / 2), (back_names[c], D / 2, D)):
                sid = slug(name)
                if name == "Hall":
                    hall_n += 1
                    sid = f"hall-{hall_n}"
                els.append(Space(id=f"{L}-space-{sid}", name=name, level=L,
                                 outline=[(x0 + 0.1, y0 + 0.1), (x1 - 0.1, y0 + 0.1), (x1 - 0.1, y1 - 0.1), (x0 + 0.1, y1 - 0.1)]))

            w = min(win_w, bay - 1.2)
            if w < 0.6:
                continue  # bay too narrow for a window
            if li == 0 and c == 0:
                els.append(Door(id=f"{L}-door-entrance", name="Entrance", wall=ext["S"].id, offset=e + 0.6, width=1.0))
                if bay - 2.2 >= w:
                    els.append(Window(id=f"{L}-win-S{c + 1}", wall=ext["S"].id, offset=e + x1 - 0.5 - w, width=w, height=win_h))
            else:
                els.append(Window(id=f"{L}-win-S{c + 1}", wall=ext["S"].id, offset=e + (x0 + x1 - w) / 2, width=w, height=win_h))
            # The north wall runs east→west, so offsets are measured from x = W.
            els.append(Window(id=f"{L}-win-N{c + 1}", wall=ext["N"].id, offset=e + W - (x0 + x1 + w) / 2, width=w, height=win_h))

        side_w = min(win_w, D / 2 - 1.2)
        for side, wall in (("W", ext["W"]), ("E", ext["E"])):
            if side_w < 0.6 or (side == "E" and garage and li == 0):
                continue  # the garage covers the east wall on the ground floor
            for r in range(2):
                els.append(Window(id=f"{L}-win-{side}{r + 1}", wall=wall.id, offset=r * D / 2 + (D / 2 - side_w) / 2, width=side_w, height=win_h))

    top = levels[-1].id
    els.append(Roof(id="roof", name="Roof", level=top, outline=[(-e, -e), (W + e, -e), (W + e, D + e), (-e, D + e)]))

    if garage:
        L, gx = "L1", W + GARAGE_W
        els += [
            Slab(id="garage-floor", name="Garage slab", level=L, outline=[(W, 0), (gx, 0), (gx, GARAGE_D), (W, GARAGE_D)]),
            Wall(id="garage-wall-S", name="Garage front wall", level=L, start=(W + e, 0), end=(gx + e, 0), thickness=EXT_T, external=True),
            Wall(id="garage-wall-E", name="Garage side wall", level=L, start=(gx, 0), end=(gx, GARAGE_D), thickness=EXT_T, external=True),
            Wall(id="garage-wall-N", name="Garage back wall", level=L, start=(gx + e, GARAGE_D), end=(W + e, GARAGE_D), thickness=EXT_T, external=True),
            Door(id="garage-door", name="Garage door", wall="garage-wall-S", offset=(GARAGE_W - 5.0) / 2, width=5.0, height=2.4),
            Door(id="garage-door-house", name="Garage to house", wall="L1-wall-E", offset=D / 4 - 0.45),
            Window(id="garage-win-E", wall="garage-wall-E", offset=GARAGE_D / 2 - 0.6),
            Space(id="L1-space-garage", name="Garage", level=L,
                  outline=[(W + 0.2, 0.2), (gx - 0.2, 0.2), (gx - 0.2, GARAGE_D - 0.2), (W + 0.2, GARAGE_D - 0.2)]),
            Roof(id="garage-roof", name="Garage roof", level=L,
                 outline=[(W + e, -e), (gx + e, -e), (gx + e, GARAGE_D + e), (W + e, GARAGE_D + e)]),
        ]

    if program.porch:
        L, pd = "L1", 2.4
        xs = [0.3 + i * (W - 0.6) / 3 for i in range(4)]
        els += [Column(id=f"porch-col-{i + 1}", name="Porch column", level=L, position=(x, -pd), width=0.3, depth=0.3) for i, x in enumerate(xs)]
        els += [
            Slab(id="porch-deck", name="Porch deck", level=L, outline=[(0, -pd - 0.3), (W, -pd - 0.3), (W, -e), (0, -e)], thickness=0.15),
            Roof(id="porch-roof", name="Porch roof", level=L, outline=[(0, -pd - 0.3), (W, -pd - 0.3), (W, -e), (0, -e)], thickness=0.2),
        ]

    return BuildingSpec(
        building={"name": program.name, "description": program.description or f"{program.storeys}-storey rectangular building"},
        levels=levels,
        elements=els,
    )
