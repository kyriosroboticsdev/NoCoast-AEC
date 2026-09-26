"""Polygon rooms, arcs, open edges, unroofed rooms, point-based wall naming and free-standing elements."""

import pytest

from core.derive import DesignError, analyze
from ifc.builder import compile_ifc
from schemas.design import Design, DoorDef, FixtureDef, FreeDef, LevelDef, RoomDef, StairDef, WindowDef
from schemas.steps import Step, StepError, apply_step


def _els(d, kind):
    return [e for e in d.spec.elements if e.type == kind]


def test_rect_rooms_keep_their_wall_ids():
    d = Design(rooms=[RoomDef(id="hall", name="Hall", kind="hall", rect=(0, 0, 3, 6)),
                      RoomDef(id="kitchen", name="Kitchen", kind="kitchen", rect=(3, 0, 4, 6))])
    ids = {w.id for w in _els(analyze(d), "wall")}
    assert ids == {"L1-wall-hall-W", "L1-wall-hall-S", "L1-wall-hall-N", "L1-wall-hall+kitchen",
                   "L1-wall-kitchen-S", "L1-wall-kitchen-E", "L1-wall-kitchen-N"}


def test_l_shaped_room_walls_and_ambiguous_side():
    # An L: 8 x 8 with the north-east 4 x 4 corner missing -> two north-facing walls.
    poly = [[0, 0], [8, 0], [8, 4], [4, 4], [4, 8], [0, 8]]
    d = Design(rooms=[RoomDef(id="living", name="Living", kind="living", poly=poly)])
    der = analyze(d)
    walls = {w.id: w for w in _els(der, "wall")}
    assert set(walls) == {"L1-wall-living-S", "L1-wall-living-E", "L1-wall-living-N", "L1-wall-living-E-2",
                          "L1-wall-living-N-2", "L1-wall-living-W"}
    assert der.rooms["living"].sides == ["S", "E", "W", "N"]
    assert d.rooms[0].area_m2 == 48

    d.windows.append(WindowDef(id="w", room="living", side="N"))
    with pytest.raises(DesignError, match="2 walls facing N; say which with near"):
        analyze(d)
    d.windows[0] = WindowDef(id="w", room="living", near=(6, 4.1))
    der = analyze(d)
    win = _els(der, "window")[0]
    assert win.wall in ("L1-wall-living-N", "L1-wall-living-N-2")
    assert der.sides["w"] == "N"
    # The stair fits along the long west wall even though the room is not a rectangle.
    d.stairs.append(StairDef(id="s", room="living", side="W"))
    stair = _els(analyze(d), "stair")[0]
    assert stair.direction in (90.0, 270.0)


def test_curved_wall_is_one_faceted_wall_with_an_opening():
    poly = [[0, 0], [6, 0], {"to": [6, 5], "through": [7.5, 2.5]}, [0, 5]]
    d = Design(rooms=[RoomDef(id="lounge", name="Lounge", kind="living", poly=poly)],
               windows=[WindowDef(id="w", room="lounge", near=(7.5, 2.5))])
    der = analyze(d)
    curved = [w for w in _els(der, "wall") if w.path]
    assert len(curved) == 1 and curved[0].id == "L1-wall-lounge-E" and curved[0].radius == pytest.approx(2.83, abs=0.05)
    assert len(curved[0].path) >= 10
    win = _els(der, "window")[0]
    assert win.wall == "L1-wall-lounge-E"
    model, _ = compile_ifc(der.spec, {})
    assert model.by_type("IfcWall") and model.by_type("IfcWindow")
    ps = {p.Name: p for p in model.by_type("IfcPropertySet")}
    assert "NoCoast_Curve" in ps


