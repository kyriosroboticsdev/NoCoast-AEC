"""Rule-based stand-in for a language model.

It answers the same two requests a real model gets — a geometric checklist, and GeoSteps —
by reading the prompt and the recipe cards. It does not expand a house template: a house is
authored the way the residential cards describe (spaces with names, walls, a plate, a roof,
a straight flight), and anything else is the closest card's worked example.
"""

from __future__ import annotations

import json
import math
import re

from blocks import card_by_id, retrieve
from llm.base import LLMRequest, OnNote, OnText
from schemas.geo import GeoModel
from schemas.requirements import Requirement

NUM = r"(\d+(?:\.\d+)?)"
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10}
STREAM_STEPS = 8

# A mention of one of these becomes an IfcSpace of that name. Order matters: "bathroom" before "room".
ROOM_WORDS = [
    (r"bedrooms?|beds?\b", "bedroom"),
    (r"wcs?\b", "wc"),
    (r"bathrooms?|baths?\b|en-?suites?", "bathroom"),
    (r"kitchens?", "kitchen"),
    (r"living rooms?|lounges?", "living"),
    (r"dining rooms?", "dining"),
    (r"offices?|studies", "office"),
    (r"halls?|entrances?", "hall"),
    (r"garages?", "garage"),
    (r"utilities|laundr(?:y|ies)", "utility"),
]

# Prompts that are a single building-block, answered by applying that card.
SCENARIOS = [
    (r"\b(domes?|cupolas?|rotundas?)\b", "dome"),
    (r"barrel vaults?|\bvaults?\b", "barrel-vault"),
    (r"\btunnels?\b|underground bores?", "tunnel"),
    (r"\bculverts?\b", "culvert"),
    (r"helical stairs?|spiral stairs?|spiral staircases?", "spiral-stair"),
    (r"\bbridges?\b|\bviaducts?\b", "bridge"),
    (r"retaining walls?", "retaining-wall"),
    (r"\btrusses?\b", "truss"),
    (r"curtain walls?", "curtain-wall"),
    (r"cantilevers?", "cantilever"),
    (r"colonnades?|column grids?", "column-grid"),
    (r"louvres?|louvers?|brise-soleil", "louvre"),
    (r"\bramps?\b", "ramp"),
    (r"\barches?\b|\barchways?\b", "arch"),
    (r"\btowers?\b", "tower"),
    (r"\bspiress?\b|\bcones?\b", "spire"),
    (r"\bshells?\b", "shell"),
]


def _num(token: str | None, default: int = 1) -> int:
    if not token:
        return default
    token = token.lower()
    if token in WORDS:
        return WORDS[token]
    try:
        return int(float(token))
    except ValueError:
        return default


def _storeys(text: str) -> int:
    m = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)[\s-]*(storeys?|stories|floors?)\b", text)
    n = _num(m.group(1)) if m else 1
    if re.search(r"\bupstairs\b|\btwo[\s-]storey\b", text):
        n = max(n, 2)
    return max(1, min(n, 8))


def _footprint(text: str) -> tuple[float, float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|metres?|meters?)?\s*(?:by|x|×)\s*(\d+(?:\.\d+)?)\s*(m|metres?|meters?|feet|foot|ft)?", text)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        if m.group(3) and m.group(3).startswith("f"):
            a, b = a * 0.3048, b * 0.3048
        elif re.search(r"\b(feet|foot|ft)\b", text):
            a, b = a * 0.3048, b * 0.3048
        return round(a, 2), round(b, 2)
    if re.search(r"\b(cabin|cottage|small)\b", text):
        return 6.0, 4.0
    return 12.0, 8.0


def _roof_kind(text: str) -> str:
    if re.search(r"\bhip", text):
        return "hip"
    if re.search(r"\b(gable|pitched)\b", text):
        return "gable"
    if re.search(r"\bflat roof\b", text):
        return "flat"
    if re.search(r"\b(house|home|villa)\b", text):
        return "gable"
    return "flat"


