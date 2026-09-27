"""Rule-based planner: reads counts and keywords from the prompt and lays the rooms out
itself, producing the same build steps a language model would. No AI — it proves the
steps → design → spec → IFC → viewer pipeline, backs the mock LLM, and is the
fallback when an LLM is unavailable.
"""

from __future__ import annotations

import re

from agents import shapes
from agents.base import PlanResult
from agents.brick_words import mentioned_bricks
from bricks import library
from core.assembly import candidates, first_fit
from core.derive import DesignError, Derived, analyze
from schemas.design import Design, Edge, LevelDef, RoomDef, slug
from schemas.requirements import Requirement
from schemas.steps import Step, StepError, apply_step
from solver.layout import place_rooms

NUMBERS = {"one": 1, "a": 1, "an": 1, "single": 1, "two": 2, "double": 2, "three": 3, "four": 4,
           "five": 5, "six": 6, "seven": 7, "eight": 8}
ORDINALS = {"first": 0, "ground": 0, "1st": 0, "lower": 0, "second": 1, "2nd": 1, "upper": -1,
            "upstairs": -1, "top": -1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3}
ROOM_WORDS = [  # (regex, display name, kind)
    (r"living\s*rooms?|lounge|family\s*rooms?", "Living Room", "living"),
    (r"kitchens?", "Kitchen", "kitchen"),
    (r"dining(\s*rooms?)?", "Dining Room", "dining"),
    (r"offices?|stud(y|ies)", "Office", "office"),
    (r"bath(room)?s?", "Bathroom", "bathroom"),
    (r"bed\s*rooms?", "Bedroom", "bedroom"),
]
NUM = r"(\d+|" + "|".join(NUMBERS) + r")"
FT = 0.3048
FURNITURE = {  # kind -> [(fixture kind, side)]
    "bedroom": [("double_bed", "N"), ("wardrobe", "E")], "living": [("sofa", "W"), ("coffee_table", "center")],
    "kitchen": [("kitchen_counter", "N"), ("fridge", "E"), ("oven", "N"), ("sink", "N")], "dining": [("dining_table", "center")],
    "bathroom": [("toilet", "N"), ("washbasin", "E"), ("shower", "W")], "office": [("desk", "N"), ("chair", "center")],
    "garage": [("car", "center")],
}


def _num(word: str) -> int:
    return int(word) if word.isdigit() else NUMBERS[word]


def _count(text: str, noun: str) -> int | None:
    m = re.search(r"\b" + NUM + r"[\s-]+" + noun, text)
    return _num(m.group(1)) if m else None


def parse_requirements(prompt: str) -> list[Requirement]:
    """The checklist the mock 'extracts': storeys, rooms per kind, features, roof."""
    text = prompt.lower()
    reqs: list[Requirement] = []
    storeys = _count(text, r"(stor(e)?y|stories|storeys|floors?|levels?)")
    if storeys:
        reqs.append(Requirement(text=f"{storeys} storeys", kind="storeys", value=storeys))
    for pattern, name, kind in ROOM_WORDS:
        for hit in re.finditer(r"(?:\b" + NUM + r"[\s-]+)?\b(?:" + pattern + r")\b", text):
            n = _num(hit.group(1)) if hit.group(1) else 1
            reqs.append(Requirement(text=f"{n} {name.lower()}{'s' if n > 1 else ''}", kind="room", room=kind, value=n))
            break
    if "garage" in text:
        reqs.append(Requirement(text="a garage", kind="feature", item="garage"))
    if re.search(r"porch|veranda", text):
        reqs.append(Requirement(text="a porch", kind="feature", item="porch"))
    if re.search(r"balcon", text):
        reqs.append(Requirement(text="a balcony", kind="feature", item="balcony"))
    m = re.search(r"(gable|pitched|hip(ped)?|flat)\s*roof", text)
    if m:
        kind = {"pitched": "gable", "hipped": "hip"}.get(m.group(1), m.group(1))
        reqs.append(Requirement(text=f"{kind} roof", kind="roof", item=kind))
    if re.search(r"basement|cellar", text):
        reqs.append(Requirement(text="a basement", kind="feature", item="basement"))
    for words, item, label in ((r"courtyard|patio|atrium", "courtyard", "a courtyard"), (r"carport", "carport", "a carport"),
                               (r"pergola|gazebo", "pergola", "a pergola"), (r"roof terrace|terrace", "terrace", "a terrace"),
                               (r"curved|rounded|bow window|round(ed)? wall", "curved wall", "a curved wall"),
                               (r"l-shaped|l shaped", "l-shaped", "an L-shaped room"), (r"garden wall|fence", "garden wall", "a garden wall"),
                               (r"\bdeck\b", "deck", "a deck")):
        if re.search(words, text):
            reqs.append(Requirement(text=label, kind="feature", item=item))
    for m in mentioned_bricks(prompt):
        name = library().get(m.brick).name.lower()
        article = "an" if name[0] in "aeiou" else "a"
        reqs.append(Requirement(text=f"{m.count} {name}s" if m.count > 1 else f"{article} {name}", kind="asset", item=m.brick, value=m.count))
    return reqs