def test_open_edge_gets_columns_and_carport_kind_has_no_walls():
    d = Design(rooms=[RoomDef(id="house", name="House", kind="living", rect=(0, 0, 6, 6)),
                      RoomDef(id="carport", name="Carport", kind="carport", rect=(6, 0, 4, 6), enclosed=False)])
    der = analyze(d)
    walls = {w.id for w in _els(der, "wall")}
    assert "L1-wall-house-E" in walls and not any("carport" in w for w in walls)
    cols = [c for c in _els(der, "column") if c.id.startswith("L1-col-carport")]
    assert len(cols) >= 6  # three open sides, two+ columns each
    assert any(b.id.startswith("L1-beam-carport") for b in _els(der, "beam"))
    assert der.rooms["carport"].open_sides == ["E", "N", "S"]
    # The house may have a window towards the carport (its east wall is exterior).
    d.windows.append(WindowDef(id="w", room="house", side="E"))
    assert _els(analyze(d), "window")[0].wall == "L1-wall-house-E"

    poly = [[0, 0], [5, 0], [5, 4], {"to": [0, 4], "open": True}]
    d2 = Design(rooms=[RoomDef(id="shed", name="Shed", kind="storage", poly=poly)])
    der2 = analyze(d2)
    assert {w.id for w in _els(der2, "wall")} == {"L1-wall-shed-S", "L1-wall-shed-E", "L1-wall-shed-W"}
    assert len([c for c in _els(der2, "column") if c.id.startswith("L1-col-shed-N")]) == 3


def test_courtyard_has_no_roof_and_neighbours_get_exterior_walls():
    d = Design(rooms=[RoomDef(id="a", name="A", kind="living", rect=(0, 0, 4, 4)),
                      RoomDef(id="yard", name="Courtyard", kind="courtyard", rect=(4, 0, 4, 4)),
                      RoomDef(id="b", name="B", kind="bedroom", rect=(8, 0, 4, 4))])
    der = analyze(d)
    assert not d.rooms[1].roofed
    assert len(_els(der, "roof")) == 2
    ids = {w.id for w in _els(der, "wall")}
    assert "L1-wall-a-E" in ids and "L1-wall-b-W" in ids and not any("yard" in w for w in ids)
    assert any(r.id.startswith("L1-rail-yard") for r in _els(der, "railing"))
    assert len(_els(der, "slab")) == 2  # the ground-floor courtyard is not paved as a slab
    d.windows.append(WindowDef(id="w", room="a", side="E"))
    assert _els(analyze(d), "window")[0].wall == "L1-wall-a-E"


def test_near_far_from_every_wall_is_rejected_with_options():
    d = Design(rooms=[RoomDef(id="a", name="A", kind="living", rect=(0, 0, 4, 4))],
               fixtures=[FixtureDef(id="f", room="a", kind="sofa", near=(20, 20))])
    with pytest.raises(DesignError, match=r"near=\[20.0, 20.0\] is .* m from every wall"):
        analyze(d)


def test_free_elements_and_openings_in_a_free_wall():
    d = Design(levels=[LevelDef(id="L1")], rooms=[],
               elements=[FreeDef(id="garden-wall", kind="wall", path=[[0, 0], [10, 0], {"to": [10, 6], "through": [12, 3]}], height=2.0),
                         FreeDef(id="deck", kind="slab", poly=[[0, 2], [6, 2], [6, 6], [0, 6]], thickness=0.15),
                         FreeDef(id="pergola-roof", kind="roof", name="Pergola", poly=[[0, 2], [6, 2], [6, 6], [0, 6]]),
                         FreeDef(id="post", kind="column", at=(0.3, 2.3)),
                         FreeDef(id="beam", kind="beam", start=(0, 2), end=(6, 2))],
               doors=[DoorDef(id="gate", wall="garden-wall", at=0.3, kind="double")])
    der = analyze(d)
    spec = der.spec
    wall = _els(der, "wall")[0]
    assert wall.id == "garden-wall" and wall.path and wall.height == 2.0
    assert _els(der, "door")[0].wall == "garden-wall"
    assert {e.type for e in spec.elements} >= {"wall", "slab", "roof", "column", "beam", "door"}
    model, _ = compile_ifc(spec, {})
    assert len(model.by_type("IfcDoor")) == 1