def _material(text: str) -> str | None:
    for word in ("masonry", "concrete", "timber", "stone", "glass"):
        if re.search(rf"\b{word}\b", text):
            return word
    return None


def _scenario(text: str) -> str | None:
    """A prompt that is about one building block, rather than a building made of several."""
    if re.search(r"party walls?", text):
        return "party-wall"
    if re.search(r"\b(house|home|cabin|cottage|villa|apartment|flat|dwelling)\b", text):
        return None
    for pattern, card in SCENARIOS:
        if re.search(pattern, text):
            return card
    found = retrieve(text, k=1)
    if found and found[0].id in {c for _, c in SCENARIOS}:
        return found[0].id
    return None


def _rooms(text: str, storeys: int) -> list[dict]:
    """Named spaces, with a level taken from the words next to the mention."""
    found: list[dict] = []
    for pattern, kind in ROOM_WORDS:
        rx = re.compile(rf"\b(?:(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+)?(?:{pattern})\b", re.IGNORECASE)
        for hit in rx.finditer(text):
            n = _num(hit.group(1)) if hit.group(1) else 1
            # Only the words before the mention. The next sentence ("Upstairs: …") must not
            # pull a downstairs room onto the floor above.
            window = text[max(0, hit.start() - 60): hit.start()]
            if re.search(r"upstairs|upper floor|second floor", window):
                level = f"L{min(storeys, 2)}"
            elif re.search(r"downstairs|ground|first floor", window):
                level = "L1"
            elif storeys > 1 and kind in ("bedroom", "bathroom"):
                level = f"L{storeys}"
            else:
                level = "L1"
            for _i in range(n):
                index = len([r for r in found if r["kind"] == kind]) + 1
                if kind == "wc":
                    name = "WC" if n == 1 else f"WC {index}"
                elif n == 1 and kind != "bedroom":
                    name = kind.title()
                else:
                    name = f"{kind.title()} {index}"
                found.append({"kind": kind, "name": name, "level": level})
    if not found:
        found.append({"kind": "room", "name": "Room", "level": "L1"})
    # Stable ids, per level.
    counts: dict[str, int] = {}
    for room in found:
        counts[room["kind"]] = counts.get(room["kind"], 0) + 1
        room["id"] = f"space-{room['level'].lower()}-{room['kind']}-{counts[room['kind']]}"
    return found


def _pack(rooms: list[dict], width: float, depth: float) -> dict[str, list[dict]]:
    """Lay each level's rooms in one row across the footprint."""
    by: dict[str, list[dict]] = {}
    for room in rooms:
        by.setdefault(room["level"], []).append(room)
    for level, group in by.items():
        rw = width / max(len(group), 1)
        for i, room in enumerate(group):
            room.update(x=round(i * rw, 3), y=0.0, w=round(rw, 3), d=depth)
    return by


def _gable(width: float, depth: float, z: float) -> dict:
    pitch = math.radians(35)
    thick = round(0.25 / math.cos(pitch), 4)
    if width >= depth:
        half = depth / 2
        h = round(half * math.tan(pitch), 4)
        profile = [[0, 0], [half, h], [depth, 0], [depth, thick], [half, round(h + thick, 4)], [0, thick]]
        return {"op": "extrude", "depth": width, "axis": [1, 0, 0], "at": [0, 0, z], "profile": {"points": profile}}
    half = width / 2
    h = round(half * math.tan(pitch), 4)
    profile = [[0, 0], [half, h], [width, 0], [width, thick], [half, round(h + thick, 4)], [0, thick]]
    return {"op": "extrude", "depth": depth, "axis": [0, 1, 0], "at": [0, 0, z], "profile": {"points": profile}}


