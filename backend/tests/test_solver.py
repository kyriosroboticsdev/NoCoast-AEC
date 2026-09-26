import pytest

from agents.template_planner import parse_program
from schemas.program import Program, Room
from solver.layout import solve


def test_deterministic():
    p = parse_program("two storey house with a kitchen, living room and three bedrooms and a garage")
    assert solve(p).model_dump_json() == solve(p).model_dump_json()


def test_ids_survive_adding_a_room():
    p1 = Program(storeys=2, rooms=[Room(name="Kitchen", kind="kitchen"), Room(name="Bedroom 1", level="L2", kind="bedroom")])
    p2 = p1.model_copy(update={"rooms": p1.rooms + [Room(name="Bedroom 2", level="L2", kind="bedroom")]})
    ids1 = {e.id for e in solve(p1).elements}
    ids2 = {e.id for e in solve(p2).elements}
    # Everything that existed still exists (walls, entrance, kitchen space …); only new elements were added.
    assert "L1-wall-S" in ids1 and "L2-space-bedroom-1" in ids1
    assert ids1 - ids2 <= {i for i in ids1 if "hall" in i}  # hall filler spaces may be replaced by real rooms
    assert "L2-space-bedroom-2" in ids2


def test_footprint_and_features():
    p = Program(storeys=1, rooms=[Room(name="Living Room", kind="living")], footprint=(12, 8), garage=True, porch=True)
    spec = solve(p)
    slab = next(e for e in spec.elements if e.id == "L1-floor")
    assert slab.outline == [(0, 0), (12, 0), (12, 8), (0, 8)]
    ids = {e.id for e in spec.elements}
    assert "garage-door" in ids and "porch-col-1" in ids and "porch-roof" in ids


def test_program_validation():
    with pytest.raises(ValueError, match="on L4 but the building has only 1"):
        Program(storeys=1, rooms=[Room(name="X", level="L4")])
    with pytest.raises(ValueError, match="duplicate"):
        Program(storeys=1, rooms=[Room(name="X"), Room(name="X")])
    with pytest.raises(ValueError, match="storey id"):
        Room(name="X", level="upstairs")


def test_program_coerces_small_model_junk():
    p = Program.model_validate({"storeys": 2, "storey_height": 0, "footprint": [0, 0], "name": "",
                                "rooms": [{"name": "Bed", "level": "level 2", "area": 0, "kind": "bedroom"},
                                          {"name": "Kitchen", "level": 1, "kind": "kitchen"}]})
    assert p.footprint is None and p.storey_height == 3.0 and p.name == "Generated Building"
    assert p.rooms[0].level == "L2" and p.rooms[0].area is None and p.rooms[0].index == 1
    assert p.rooms[1].level == "L1"


def test_parse_program_places_rooms():
    p = parse_program("Two storey house. Ground floor: kitchen and living room. Upstairs three bedrooms and a bathroom.")
    by_level = {}
    for r in p.rooms:
        by_level.setdefault(r.level, []).append(r.name)
    assert set(by_level["L1"]) == {"Kitchen", "Living Room"}
    assert set(by_level["L2"]) == {"Bedroom 1", "Bedroom 2", "Bedroom 3", "Bathroom"}