def _assign_rooms(text: str, storeys: int) -> list[list[tuple[str, str]]]:
    floors: list[list[tuple[str, str]]] = [[] for _ in range(storeys)]
    unplaced: list[tuple[str, str]] = []
    for sentence in re.split(r"[.;\n]", text):
        m = re.search(r"\b(" + "|".join(ORDINALS) + r")\s+(floor|stor(e)?y|level)|\b(upstairs|downstairs)\b", sentence)
        target = None
        if m:
            word = m.group(1) or m.group(4)
            target = 0 if word == "downstairs" else ORDINALS[word]
            target = storeys - 1 if target == -1 else min(target, storeys - 1)
        for pattern, name, kind in ROOM_WORDS:
            for hit in re.finditer(r"(?:\b" + NUM + r"[\s-]+)?\b(?:" + pattern + r")\b", sentence):
                n = _num(hit.group(1)) if hit.group(1) else 1
                names = [f"{name} {i + 1}" if n > 1 or kind == "bedroom" else name for i in range(n)]
                seen = {r for f in floors for r, _ in f} | {r for r, _ in unplaced}
                names = [r for r in names if kind == "bedroom" or r not in seen]
                (floors[target] if target is not None else unplaced).extend((r, kind) for r in names)
    for room, kind in unplaced:  # public rooms downstairs, private rooms upstairs
        public = kind in ("living", "kitchen", "dining", "office")
        if public or storeys == 1:
            floors[0].append((room, kind))
        else:
            floors[min(range(1, storeys), key=lambda i: len(floors[i]))].append((room, kind))
    if not floors[0]:
        floors[0] = [("Living Room", "living"), ("Kitchen", "kitchen")]
    for i in range(1, storeys):
        if not floors[i]:
            floors[i] = [("Bedroom 1", "bedroom"), ("Bedroom 2", "bedroom")] if i == 1 else [("Room", "other")]
    k = 0
    for rooms in floors:
        for j, (r, kind) in enumerate(rooms):
            if kind == "bedroom":
                k += 1
                rooms[j] = (f"Bedroom {k}", kind)
    return floors