def _hip(width: float, depth: float, z: float) -> dict:
    h = round(min(width, depth) / 2 * math.tan(math.radians(35)), 4)
    cx, cy = width / 2, depth / 2
    if abs(width - depth) < 1e-6:
        apex = [cx, cy, h]
        base = [[0, 0, 0], [width, 0, 0], [width, depth, 0], [0, depth, 0]]
        faces = [list(reversed(base))] + [[base[i], base[(i + 1) % 4], apex] for i in range(4)]
    elif width > depth:
        r0, r1 = [cx - (width - depth) / 2, cy, h], [cx + (width - depth) / 2, cy, h]
        a, b, c, e = [0, 0, 0], [width, 0, 0], [width, depth, 0], [0, depth, 0]
        faces = [[e, c, b, a], [a, b, r1, r0], [b, c, r1], [c, e, r0, r1], [e, a, r0]]
    else:
        r0, r1 = [cx, cy - (depth - width) / 2, h], [cx, cy + (depth - width) / 2, h]
        a, b, c, e = [0, 0, 0], [width, 0, 0], [width, depth, 0], [0, depth, 0]
        faces = [[e, c, b, a], [a, b, r0], [b, c, r1, r0], [c, e, r1], [e, a, r0, r1]]
    return {"op": "mesh", "at": [0, 0, z], "faces": faces}


