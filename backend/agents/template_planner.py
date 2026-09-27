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
from core.derive import DesignError, analyze
from core.placement import candidates, first_fit
from core.rooms import compass
from schemas.design import Design, Edge, LevelDef, RoomDef, slug
from schemas.requirements import Requirement
from schemas.steps import Step, StepError, apply_step
from solver.layout import ROW_DEPTH, place_rooms

NUMBERS = {"one": 1, "a": 1, "an": 1, "single": 1, "two": 2, "double": 2, "three": 3, "four": 4,
           "five": 5, "six": 6, "seven": 7, "eight": 8}
ORDINALS = {"first": 0, "ground": 0, "1st": 0, "lower": 0, "second": 1, "2nd": 1, "upper": -1,
            "upstairs": -1, "top": -1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3}
BRIDGE = re.compile(r"\b(foot|road|pedestrian )?bridges?\b|\bviaduct\b|\bwalkway over\b")

ROOM_WORDS = [  # (regex, display name, kind)
    (r"living\s*rooms?|lounge|family\s*rooms?", "Living Room", "living"),
    (r"kitchens?", "Kitchen", "kitchen"),
    (r"dining(\s*rooms?)?", "Dining Room", "dining"),
    (r"meeting\s*rooms?|conference\s*rooms?|board\s*rooms?", "Meeting Room", "meeting"),
    (r"class\s*rooms?|lecture\s*(rooms?|halls?)|teaching\s*rooms?", "Classroom", "classroom"),
    (r"consult(ing|ation)?\s*rooms?|exam(ination)?\s*rooms?|treatment\s*rooms?", "Consulting Room", "clinic"),
    (r"wards?", "Ward", "ward"),
    (r"lab(oratory|oratories|s)?\b", "Laboratory", "lab"),
    (r"receptions?|front\s*desks?", "Reception", "reception"),
    (r"shops?|retail\s*(units?|spaces?|floors?)|show\s*rooms?|sales\s*floors?", "Shop", "retail"),
    (r"caf[eé]s?|coffee\s*shops?|restaurants?|bistros?", "Café", "cafe"),
    (r"gyms?|fitness\s*(rooms?|suites?)", "Gym", "gym"),
    (r"auditoriums?|theatres?|theaters?|assembly\s*halls?|cinemas?", "Auditorium", "auditorium"),
    (r"workshops?|maker\s*spaces?|machine\s*shops?", "Workshop", "workshop"),
    (r"stock\s*rooms?|store\s*rooms?|storage\s*(rooms?|areas?)?", "Store", "storage"),
    (r"warehouses?|depots?|distribution\s*(centres?|centers?)", "Warehouse", "warehouse"),
    (r"plant\s*rooms?|boiler\s*rooms?|mechanical\s*rooms?", "Plant Room", "plant"),
    (r"server\s*rooms?|data\s*(centres?|centers?)|comms\s*rooms?", "Server Room", "server"),
    (r"barns?", "Barn", "barn"),
    (r"stables?", "Stable", "stable"),
    (r"offices?|stud(y|ies)", "Office", "office"),
    (r"bath(room)?s?|wash\s*rooms?|rest\s*rooms?|toilets?", "Bathroom", "bathroom"),
    (r"bed\s*rooms?", "Bedroom", "bedroom"),
]
NUM = r"(\d+|" + "|".join(NUMBERS) + r")"
FT = 0.3048
# What a room of each kind is fitted out with — a few pieces that read as the room's purpose.
FURNITURE = {  # kind -> [(fixture kind, side)]
    "bedroom": [("double_bed", "N"), ("wardrobe", "E")], "living": [("sofa", "W"), ("coffee_table", "center")],
    "kitchen": [("kitchen_counter", "N"), ("fridge", "E"), ("oven", "N"), ("sink", "N")], "dining": [("dining_table", "center")],
    "bathroom": [("toilet", "N"), ("washbasin", "E"), ("shower", "W")], "office": [("desk", "N"), ("chair", "center")],
    "garage": [("car", "center")],
    "meeting": [("conference_table", "center"), ("whiteboard", "N")],
    "reception": [("reception_desk", "N"), ("sofa", "W")],
    "classroom": [("school_desk", "center"), ("whiteboard", "N"), ("lectern", "W")],
    "lab": [("workbench", "N"), ("filing_cabinet", "E")],
    "clinic": [("exam_table", "center"), ("washbasin", "E"), ("desk", "N")],
    "ward": [("hospital_bed", "N"), ("washbasin", "E")],
    "retail": [("shelving_unit", "N"), ("display_case", "W"), ("checkout_counter", "S")],
    "cafe": [("cafe_table", "center"), ("bar_counter", "N"), ("stool", "E")],
    "gym": [("treadmill", "N"), ("weight_bench", "center")],
    "auditorium": [("seating_row", "center"), ("lectern", "N")],
    "workshop": [("workbench", "N"), ("machine", "center"), ("crate", "E")],
    "warehouse": [("pallet_rack", "N"), ("pallet_rack", "S"), ("crate", "center")],
    "plant": [("boiler", "N"), ("hvac_unit", "E"), ("water_tank", "W")],
    "server": [("server_rack", "N"), ("server_rack", "E")],
    "parking": [("car", "center")],
    "utility": [("washing_machine", "N")],
    "storage": [("shelving_unit", "N")],
    "barn": [("crate", "center")], "stable": [("crate", "N")],
}
# Prompts that describe a building that is not a house: the storey height and roof they want.
NON_DOMESTIC = [
    (r"\b(warehouses?|depots?|distribution (centre|center|hub)|hangars?|logistics)\b", "warehouse", 8.0, "shed"),
    (r"\b(workshops?|maker ?spaces?|machine shops?|fabrication)\b", "workshop", 6.0, "shed"),
    (r"\b(barns?|stables?|farm building|granary)\b", "barn", 6.0, "gable"),
    (r"\b(car ?parks?|parking (deck|structure|garage))\b", "parking", 2.8, "flat"),
    (r"\b(office (block|building|tower)|headquarters|hq)\b", "office", 3.6, "flat"),
    (r"\b(schools?|colleges?|academy|classroom block)\b", "school", 3.6, "flat"),
    (r"\b(clinics?|surgery|health ?(centre|center)|hospital|ward block)\b", "clinic", 3.3, "flat"),
    (r"\b(shops?|retail|stores?|supermarkets?|showrooms?|caf[eé]s?|restaurants?)\b", "retail", 4.5, "flat"),
    (r"\b(gyms?|sports hall|leisure ?(centre|center)|fitness)\b", "gym", 6.0, "flat"),
    (r"\b(auditoriums?|theatres?|theaters?|cinemas?|assembly hall|chapel|church)\b", "auditorium", 8.0, "gable"),
    (r"\b(data ?(centre|center)|server farm)\b", "server", 4.0, "flat"),
]
# The rooms a typology gets when the prompt names none of its own (sizes come from _room_area).
PROGRAMME: dict[str, list[tuple[str, str]]] = {  # building type -> [(room name, room kind)]
    "warehouse": [("Warehouse", "warehouse"), ("Despatch Office", "office"), ("Plant Room", "plant"), ("Washroom", "bathroom")],
    "workshop": [("Workshop", "workshop"), ("Store", "storage"), ("Workshop Office", "office"), ("Washroom", "bathroom")],
    "barn": [("Barn", "barn"), ("Stable", "stable"), ("Feed Store", "storage")],
    "parking": [("Parking Deck", "parking"), ("Plant Room", "plant")],
    "office": [("Reception", "reception"), ("Open Office", "office"), ("Meeting Room", "meeting"),
               ("Washroom", "bathroom"), ("Server Room", "server")],
    "school": [("Reception", "reception"), ("Classroom 1", "classroom"), ("Classroom 2", "classroom"),
               ("Assembly Hall", "auditorium"), ("Washroom", "bathroom")],
    "clinic": [("Reception", "reception"), ("Consulting Room 1", "clinic"), ("Consulting Room 2", "clinic"),
               ("Ward", "ward"), ("Washroom", "bathroom")],
    "retail": [("Shop", "retail"), ("Stock Room", "storage"), ("Washroom", "bathroom")],
    "gym": [("Reception", "reception"), ("Gym", "gym"), ("Changing Room", "bathroom")],
    "auditorium": [("Foyer", "hall"), ("Auditorium", "auditorium"), ("Washroom", "bathroom")],
    "server": [("Server Room", "server"), ("Plant Room", "plant"), ("Control Office", "office")],
}
# What goes on an upper storey the prompt didn't describe. Single-purpose buildings repeat themselves
# (a car park is parking all the way up); everything else gets workspace over the ground floor.
UPPER_FLOOR: dict[str, tuple[str, str]] = {
    "parking": ("Parking Deck", "parking"), "warehouse": ("Warehouse", "warehouse"),
    "retail": ("Shop", "retail"), "gym": ("Gym", "gym"), "server": ("Server Room", "server"),
    "barn": ("Hay Loft", "storage"),
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
    m = re.search(r"(gable|pitched|hip(ped)?|flat|shed|mono-?pitch|skillion|lean-to)\s*roof", text)
    if m:
        kind = {"pitched": "gable", "hipped": "hip", "monopitch": "shed", "mono-pitch": "shed",
                "skillion": "shed", "lean-to": "shed"}.get(m.group(1), m.group(1))
        reqs.append(Requirement(text=f"{kind} roof", kind="roof", item=kind))
    for words, item, label in ((r"solar|photovoltaic|\bpv\b", "solar panels", "solar panels"),
                               (r"water tank|cistern|rainwater", "water tank", "a water tank"),
                               (r"cycle (rack|park|store)|bike rack|bicycle", "bicycle rack", "cycle parking"),
                               (r"car ?park|parking (deck|structure|bays?|spaces?)", "car park", "parking"),
                               (r"loading (bay|dock)|roller (door|shutter)|goods door", "loading bay", "a loading bay"),
                               (r"mezzanine|gallery floor", "mezzanine", "a mezzanine"),
                               (r"landscap(e|ing)\b", "landscaping", "landscaping")):
        if re.search(words, text):
            reqs.append(Requirement(text=label, kind="feature", item=item))
    if re.search(r"basement|cellar", text):
        reqs.append(Requirement(text="a basement", kind="feature", item="basement"))
    for words, item, label in ((r"courtyard|patio|atrium", "courtyard", "a courtyard"), (r"carport", "carport", "a carport"),
                               (r"pergola|gazebo", "pergola", "a pergola"), (r"roof terrace|terrace", "terrace", "a terrace"),
                               (r"curved|rounded|bow window|round(ed)? wall", "curved wall", "a curved wall"),
                               (r"l-shaped|l shaped", "l-shaped", "an L-shaped room"), (r"garden wall|fence", "garden wall", "a garden wall"),
                               (r"\bdeck\b", "deck", "a deck"), (BRIDGE.pattern, "bridge", "a bridge"),
                               (r"railings?|parapets?|balustrades?|handrails?", "railing", "railings")):
        if re.search(words, text):
            reqs.append(Requirement(text=label, kind="feature", item=item))
    for m in mentioned_bricks(prompt):
        name = library().get(m.brick).name.lower()
        if m.room_kind:
            reqs.append(Requirement(text=f"{name} in the {m.room_kind}", kind="asset", item=m.brick, room=m.room_kind,
                                    value=m.count if not m.each else None))
            continue
        article = "an" if name[0] in "aeiou" else "a"
        reqs.append(Requirement(text=f"{m.count} {name}s" if m.count > 1 else f"{article} {name}", kind="asset", item=m.brick, value=m.count))
    return reqs


def _assign_rooms(text: str, storeys: int, building: str | None = None) -> list[list[tuple[str, str]]]:
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
        public = kind in ("living", "kitchen", "dining", "office", "reception", "retail", "cafe", "warehouse",
                          "workshop", "auditorium", "gym", "parking", "barn", "stable")
        if public or storeys == 1:
            floors[0].append((room, kind))
        else:
            floors[min(range(1, storeys), key=lambda i: len(floors[i]))].append((room, kind))
    # Nothing named: fall back to the standard programme for this kind of building.
    if not floors[0]:
        floors[0] = list(PROGRAMME.get(building or "", [("Living Room", "living"), ("Kitchen", "kitchen")]))
    for i in range(1, storeys):
        if floors[i]:
            continue
        if not building:
            floors[i] = [("Bedroom 1", "bedroom"), ("Bedroom 2", "bedroom")] if i == 1 else [(f"Room {i}", "other")]
        elif building in UPPER_FLOOR:
            name, kind = UPPER_FLOOR[building]
            floors[i] = [(f"{name} {i + 1}", kind)]
        else:
            floors[i] = [(f"Office {i + 1}", "office"), (f"Meeting Room {i + 1}", "meeting")]
    k = 0
    for rooms in floors:
        for j, (r, kind) in enumerate(rooms):
            if kind == "bedroom":
                k += 1
                rooms[j] = (f"Bedroom {k}", kind)
    return floors


def typology(text: str) -> tuple[str, float, str] | None:
    """Which non-domestic building the prompt is describing, and the storey height and roof it wants."""
    for pattern, kind, height, roof in NON_DOMESTIC:
        if re.search(pattern, text):
            return kind, height, roof
    return None


def _room_area(kind: str) -> float:
    """A sensible size for a room the prompt named but did not dimension."""
    return {"bathroom": 8, "storage": 12, "plant": 20, "server": 16, "utility": 10, "clinic": 16, "meeting": 24,
            "reception": 35, "classroom": 60, "lab": 60, "ward": 45, "retail": 150, "cafe": 80, "gym": 200,
            "auditorium": 250, "workshop": 180, "warehouse": 700, "parking": 600, "barn": 250,
            "stable": 60}.get(kind, 18)


def template_steps(prompt: str) -> list[dict]:
    """Build steps for a new design, in construction order."""
    text = prompt.lower()
    storeys = max(1, min(_count(text, r"(stor(e)?y|stories|storeys|floors?|levels?)") or 1, 40))
    basement = bool(re.search(r"basement|cellar", text))
    kind_of_building = typology(text)
    floors = _assign_rooms(text, storeys, kind_of_building[0] if kind_of_building else None)
    garage = "garage" in text
    if BRIDGE.search(text) and not any(re.search(r"\b(?:" + p + r")\b", text) for p, _, _ in ROOM_WORDS):
        # A structure with no rooms at all: the level exists only to carry the free elements.
        return [{"step": "building", "name": "Footbridge", "description": "a footbridge: deck on piers"},
                {"step": "level", "id": "L1"}] + shapes.bridge_steps(Design(levels=[LevelDef(id="L1")]))
    if kind_of_building:
        what, storey_height, default_roof = kind_of_building
        name, description = what.title(), f"{storeys}-storey {what}"
    else:
        storey_height, default_roof = 3.0, None
        name, description = "Generated House", f"{storeys}-storey house" + (" with a basement" if basement else "")
    steps: list[dict] = [{"step": "building", "name": name, "description": description}]
    if basement:
        steps.append({"step": "level", "id": "B1", "height": min(storey_height, 3.0)})
    for i in range(storeys):
        steps.append({"step": "level", "id": f"L{i + 1}", "height": storey_height,
                      "why": (f"{storey_height:g} m floor-to-floor suits the spans and services this building needs"
                              if kind_of_building and not i else
                              "3 m floor-to-floor keeps the stair to a single straight flight" if i else None)})
    # Every storey gets a hall so there is somewhere for the stair and the doors to meet.
    design = Design(levels=[])
    level_ids = (["B1"] if basement else []) + [f"L{i + 1}" for i in range(storeys)]
    if basement:
        floors = [[("Storage", "storage"), ("Utility Room", "utility")]] + floors
    for i, (level, rooms) in enumerate(zip(level_ids, floors)):
        design.levels.append(LevelDef(id=level, height=min(storey_height, 3.0) if level.startswith("B") else storey_height))
        hall_id, hall_name = ("hall", "Hall") if level == "L1" else (f"landing-{level.lower()}", f"Landing {level}")
        hall = RoomDef(id=hall_id, name=hall_name, level=level, kind="hall", area=12)
        defs = [hall] + [RoomDef(id=slug(r), name=r, level=level, kind=kind, area=_room_area(kind)) for r, kind in rooms]
        if level == "L1" and garage:
            defs.append(RoomDef(id="garage", name="Garage", level=level, kind="garage"))
        if len(level_ids) > 1:
            # Stacked storeys need a stair, and a straight flight wants one long wall: give the hall
            # the full depth of the plan at the west end and pack everything else east of it.
            hall.rect = (0.0, 0.0, 4.0 if kind_of_building else 3.0, 2 * ROW_DEPTH)
            rects = place_rooms([hall.rect], [r for r in defs if r is not hall])
        else:
            rects = place_rooms([], defs)
        for r in defs:
            r.rect = rects.get(r.id, r.rect)
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
            for r in defs],
            "why": ("service rooms grouped below ground where they need no daylight" if level.startswith("B")
                    else "public rooms on the ground floor, hall in the middle so nothing is reached through another room"
                    if level == "L1" else "sleeping rooms stacked over the ground-floor plate so the load paths line up")})
    m = re.search(r"(gable|pitched|hip(ped)?|shed|mono-?pitch|skillion|lean-to)\s*roof", text)
    roof_kind = ({"pitched": "gable", "hipped": "hip", "monopitch": "shed", "mono-pitch": "shed", "skillion": "shed",
                  "lean-to": "shed"}.get(m.group(1), m.group(1)) if m else
                 default_roof if kind_of_building and default_roof != "flat" else None)
    if roof_kind:
        steps.append({"step": "roof", "kind": roof_kind,
                      "why": ("one sloping plane is the cheapest way to span and drain a shed of this depth"
                              if roof_kind == "shed" else
                              "a pitched roof over a rectangular plate sheds water to two sides and needs no gutters at the gable ends")})
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
            steps.append({"step": "door", "room": hall, "to": "outside", "side": side,
                          "why": "the entrance opens straight into the hall, so the circulation starts at the front door"})
    # A room that takes vehicles or pallets gets a shutter straight to the outside, not a single leaf.
    for r in design.rooms:
        if r.kind in ("warehouse", "workshop", "parking", "barn") and derived.rooms[r.id].sides:
            steps.append({"step": "door", "room": r.id, "to": "outside", "side": derived.rooms[r.id].sides[0],
                          "kind": "roller", "why": "a roller shutter on the yard side so a lorry can back straight in"})
    big = bool(re.search(r"natural light|lots of windows|large windows|bright|glass", text))
    for r in design.rooms:
        info = derived.rooms[r.id]
        sides = info.sides
        if r.id == "hall" and len(sides) > 1:
            sides = sides[1:]  # the entrance door is on the first exterior side
        if sides and r.kind not in ("garage", "carport", "courtyard", "terrace", "pergola", "parking") and not design.level(r.level).below_ground:
            # Tall industrial volumes are lit high up; shops and offices want a horizontal band.
            glazing = ("clerestory" if r.kind in ("warehouse", "workshop", "auditorium", "gym", "barn")
                       else "ribbon" if r.kind in ("retail", "office", "reception", "cafe") and design.level(r.level).height >= 3.5
                       else "large" if big else "standard")
            if r.poly:  # polygons name walls by a point: the middle of the longest wall on that side
                wall = max(info.exterior[sides[0]], key=lambda w: w.length)
                steps.append({"step": "window", "room": r.id, "near": list(wall.mid), "kind": glazing})
            else:
                steps.append({"step": "window", "room": r.id, "side": sides[0], "kind": glazing})
    # No side: the flight takes the hall's longest straight wall, which is where it actually fits.
    if storeys > 1:
        steps.append({"step": "stair", "room": "hall",
                      "why": "the flight runs along the hall's longest wall, clear of the front door and the room openings"})
    if basement:
        steps.append({"step": "stair", "room": "landing-b1",
                      "why": "the basement flight sits under the upper one so the wells align"})
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
    if BRIDGE.search(text):
        steps += shapes.bridge_steps(design)
    steps += site_steps(text, design)
    mentions = mentioned_bricks(prompt)
    if mentions:
        steps += brick_steps(mentions, run_steps(steps)[0])
    return steps