def template_steps(prompt: str) -> list[dict]:
    """Build steps for a new design, in construction order."""
    text = prompt.lower()
    storeys = max(1, min(_count(text, r"(stor(e)?y|stories|storeys|floors?|levels?)") or 1, 40))
    basement = bool(re.search(r"basement|cellar", text))
    floors = _assign_rooms(text, storeys)
    garage = "garage" in text
    steps: list[dict] = [{"step": "building", "name": "Generated House", "description": f"{storeys}-storey house" + (" with a basement" if basement else "")}]
    if basement:
        steps.append({"step": "level", "id": "B1"})
    for i in range(storeys):
        steps.append({"step": "level", "id": f"L{i + 1}"})
    # Every storey gets a hall so there is somewhere for the stair and the doors to meet.
    design = Design(levels=[])
    level_ids = (["B1"] if basement else []) + [f"L{i + 1}" for i in range(storeys)]
    if basement:
        floors = [[("Storage", "storage"), ("Utility Room", "utility")]] + floors
    for i, (level, rooms) in enumerate(zip(level_ids, floors)):
        design.levels.append(LevelDef(id=level))
        hall_id, hall_name = ("hall", "Hall") if level == "L1" else (f"landing-{level.lower()}", f"Landing {level}")
        defs = [RoomDef(id=hall_id, name=hall_name, level=level, kind="hall", area=12)]
        defs += [RoomDef(id=slug(r), name=r, level=level, kind=kind, area=18 if kind != "bathroom" else 8) for r, kind in rooms]
        if level == "L1" and garage:
            defs.append(RoomDef(id="garage", name="Garage", level=level, kind="garage"))
        rects = place_rooms([], defs)
        for r in defs:
            r.rect = rects[r.id]
            design.rooms.append(r)
        # Open-air and unwalled rooms sit against the block, not inside it.
        extras: list[RoomDef] = []
        if level == "L1" and re.search(r"carport", text):
            extras.append(RoomDef(id="carport", name="Carport", level=level, kind="carport"))
        if level == "L1" and re.search(r"courtyard|patio|atrium", text):
            extras.append(RoomDef(id="courtyard", name="Courtyard", level=level, kind="courtyard"))
        if level == level_ids[-1] and re.search(r"roof terrace|terrace", text):
            extras.append(RoomDef(id="terrace", name="Terrace", level=level, kind="terrace"))
        for i, r in enumerate(extras):
            w, dpt = (6.0, 6.0) if r.kind == "carport" else (4.0, 4.0)
            r.rect = tuple(shapes.beside(design, level, w, dpt, "E" if i == 0 else "N"))
            design.rooms.append(r)
            defs.append(r)
        # Shapes asked for by name: "L-shaped living room", "curved wall in the lounge" / "a curved living room".
        for r in defs:
            words = r.name.lower().split()[0]
            if re.search(r"l-shaped\s+(\w+\s+)?" + re.escape(words), text) or (r.kind == "living" and re.search(r"l-shaped", text) and not re.search(r"l-shaped\s+(\w+\s+)?(kitchen|bed|bath|hall|dining|office)", text)):
                poly = shapes.l_shape(design, r)
                if poly:
                    r.poly = [Edge(to=p) for p in poly]
                    r.rect = None
            elif re.search(r"(curved|rounded|round|bow window)\s+(\w+\s+)?" + re.escape(words), text) or (r.kind == "living" and re.search(r"curved|rounded|bow window", text) and not re.search(r"(curved|rounded|round)\s+(\w+\s+)?(kitchen|bed|bath|hall|dining|office)", text)):
                poly = shapes.curved_side(design, r)
                if poly:
                    r.poly = [Edge.model_validate(e) for e in poly]
                    r.rect = None
        steps.append({"step": "layout", "level": level, "rooms": [
            {"name": r.name, "kind": r.kind, **({"poly": [e.model_dump(exclude_none=True, exclude_defaults=True) for e in r.poly]} if r.poly else {"rect": list(r.rect)})}
            for r in defs]})
    m = re.search(r"(gable|pitched|hip(ped)?)\s*roof", text)
    if m:
        steps.append({"step": "roof", "kind": {"pitched": "gable", "hipped": "hip"}.get(m.group(1), m.group(1))})
    # Doors: each room to the hall of its storey if adjacent, else to its first neighbour.
    derived = analyze(design)
    for level in level_ids:
        hall = "hall" if level == "L1" else f"landing-{level.lower()}"
        for r in design.rooms_on(level):
            if r.id == hall or not r.enclosed:
                continue
            info = derived.rooms[r.id]
            to = hall if hall in info.neighbours else (info.neighbours[0] if info.neighbours else None)
            if to and (design.room(to).enclosed or design.room(to).roofed):
                steps.append({"step": "door", "room": r.id, "to": to})
        if level == "L1":
            side = "S" if "S" in derived.rooms[hall].sides else derived.rooms[hall].sides[0]
            steps.append({"step": "door", "room": hall, "to": "outside", "side": side})
    big = bool(re.search(r"natural light|lots of windows|large windows|bright|glass", text))
    for r in design.rooms:
        info = derived.rooms[r.id]
        sides = info.sides
        if r.id == "hall" and len(sides) > 1:
            sides = sides[1:]  # the entrance door is on the first exterior side
        if sides and r.kind not in ("garage", "carport", "courtyard", "terrace", "pergola") and not design.level(r.level).below_ground:
            if r.poly:  # polygons name walls by a point: the middle of the longest wall on that side
                wall = max(info.exterior[sides[0]], key=lambda w: w.length)
                steps.append({"step": "window", "room": r.id, "near": list(wall.mid), "kind": "large" if big else "standard"})
            else:
                steps.append({"step": "window", "room": r.id, "side": sides[0], "kind": "large" if big else "standard"})
    if storeys > 1:
        steps.append({"step": "stair", "room": "hall", "side": "W"})
    if basement:
        steps.append({"step": "stair", "room": "landing-b1", "side": "W"})
    if re.search(r"porch|pillars?|veranda", text):
        steps.append({"step": "porch", "side": "S"})
    for r in design.rooms:
        for kind, side in FURNITURE.get(r.kind, []):
            if r.poly and side != "center":  # against the longest wall facing that way, named by a point
                walls = [w for w in derived.rooms[r.id].walls if _facing(w, derived.rooms[r.id].polygon) == side]
                if not walls:
                    continue
                steps.append({"step": "furniture", "room": r.id, "kind": kind, "near": list(max(walls, key=lambda w: w.length).mid)})
            else:
                steps.append({"step": "furniture", "room": r.id, "kind": kind, "side": side})
    if re.search(r"pergola|gazebo", text):
        steps += shapes.pergola_steps(design)
    if re.search(r"garden wall|fence", text):
        steps += shapes.garden_wall_steps(design)
    if re.search(r"\bdeck\b", text) and not re.search(r"roof deck", text):
        steps += shapes.deck_steps(design)
    mentions = mentioned_bricks(prompt)
    if mentions:
        steps += brick_steps(mentions, run_steps(steps)[0])
    return steps