def _building(prompt: str) -> list[dict]:
    text = prompt.lower()
    storeys = _storeys(text)
    width, depth = _footprint(text)
    height = 3.0
    m = re.search(r"(?:storey|floor|ceiling|level)s?\s*(?:height|heights)?\s*(?:to|of|=)?\s*" + NUM, text)
    if m:
        height = float(m.group(1))
    roof = _roof_kind(text)
    material = _material(text)
    rooms = _pack(_rooms(text, storeys), width, depth)
    title = "Cabin" if "cabin" in text else "House" if re.search(r"house|home|cottage|villa", text) else "Building"
    steps: list[dict] = [{"step": "model", "name": title}]
    for i in range(2, storeys + 1):
        steps.append({"step": "level", "id": f"L{i}", "name": f"Level {i}", "height": height})
    if re.search(r"\bbasement\b", text):
        steps.append({"step": "level", "id": "B1", "name": "Basement", "height": height, "elevation": -height})
        steps.append({"step": "part", "id": "space-b1-room-1", "name": "Basement", "ifc": "IfcSpace", "ifc_type": "SPACE",
                      "level": "B1", "at": [width / 2, depth / 2, 0.2], "solid": {"box": [width - 0.6, depth - 0.6, height - 0.4]}})

    outline = [[0, 0], [width, 0], [width, depth], [0, depth]]
    for index in range(1, storeys + 1):
        level = f"L{index}"
        group = rooms.get(level, [])
        steps.append({"step": "part", "id": f"slab-{level.lower()}", "name": f"floor plate {level}", "ifc": "IfcSlab",
                      "ifc_type": "FLOOR", "level": level, "material": "concrete",
                      "solid": {"op": "extrude", "depth": 0.2, "profile": {"points": outline}}})
        wall = {"ifc": "IfcWall", "ifc_type": "SOLIDWALL", "level": level, "material": material} if material else {
            "ifc": "IfcWall", "ifc_type": "SOLIDWALL", "level": level}
        steps.append({"step": "part", "id": f"wall-{level.lower()}-south", "name": f"south wall {level}", **wall,
                      "solid": {"wall": [[0, 0], [width, 0]], "thickness": 0.2, "height": height}})
        steps.append({"step": "part", "id": f"wall-{level.lower()}-north", "name": f"north wall {level}", **wall,
                      "solid": {"wall": [[0, depth], [width, depth]], "thickness": 0.2, "height": height}})
        steps.append({"step": "part", "id": f"wall-{level.lower()}-west", "name": f"west wall {level}", **wall,
                      "solid": {"wall": [[0, 0], [0, depth]], "thickness": 0.2, "height": height}})
        steps.append({"step": "part", "id": f"wall-{level.lower()}-east", "name": f"east wall {level}", **wall,
                      "solid": {"wall": [[width, 0], [width, depth]], "thickness": 0.2, "height": height}})
        for i in range(len(group) - 1):
            x = group[i]["x"] + group[i]["w"]
            steps.append({"step": "part", "id": f"wall-{level.lower()}-partition-{i+1}", "name": "partition",
                          "ifc": "IfcWall", "ifc_type": "PARTITIONING", "level": level,
                          "solid": {"wall": [[x, 0], [x, depth]], "thickness": 0.12, "height": height}})
        for room in group:
            steps.append({"step": "part", "id": room["id"], "name": room["name"], "ifc": "IfcSpace", "ifc_type": "SPACE",
                          "level": level, "at": [room["x"] + room["w"] / 2, depth / 2, 0.2],
                          "solid": {"box": [max(room["w"] - 0.5, 0.8), max(depth - 0.5, 0.8), height - 0.4]}})
        # One entrance on the ground floor, and a window in every habitable room on the south wall.
        if index == 1 and group:
            door_at = group[0]["x"] + 0.3
            steps.append({"step": "part", "id": "door-entrance", "name": "entrance door", "ifc": "IfcDoor",
                          "ifc_type": "DOOR", "level": level, "material": "timber", "at": [door_at + 0.45, 0, 0],
                          "solid": {"box": [0.9, 0.05, 2.1]}})
            steps.append({"step": "opening", "id": "door-entrance-void", "host": f"wall-{level.lower()}-south",
                          "along": door_at, "up": 0, "width": 0.9, "height": 2.1, "fill": "door-entrance"})
        for room in group:
            if room["kind"] in ("garage", "wc") or room["w"] < 2.4:
                continue
            along = round(room["x"] + room["w"] - 1.3, 3)
            if along < room["x"] + 1.5 or along + 1.1 > width:
                continue
            wid = f"window-{room['id']}"
            steps.append({"step": "part", "id": wid, "name": f"window {room['name']}", "ifc": "IfcWindow",
                          "ifc_type": "WINDOW", "level": level, "material": "glass", "at": [along + 0.5, 0, 0.9],
                          "solid": {"box": [1.0, 0.05, 1.2]}})
            steps.append({"step": "opening", "id": f"{wid}-void", "host": f"wall-{level.lower()}-south",
                          "along": along, "up": 0.9, "width": 1.0, "height": 1.2, "fill": wid})
            if re.search(r"each long side|both sides|either side", text):
                steps.append({"step": "opening", "id": f"{wid}-north-void", "host": f"wall-{level.lower()}-north",
                              "along": along, "up": 0.9, "width": 1.0, "height": 1.2})

    if storeys > 1:
        steps.append({"step": "part", "id": "stair", "name": "straight stair", "ifc": "IfcStair",
                      "ifc_type": "STRAIGHT_RUN_STAIR", "level": "L1", "material": "timber",
                      "repeat": {"count": 16, "translate": [0, 0.26, round(height / 16, 4)]},
                      "solid": {"op": "extrude", "at": [0.6, 0.4, 0], "profile": {"rect": [1.0, 0.28]}, "depth": 0.04}})

    z = height
    top = f"L{storeys}"
    if roof == "gable":
        solid = _gable(width, depth, z)
        steps.append({"step": "part", "id": "roof", "name": "gable roof", "ifc": "IfcRoof", "ifc_type": "GABLE_ROOF",
                      "level": top, "material": "tile", "axis": solid.pop("axis"), "at": solid.pop("at"), "solid": solid})
    elif roof == "hip":
        solid = _hip(width, depth, z)
        steps.append({"step": "part", "id": "roof", "name": "hip roof", "ifc": "IfcRoof", "ifc_type": "HIP_ROOF",
                      "level": top, "at": solid.pop("at"), "solid": solid})
    else:
        steps.append({"step": "part", "id": "roof", "name": "flat roof", "ifc": "IfcRoof", "ifc_type": "FLAT_ROOF",
                      "level": top, "material": "membrane", "at": [0, 0, z],
                      "solid": {"op": "extrude", "depth": 0.2, "profile": {"points": outline}}})
    return steps


def _card_steps(card_id: str) -> list[dict]:
    card = card_by_id(card_id)
    if card is None:
        return _building("a single room")
    return [dict(step) for step in card.steps]