def brick_steps(mentions, design: Design) -> list[dict]:
    """A brick step for every brick the prompt names, at the first spot its mount and tags suggest that clashes with
    nothing already there (core/placement.py)."""
    steps: list[dict] = []
    derived = analyze(design)
    slot = 0
    for m in mentions:
        brick = library().get(m.brick)
        targets = [r.id for r in design.rooms if r.kind == m.room_kind] if m.each else []
        for i in range(len(targets) or m.count):
            options = candidates(brick, design, derived, targets[i] if targets else None, slot, m.room_kind)
            slot += 1
            fit = first_fit(brick, design, options)
            if fit is not None:
                args, design, derived = fit
                steps.append({"step": "brick", "brick": brick.id, **args})
    return steps


def site_steps(text: str, design: Design) -> list[dict]:
    """Equipment and site objects that stand outside the rooms: roof plant, a solar array, cycle
    parking, trees, parking bays. Free-standing fixtures, laid out from the building's own extent."""
    if not design.rooms:
        return []
    top = design.levels[-1].id
    xs = [c for r in design.rooms_on("L1") for c in (r.box[0], r.box[2])]
    ys = [c for r in design.rooms_on("L1") for c in (r.box[1], r.box[3])]
    if not xs:
        return []
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    out: list[dict] = []
    if re.search(r"solar|photovoltaic|\bpv\b", text):
        rows = max(1, int((x1 - x0) // 2))
        out += [{"step": "furniture", "kind": "solar_panel", "level": top, "position": [round(x0 + 1 + i * 2, 2), round((y0 + y1) / 2, 2)],
                 "elevation": design.level(top).height, "rotation": 0,
                 **({"why": "the array sits on the largest unshaded roof plane, tilted south"} if i == 0 else {})}
                for i in range(min(rows, 10))]
    if re.search(r"water tank|cistern|rainwater", text):
        out.append({"step": "furniture", "kind": "water_tank", "level": "L1", "position": [round(x1 + 2, 2), round(y0 + 1, 2)],
                    "why": "the tank stands clear of the building on the service side"})
    if re.search(r"cycle (rack|park|store)|bike rack|bicycle", text):
        out += [{"step": "furniture", "kind": "bicycle_rack", "level": "L1", "position": [round(x0 + 1 + i * 2.5, 2), round(y0 - 3, 2)]}
                for i in range(2)]
    if re.search(r"landscap|planting", text) and not re.search(r"\btrees?\b", text):
        # Trees the prompt names are placed as library bricks by mentioned_bricks; a bare "landscaping"
        # names none, so plant a line of them here.
        out += [{"step": "brick", "brick": "tree", "ref": "site", "position": [round(x0 - 5, 2), round(y0 + i * 7, 2)],
                 **({"why": "a line of trees screens the approach without shading the south elevation"} if i == 0 else {})}
                for i in range(3)]
    if re.search(r"car ?park|parking (bays?|spaces?|lot)", text) and not any(r.kind == "parking" for r in design.rooms):
        out += [{"step": "furniture", "kind": "car", "level": "L1", "position": [round(x1 + 4, 2), round(y0 + i * 2.8, 2)], "rotation": 90}
                for i in range(4)]
    if re.search(r"bench|seating outside|forecourt", text):
        out += [{"step": "furniture", "kind": "bench", "level": "L1", "position": [round(x0 + 2 + i * 4, 2), round(y0 - 2, 2)]}
                for i in range(2)]
    if re.search(r"loading (bay|dock)|yard\b|forecourt|hardstanding", text):
        out.append({"step": "element", "kind": "slab", "name": "Yard", "level": "L1", "thickness": 0.2,
                    "poly": [[round(x0, 2), round(y0 - 12, 2)], [round(x1, 2), round(y0 - 12, 2)],
                             [round(x1, 2), round(y0, 2)], [round(x0, 2), round(y0, 2)]],
                    "why": "12 m of hardstanding in front of the shutters: enough for a lorry to turn"})
    return out


def _facing(wall, poly) -> str:
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
