"""Rule-based planner: reads counts and keywords from the prompt and lays out a
rectangular house on a two-row room grid. No AI — it exists to prove the
prompt â†’ spec â†’ IFC â†’ viewer pipeline, and as the fallback when an LLM fails.
"""

from __future__ import annotations

import math
import re

from agents.base import PlanResult
from agents.progress import NO_PROGRESS, Progress
from schemas.bim import BuildingSpec, Column, Door, Level, Roof, Slab, Space, Wall, Window

NUMBERS = {"one": 1, "a": 1, "an": 1, "single": 1, "two": 2, "double": 2, "three": 3, "four": 4,
           "five": 5, "six": 6, "seven": 7, "eight": 8}
ORDINALS = {"first": 0, "ground": 0, "1st": 0, "lower": 0, "second": 1, "2nd": 1, "upper": -1,
            "upstairs": -1, "top": -1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3}
ROOM_WORDS = [  # (regex, display name, public room?)
    (r"living\s*rooms?|lounge|family\s*rooms?", "Living Room", True),
    (r"kitchens?", "Kitchen", True),
    (r"dining(\s*rooms?)?", "Dining Room", True),
    (r"offices?|stud(y|ies)", "Office", True),
    (r"bath(room)?s?", "Bathroom", False),
    (r"bed\s*rooms?", "Bedroom", False),
]
NUM = r"(\d+|" + "|".join(NUMBERS) + r")"

EXT_T, INT_T = 0.3, 0.12  # wall thicknesses
LEVEL_H = 3.0
ROW_DEPTH = 4.5
MIN_BAY = 4.0
GARAGE_W, GARAGE_D = 6.5, 6.5
FT = 0.3048


def _num(word: str) -> int:
    return int(word) if word.isdigit() else NUMBERS[word]


def _count(text: str, noun: str) -> int | None:
    m = re.search(r"\b" + NUM + r"[\s-]+" + noun, text)
    return _num(m.group(1)) if m else None