def author_steps(prompt: str) -> list[dict]:
    """The steps the mock would stream for a new model."""
    text = prompt.lower()
    card = _scenario(text)
    if card:
        return _card_steps(card)
    return _building(prompt)


def parse_requirements(prompt: str) -> list[Requirement]:
    """A checklist the mock's own steps satisfy, so the verify round has something true to say."""
    text = prompt.lower()
    card = _scenario(text)
    reqs: list[Requirement] = []
    if card == "dome":
        reqs += [Requirement(text="a dome", kind="count", ifc="IfcRoof", name="dome", value=1),
                 Requirement(text="the dome is curved", kind="curved", ifc="IfcRoof", name="dome")]
    elif card == "barrel-vault":
        reqs += [Requirement(text="a barrel vault", kind="count", ifc="IfcRoof", name="vault", value=1),
                 Requirement(text="the vault is curved", kind="curved", ifc="IfcRoof")]
    elif card == "tunnel":
        reqs += [Requirement(text="a tunnel lining", kind="count", ifc="IfcCivilElement", name="tunnel", value=1),
                 Requirement(text="the bore is below ground", kind="count", ifc="IfcCivilElement", level="B1", value=1)]
    elif card == "bridge":
        reqs += [Requirement(text="piers", kind="count", ifc="IfcColumn", name="pier", value=3),
                 Requirement(text="a deck", kind="count", ifc="IfcSlab", name="deck", value=1),
                 Requirement(text="the deck is curved", kind="curved", name="deck"),
                 Requirement(text="the deck is supported", kind="supported", name="deck"),
                 Requirement(text="clearance under the deck", kind="clearance", name="deck", value=7)]
    elif card == "spiral-stair":
        reqs += [Requirement(text="a spiral stair", kind="entity", ifc="IfcStair", value=1),
                 Requirement(text="the stair winds", kind="curved", ifc="IfcStair")]
    elif card == "retaining-wall":
        reqs.append(Requirement(text="a retaining wall", kind="count", name="retaining", value=1))
    elif card:
        reqs.append(Requirement(text=card.replace("-", " "), kind="count", value=1))
    else:
        storeys = _storeys(text)
        width, depth = _footprint(text)
        reqs.append(Requirement(text=f"{storeys} storeys", kind="levels", value=storeys))
        reqs.append(Requirement(text="footprint", kind="extent", ifc="IfcSlab", name="floor", value=width, value2=depth))
        counts: dict[tuple, int] = {}
        for room in _rooms(text, storeys):
            key = (room["kind"], room["level"])
            counts[key] = counts.get(key, 0) + 1
        for (kind, level), n in counts.items():
            reqs.append(Requirement(text=f"{n} {kind} on {level}", kind="count", ifc="IfcSpace", name=kind, level=level, value=n))
        if storeys > 1:
            reqs.append(Requirement(text="a stair", kind="entity", ifc="IfcStair", value=1))
        roof = _roof_kind(text)
        reqs.append(Requirement(text=f"{roof} roof", kind="count", ifc="IfcRoof", name=roof, value=1))
        if _material(text):
            reqs.append(Requirement(text=f"{_material(text)} walls", kind="material", ifc="IfcWall", item=_material(text)))
    if re.search(r"\b(modern|cozy|cosy|beautiful|elegant)\b", text):
        reqs.append(Requirement(text="the look of it", kind="style"))
    if re.search(r"\bpools?\b", text):
        reqs.append(Requirement(text="a pool", kind="other", supported=False))
    return reqs