def test_steps_accept_polygons_near_and_elements():
    d = Design(levels=[LevelDef(id="L1")])
    d, msg = apply_step(d, Step.model_validate({"step": "room", "name": "Living", "poly": [[0, 0], [8, 0], [8, 4], [4, 4], [4, 8], [0, 8]]}))
    assert "6-sided, 48 m" in msg and d.rooms[0].poly is not None
    d, msg = apply_step(d, Step.model_validate({"step": "window", "room": "living", "near": [6, 4]}))
    assert d.windows[0].near == (6.0, 4.0) and "near" in msg
    d, msg = apply_step(d, Step.model_validate({"step": "room", "name": "Carport", "kind": "carport", "rect": [8, 0, 4, 4]}))
    assert not d.rooms[1].enclosed and "no walls" in msg
    d, msg = apply_step(d, Step.model_validate({"step": "room", "name": "Patio", "kind": "courtyard", "rect": [8, 4, 4, 4]}))
    assert not d.rooms[2].roofed
    d, msg = apply_step(d, Step.model_validate({"step": "element", "kind": "wall", "name": "Garden wall", "path": [[0, -2], [12, -2]], "height": 1.8}))
    assert d.elements[0].id == "garden-wall" and d.elements[0].height == 1.8
    d, msg = apply_step(d, Step.model_validate({"step": "door", "wall": "garden-wall"}))
    assert d.doors[0].wall == "garden-wall"
    with pytest.raises(StepError, match="crosses itself"):
        apply_step(d, Step.model_validate({"step": "room", "name": "Bow", "poly": [[20, 0], [24, 4], [24, 0], [20, 4]]}))
    analyze(d)  # everything derives
    d, msg = apply_step(d, Step.model_validate({"step": "remove", "id": "garden-wall"}))
    assert not d.doors and not d.elements


def test_layout_with_polygon_rooms():
    d = Design(levels=[LevelDef(id="L1")])
    d, _ = apply_step(d, Step.model_validate({"step": "layout", "level": "L1", "rooms": [
        {"name": "Hall", "rect": [0, 0, 3, 8]},
        {"name": "Living", "poly": [[3, 0], [10, 0], [10, 5], [7, 5], [7, 8], [3, 8]]}]}))
    der = analyze(d)
    assert der.rooms["living"].neighbours == ["hall"]
    assert "hall" in der.rooms["hall"].partitions["living"][0].rooms


def test_template_and_mock_cover_the_new_vocabulary():
    from agents.template_planner import TemplatePlanner, parse_requirements
    from llm.mock import MockLLM

    r = TemplatePlanner().plan("a house with an L-shaped living room, a kitchen, two bedrooms and a carport")
    assert not [n for n in r.notes if "{'step'" in n], r.notes
    living = r.design.room("living-room")
    assert living.poly is not None and len(living.poly) == 6
    assert any(w.room == "living-room" and w.near is not None for w in r.design.windows)
    assert r.design.room("carport").enclosed is False
    kinds = {q.item for q in parse_requirements("an l-shaped living room with a curved wall and a pergola") if q.kind == "feature"}
    assert kinds >= {"l-shaped", "curved wall", "pergola"}

    steps = MockLLM()._edit("make the kitchen L-shaped", r.design)
    assert steps and steps[0]["step"] == "room" and steps[0]["id"] == "kitchen" and len(steps[0]["poly"]) == 6
    steps = MockLLM()._edit("add a pergola", r.design)
    assert {s["kind"] for s in steps} == {"column", "beam", "roof"}
    steps = MockLLM()._edit("add a courtyard", r.design)
    assert steps[0]["kind"] == "courtyard"