class TemplatePlanner:
    name = "template"

    def plan(self, prompt: str, progress: Progress = NO_PROGRESS) -> PlanResult:
        with progress.step("Reading the prompt", phase="plan", detail="rule-based: keywords and counts") as read:
            notes, floors, width, depth, garage, porch, bright = self._interpret(prompt)
            for n in notes:
                progress.note(n[0].upper() + n[1:], phase="plan", parent=read)
            read.detail = f"{len(notes)} findings"

        with progress.step("Laying out the floor plan", phase="plan") as lay:
            spec = self._layout(floors, width, depth, garage, porch, bright)
            for level, rooms in zip(spec.levels, floors):
                mine = [e for e in spec.elements if getattr(e, "level", None) == level.id]
                walls = sum(e.type == "wall" for e in mine)
                progress.note(f"{level.name}: {len(rooms)} rooms on a {math.ceil(len(rooms) / 2)} × 2 grid",
                              phase="plan", parent=lay, detail=f"{walls} walls, {', '.join(rooms)}")
            lay.detail = f"{width:.1f} × {depth:.1f} m footprint · {len(spec.levels)} levels · {len(spec.elements)} elements"
        return PlanResult(spec=spec, planner=self.name, notes=notes)

    def _interpret(self, prompt: str):
        text = prompt.lower()
        notes: list[str] = []

        stories = _count(text, r"(stor(e)?y|stories|storeys|floors?|levels?)") or 1
        stories = max(1, min(stories, 5))
        notes.append(f"{stories} storey{'s' if stories > 1 else ''}")

        floors = self._assign_rooms(text, stories, notes)
        garage = "garage" in text
        porch = bool(re.search(r"porch|columns?|pillars?|veranda", text))
        bright = bool(re.search(r"natural light|lots of windows|large windows|bright|glass", text))

        cols = max(math.ceil(len(rooms) / 2) for rooms in floors)
        width, depth = cols * MIN_BAY, 2 * ROW_DEPTH
        size = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|by|×)\s*(\d+(?:\.\d+)?)\s*(m|meters?|metres?|ft|feet|foot|')?", text)
        if size:
            scale = FT if (size.group(3) or "").startswith(("f", "'")) else 1.0
            width, depth = float(size.group(1)) * scale, float(size.group(2)) * scale
            notes.append(f"footprint {width:.1f} × {depth:.1f} m from prompt")
        else:
            notes.append(f"footprint {width:.1f} × {depth:.1f} m sized to fit rooms")

        if re.search(r"gable|pitched|hip(ped)?\s*roof|sloped", text):
            notes.append("only flat roofs are supported so far — used a flat roof")

        if garage:
            notes.append("attached single garage on the east side")
        if porch:
            notes.append("front porch with columns")
        if bright:
            notes.append("larger windows for natural light")
        return notes, floors, width, depth, garage, porch, bright

    # --- interpretation -------------------------------------------------

    def _assign_rooms(self, text: str, stories: int, notes: list[str]) -> list[list[str]]:
        floors: list[list[str]] = [[] for _ in range(stories)]
        unplaced: list[str] = []
        for sentence in re.split(r"[.;\n]", text):
            m = re.search(r"\b(" + "|".join(ORDINALS) + r")\s+(floor|stor(e)?y|level)|\b(upstairs|downstairs)\b", sentence)
            target = None
            if m:
                word = m.group(1) or m.group(4)
                target = 0 if word == "downstairs" else ORDINALS[word]
                target = stories - 1 if target == -1 else min(target, stories - 1)
            for pattern, name, _ in ROOM_WORDS:
                for hit in re.finditer(r"(?:\b" + NUM + r"[\s-]+)?\b(?:" + pattern + r")\b", sentence):
                    n = _num(hit.group(1)) if hit.group(1) else 1
                    rooms = [f"{name} {i + 1}" if n > 1 or name == "Bedroom" else name for i in range(n)]
                    seen = {r for f in floors for r in f} | set(unplaced)
                    rooms = [r for r in rooms if r.startswith("Bedroom") or r not in seen]
                    (floors[target] if target is not None else unplaced).extend(rooms)

        for room in unplaced:  # public rooms downstairs, private rooms upstairs
            public = next(p for pat, name, p in ROOM_WORDS if room.startswith(name))
            if public or stories == 1:
                floors[0].append(room)
            else:
                floors[min(range(1, stories), key=lambda i: len(floors[i]))].append(room)

        if not floors[0]:
            floors[0] = ["Living Room", "Kitchen"]
            notes.append("no ground-floor rooms named — added living room and kitchen")
        for i in range(1, stories):
            if not floors[i]:
                floors[i] = ["Bedroom 1", "Bedroom 2"] if i == 1 else ["Room"]
        # Number bedrooms uniquely across the whole house.
        k = 0
        for rooms in floors:
            for j, r in enumerate(rooms):
                if r.startswith("Bedroom"):
                    k += 1
                    rooms[j] = f"Bedroom {k}"
        for i, rooms in enumerate(floors):
            notes.append(f"level {i + 1}: {', '.join(rooms)}")
        return floors

    # --- geometry -------------------------------------------------------

    def _layout(self, floors, W, D, garage, porch, bright) -> BuildingSpec:
        levels = [Level(id=f"L{i + 1}", name="Ground Floor" if i == 0 else f"Level {i + 1}", height=LEVEL_H)
                  for i in range(len(floors))]
        els: list = []
        win_w, win_h = (2.0, 1.6) if bright else (1.2, 1.2)
        outline = [(0, 0), (W, 0), (W, D), (0, D)]
        e = EXT_T / 2

        for li, rooms in enumerate(floors):
            L = levels[li].id
            cols = math.ceil(len(rooms) / 2)
            bay = W / cols
            front, back = rooms[:cols], rooms[cols:]
            back += ["Hall"] * (cols - len(back))

            els.append(Slab(id=f"{L}-floor", name=f"{levels[li].name} slab", level=L, outline=outline))
            # Exterior walls: front/back run corner-to-corner past the side walls.
            ext = {
                "S": Wall(id=f"{L}-wall-S", name="South wall", level=L, start=(-e, 0), end=(W + e, 0), thickness=EXT_T, external=True),
                "E": Wall(id=f"{L}-wall-E", name="East wall", level=L, start=(W, 0), end=(W, D), thickness=EXT_T, external=True),
                "N": Wall(id=f"{L}-wall-N", name="North wall", level=L, start=(W + e, D), end=(-e, D), thickness=EXT_T, external=True),
                "W": Wall(id=f"{L}-wall-W", name="West wall", level=L, start=(0, D), end=(0, 0), thickness=EXT_T, external=True),
            }
            els += ext.values()

            # Interior: one spine wall between rows, cross walls between bays.
            spine = Wall(id=f"{L}-wall-spine", name="Spine wall", level=L, start=(0, D / 2), end=(W, D / 2), thickness=INT_T)
            els.append(spine)
            for c in range(cols):
                els.append(Door(id=f"{L}-door-spine-{c + 1}", wall=spine.id, offset=c * bay + bay / 2 - 0.45))
            for c in range(1, cols):
                x = c * bay
                cross = Wall(id=f"{L}-wall-x{c}", name="Partition", level=L, start=(x, 0), end=(x, D), thickness=INT_T)
                els.append(cross)
                els.append(Door(id=f"{L}-door-x{c}", wall=cross.id, offset=D / 4 - 0.45))

            for c in range(cols):
                x0, x1 = c * bay, (c + 1) * bay
                for name, y0, y1 in ((front[c], 0, D / 2), (back[c], D / 2, D)):
                    els.append(Space(id=f"{L}-space-{name.lower().replace(' ', '-')}", name=name, level=L,
                                     outline=[(x0 + 0.1, y0 + 0.1), (x1 - 0.1, y0 + 0.1), (x1 - 0.1, y1 - 0.1), (x0 + 0.1, y1 - 0.1)]))

                # Front (south) wall: entrance door in the first ground-floor bay, window in each bay.
                w = min(win_w, bay - 1.2)
                if w < 0.6:
                    continue  # bay too narrow for a window
                if li == 0 and c == 0:
                    els.append(Door(id=f"{L}-door-entrance", name="Entrance", wall=ext["S"].id, offset=e + 0.6, width=1.0))
                    if bay - 2.2 >= w:
                        els.append(Window(id=f"{L}-win-S{c + 1}", wall=ext["S"].id, offset=e + x1 - 0.5 - w, width=w, height=win_h))
                else:
                    els.append(Window(id=f"{L}-win-S{c + 1}", wall=ext["S"].id, offset=e + (x0 + x1 - w) / 2, width=w, height=win_h))
                # Back (north) wall runs eastâ†’west, so offsets are measured from x = W.
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

        if porch:
            L, pd = "L1", 2.4
            xs = [0.3 + i * (W - 0.6) / 3 for i in range(4)]
            els += [Column(id=f"porch-col-{i + 1}", name="Porch column", level=L, position=(x, -pd), width=0.3, depth=0.3) for i, x in enumerate(xs)]
            els += [
                Slab(id="porch-deck", name="Porch deck", level=L, outline=[(0, -pd - 0.3), (W, -pd - 0.3), (W, -e), (0, -e)], thickness=0.15),
                Roof(id="porch-roof", name="Porch roof", level=L, outline=[(0, -pd - 0.3), (W, -pd - 0.3), (W, -e), (0, -e)], thickness=0.2),
            ]

        return BuildingSpec(
            building={"name": "Generated House", "description": f"{len(floors)}-storey rectangular house"},
            levels=levels,
            elements=els,
        )