class MockLLM:
    name = "mock"

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        prompt: str = request.meta.get("prompt", request.user)
        if request.schema_name == "requirements":
            reply = {"summary": prompt[:80], "requirements": [r.model_dump(exclude_none=True) for r in parse_requirements(prompt)]}
        elif request.schema_name == "build":
            if request.meta.get("problems") or request.meta.get("unmet"):
                reply = {"steps": []}
            elif request.meta.get("editing"):
                reply = {"steps": _edit(prompt, GeoModel.model_validate(request.meta["model"]), request.meta.get("focus"))}
            else:
                reply = {"steps": author_steps(prompt)}
        else:
            raise ValueError(f"mock has no answer for schema '{request.schema_name}'")
        if on_text:
            text = json.dumps(reply)
            for i in range(1, STREAM_STEPS + 1):
                on_text(text[: len(text) * i // STREAM_STEPS])
        return reply


def _edit(prompt: str, geo: GeoModel, focus: str | None) -> list[dict]:
    text = prompt.lower().strip()
    focus_id = None
    if focus:
        m = re.search(r"id=(\S+)", focus)
        focus_id = m.group(1) if m else None

    m = re.search(r"\b(rename|call|name) (the )?(building|house|project|model) (to )?['\"]?([^'\"]+?)['\"]?$", text)
    if m:
        return [{"step": "model", "name": prompt.strip()[m.start(5):m.end(5)]}]

    if focus_id and re.search(r"\b(add|put) (a |an )?(window|door)\b", text):
        host = focus_id if geo.part(focus_id) and geo.part(focus_id).ifc == "IfcWall" else _wall_id(geo)
        if host is None:
            return []
        kind = "window" if "window" in text else "door"
        new_id = geo.unique_id(kind)
        height, up = (1.2, 0.9) if kind == "window" else (2.1, 0.0)
        ifc = "IfcWindow" if kind == "window" else "IfcDoor"
        return [
            {"step": "part", "id": new_id, "name": kind, "ifc": ifc, "level": geo.part(host).level,
             "solid": {"box": [0.9, 0.05, height]}},
            {"step": "opening", "id": f"{new_id}-void", "host": host, "along": 0.2, "up": up, "width": 0.9,
             "height": height, "fill": new_id},
        ]

    if focus_id and re.search(r"\b(remove|delete|drop)\b", text):
        return [{"step": "remove", "id": focus_id}]

    m = re.search(r"\b(remove|delete|drop)\b (the )?(.*)", text)
    if m:
        target = m.group(3).strip()
        if "window" in target and "all" in target:
            return [{"step": "remove", "id": p.id} for p in geo.parts if p.ifc == "IfcWindow"]
        hits = [p for p in geo.parts if target in (p.name or "").lower() or target.replace(" ", "-") in p.id.lower()]
        if not hits:
            # "garage" matches a space named Garage.
            word = target.split()[-1] if target else target
            hits = [p for p in geo.parts if word and word in (p.name or "").lower()]
        return [{"step": "remove", "id": p.id} for p in hits]

    if re.search(r"\b(gable|pitched)\b", text):
        return [{"step": "part", "id": "roof", "name": "gable roof", "ifc": "IfcRoof", "ifc_type": "GABLE_ROOF",
                 "level": _top(geo), "axis": [1, 0, 0], "at": [0, 0, 3],
                 "solid": {"op": "extrude", "depth": 8, "profile": {"points": [[0, 0], [3, 2.1], [6, 0], [6, 0.3], [3, 2.4], [0, 0.3]]}}}]

    if re.search(r"\badd (a |an |another )?(bedroom|room)\b", text):
        level = _top(geo)
        return [{"step": "part", "id": geo.unique_id("bedroom"), "name": "Bedroom extra", "ifc": "IfcSpace",
                 "ifc_type": "SPACE", "level": level, "at": [20, 2, 0.2], "solid": {"box": [3.5, 3.2, 2.6]}}]

    m = re.search(r"\b(storey|floor|ceiling|level)s? (height|heights)? ?(to|of|=)? ?" + NUM, text)
    if m:
        return [{"step": "level", "id": level.id, "height": float(m.group(4))} for level in geo.levels]

    return []


def _wall_id(geo: GeoModel) -> str | None:
    wall = next((p for p in geo.parts if p.ifc == "IfcWall"), None)
    return wall.id if wall else None


def _top(geo: GeoModel) -> str:
    above = [level for level in geo.levels if not level.below_ground]
    return above[-1].id if above else geo.levels[-1].id
