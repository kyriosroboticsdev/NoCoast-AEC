"""Rule-based planner: reads counts and keywords from the prompt into a Program,
then hands it to the layout solver. No AI — it proves the prompt → program →
spec → IFC → viewer pipeline, backs the mock LLM, and is the fallback when an
LLM is unavailable.
"""

from __future__ import annotations

import re

from agents.base import PlanResult
from schemas.program import MAX_STOREYS, Program, Room
from solver.layout import solve

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


def _num(word: str) -> int:
    return int(word) if word.isdigit() else NUMBERS[word]


def _count(text: str, noun: str) -> int | None:
    m = re.search(r"\b" + NUM + r"[\s-]+" + noun, text)
    return _num(m.group(1)) if m else None


def parse_program(prompt: str) -> Program:
    """Regex interpretation of a prompt. Deliberately simple; an LLM does this better."""
    text = prompt.lower()
    notes: list[str] = []

    storeys = _count(text, r"(stor(e)?y|stories|storeys|floors?|levels?)") or 1
    storeys = max(1, min(storeys, MAX_STOREYS))
    notes.append(f"{storeys} storey{'s' if storeys > 1 else ''}")

    rooms = _assign_rooms(text, storeys, notes)
    garage = "garage" in text
    porch = bool(re.search(r"porch|columns?|pillars?|veranda", text))
    bright = bool(re.search(r"natural light|lots of windows|large windows|bright|glass", text))

    footprint = None
    size = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|by|×)\s*(\d+(?:\.\d+)?)\s*(m|meters?|metres?|ft|feet|foot|')?", text)
    if size:
        scale = FT if (size.group(3) or "").startswith(("f", "'")) else 1.0
        footprint = (float(size.group(1)) * scale, float(size.group(2)) * scale)
        notes.append(f"footprint {footprint[0]:.1f} × {footprint[1]:.1f} m from prompt")

    if re.search(r"gable|pitched|hip(ped)?\s*roof|sloped", text):
        notes.append("only flat roofs are supported so far — used a flat roof")
    if garage:
        notes.append("attached single garage on the east side")
    if porch:
        notes.append("front porch with columns")
    if bright:
        notes.append("larger windows for natural light")

    return Program(name="Generated House", description=f"{storeys}-storey rectangular house", storeys=storeys,
                   rooms=rooms, footprint=footprint, garage=garage, porch=porch, bright=bright, notes=notes)


def _assign_rooms(text: str, storeys: int, notes: list[str]) -> list[Room]:
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
        notes.append("no ground-floor rooms named — added living room and kitchen")
    for i in range(1, storeys):
        if not floors[i]:
            floors[i] = [("Bedroom 1", "bedroom"), ("Bedroom 2", "bedroom")] if i == 1 else [("Room", "other")]
    # Number bedrooms uniquely across the whole house.
    k = 0
    for rooms in floors:
        for j, (r, kind) in enumerate(rooms):
            if kind == "bedroom":
                k += 1
                rooms[j] = (f"Bedroom {k}", kind)
    for i, rooms in enumerate(floors):
        notes.append(f"level {i + 1}: {', '.join(r for r, _ in rooms)}")
    return [Room(name=r, level=f"L{i + 1}", kind=kind) for i, rooms in enumerate(floors) for r, kind in rooms]


class TemplatePlanner:
    name = "template"

    def plan(self, prompt: str) -> PlanResult:
        program = parse_program(prompt)
        return PlanResult(spec=solve(program), planner=self.name, program=program, notes=program.notes)