def brick_steps(mentions, design: Design) -> list[dict]:
    """A brick step for every brick the prompt names, at the first spot its rules allow that clashes with
    nothing already there (see core/assembly.py)."""
    steps: list[dict] = []
    slot = 0
    for m in mentions:
        brick = library().get(m.brick)
        for _ in range(m.count):
            derived = analyze(design)
            if brick.host == "span":
                options = [a for a in [_across_largest_room(design, derived)] if a]
            else:
                options = candidates(brick, design, derived, slot=slot)
            slot += 1
            fit = first_fit(brick, design, options)
            if fit is not None:
                steps.append({"step": "brick", "brick": brick.id, **fit[0]})
                design = fit[1]
    return steps


def _across_largest_room(design: Design, derived: Derived) -> dict | None:
    rooms = [r for r in design.rooms if r.id in derived.rooms and r.enclosed]
    if not rooms:
        return None
    room = max(rooms, key=lambda r: derived.rooms[r.id].polygon.area)
    x0, y0, x1, y1 = derived.rooms[room.id].polygon.bounds
    if x1 - x0 >= y1 - y0:
        mid = round((y0 + y1) / 2, 2)
        return {"level": room.level, "start": [round(x0 + 0.1, 2), mid], "end": [round(x1 - 0.1, 2), mid]}
    mid = round((x0 + x1) / 2, 2)
    return {"level": room.level, "start": [mid, round(y0 + 0.1, 2)], "end": [mid, round(y1 - 0.1, 2)]}


def _facing(wall, poly) -> str:
    from core.derive import compass
    ix, iy = wall.inward(poly)
    return compass(-ix, -iy)


def run_steps(steps: list[dict], design: Design | None = None) -> tuple[Design, list[str]]:
    """Apply steps to a design, skipping the ones that fail (their messages are returned)."""
    design = design or Design()
    problems: list[str] = []
    for raw in steps:
        try:
            candidate, _ = apply_step(design, Step.model_validate(raw))
            analyze(candidate)
            design = candidate
        except (StepError, DesignError, ValueError) as exc:
            problems.append(f"{raw}: {exc}")
    return design, problems


class TemplatePlanner:
    name = "template"

    def plan(self, prompt: str) -> PlanResult:
        design, problems = run_steps(template_steps(prompt))
        derived = analyze(design)
        return PlanResult(spec=derived.spec, planner=self.name, design=design, notes=derived.notes + problems)
