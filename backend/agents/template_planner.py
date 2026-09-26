"""Rule-based planner: reads counts and keywords from the prompt and lays the rooms out
itself, producing the same build steps a language model would. No AI — it proves the
steps → design → spec → IFC → viewer pipeline, backs the mock LLM, and is the
fallback when an LLM is unavailable.
"""

from __future__ import annotations

import re

from agents.base import PlanResult
from core.derive import DesignError, analyze
from schemas.design import Design, LevelDef, RoomDef, slug
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
    if re.search(r"\bpool\b|elevator|lift\b", text):
        reqs.append(Requirement(text="pool/elevator", kind="other", supported=False))
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
        steps.append({"step": "layout", "level": level, "rooms": [{"name": r.name, "kind": r.kind, "rect": list(r.rect)} for r in defs]})
    m = re.search(r"(gable|pitched|hip(ped)?)\s*roof", text)
    if m:
        steps.append({"step": "roof", "kind": {"pitched": "gable", "hipped": "hip"}.get(m.group(1), m.group(1))})
    # Doors: each room to the hall of its storey if adjacent, else to its first neighbour.
    derived = analyze(design)
    for level in level_ids:
        hall = "hall" if level == "L1" else f"landing-{level.lower()}"
        for r in design.rooms_on(level):
            if r.id == hall:
                continue
            info = derived.rooms[r.id]
            to = hall if hall in info.neighbours else (info.neighbours[0] if info.neighbours else None)
            if to:
                steps.append({"step": "door", "room": r.id, "to": to})
        if level == "L1":
            side = "S" if "S" in derived.rooms[hall].sides else derived.rooms[hall].sides[0]
            steps.append({"step": "door", "room": hall, "to": "outside", "side": side})
    big = bool(re.search(r"natural light|lots of windows|large windows|bright|glass", text))
    for r in design.rooms:
        sides = derived.rooms[r.id].sides
        if r.id == "hall" and len(sides) > 1:
            sides = sides[1:]  # the entrance door is on the first exterior side
        if sides and r.kind != "garage" and not design.level(r.level).below_ground:
            steps.append({"step": "window", "room": r.id, "side": sides[0], "kind": "large" if big else "standard"})
    if storeys > 1:
        steps.append({"step": "stair", "room": "hall", "side": "W"})
    if basement:
        steps.append({"step": "stair", "room": "landing-b1", "side": "W"})
    if re.search(r"porch|columns?|pillars?|veranda", text):
        steps.append({"step": "porch", "side": "S"})
    for r in design.rooms:
        for kind, side in FURNITURE.get(r.kind, []):
            steps.append({"step": "furniture", "room": r.id, "kind": kind, "side": side})
    return steps


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
