"""Everything the builder can make beyond a house: non-domestic room types, the full fixture
catalogue, free-standing equipment and site objects, shed roofs, railings and external stairs."""

import pytest

from agents.template_planner import TemplatePlanner, typology
from core.derive import analyze
from ifc.builder import compile_ifc
from schemas.bim import FixtureKind, RoofShape
from schemas.design import Design, RoomKind
from schemas.steps import Step, StepError, apply_step


def build(steps: list[dict]) -> Design:
    design = Design()
    for raw in steps:
        design, _ = apply_step(design, Step.model_validate(raw))
    return design


def compile_design(design: Design):
    derived = analyze(design)
    model, _ = compile_ifc(derived.spec, {})
    return derived, model


SHELL = [
    {"step": "building", "name": "Probe"},
    {"step": "level", "id": "L1", "height": 8.0},
]


def test_every_catalogue_fixture_compiles():
    """Each of the ~60 kinds has a size and a solid, in a room and standing free."""
    kinds = list(FixtureKind.__args__)
    steps = SHELL + [{"step": "layout", "level": "L1", "rooms": [{"name": "Shed", "kind": "warehouse", "rect": [0, 0, 60, 30]}]}]
    steps += [{"step": "furniture", "kind": k, "position": [2 + i * 2.5, -8], "level": "L1"} for i, k in enumerate(kinds)]
    steps += [{"step": "furniture", "room": "shed", "kind": k, "side": "N", "at": i / len(kinds)} for i, k in enumerate(kinds)]
    design = build(steps)
    derived, model = compile_design(design)
    assert len([e for e in derived.spec.elements if e.type == "fixture"]) == 2 * len(kinds)
    assert model.by_type("IfcFurniture") and model.by_type("IfcBuildingElementProxy")


@pytest.mark.parametrize("kind", [k for k in RoomKind.__args__ if k != "other"])
def test_every_room_kind_builds(kind):
    design = build(SHELL + [{"step": "layout", "level": "L1", "rooms": [
        {"name": "Subject", "kind": kind, "rect": [0, 0, 12, 10]},
        {"name": "Lobby", "kind": "hall", "rect": [12, 0, 4, 10]}]},
        {"step": "door", "room": "lobby", "to": "outside", "side": "S"}])
    derived, model = compile_design(design)
    assert any(e.type == "space" and e.name == "Subject" for e in derived.spec.elements)
    assert model.by_type("IfcSpace")


@pytest.mark.parametrize("shape", list(RoofShape.__args__))
def test_every_roof_shape_compiles(shape):
    design = build(SHELL + [
        {"step": "layout", "level": "L1", "rooms": [{"name": "Hall", "kind": "hall", "rect": [0, 0, 12, 8]}]},
        {"step": "roof", "kind": shape, "pitch": 20}])
    derived, model = compile_design(design)
    roofs = [e for e in derived.spec.elements if e.type == "roof"]
    assert roofs and roofs[0].shape == shape
    assert model.by_type("IfcRoof")


def test_free_standing_equipment_sits_where_it_is_put():
    design = build(SHELL + [
        {"step": "layout", "level": "L1", "rooms": [{"name": "Shed", "kind": "warehouse", "rect": [0, 0, 20, 20]}]},
        {"step": "furniture", "kind": "solar_panel", "position": [5, 5], "level": "L1", "elevation": 8.0},
        {"step": "furniture", "kind": "bench", "position": [-6, 4], "level": "L1"},
        {"step": "custom", "name": "Totem", "position": [-6, 12], "level": "L1",
         "parts": [{"shape": "box", "w": 0.4, "d": 0.4, "h": 4.0}]}])
    panel = next(f for f in design.fixtures if f.kind == "solar_panel")
    assert panel.room is None and panel.position == (5.0, 5.0) and panel.elevation == 8.0
    derived, model = compile_design(design)
    spec_panel = next(e for e in derived.spec.elements if e.id == panel.id)
    assert spec_panel.position == (5.0, 5.0) and spec_panel.elevation == 8.0
    assert next(e for e in derived.spec.elements if e.type == "custom").position == (-6.0, 12.0)
    assert model.by_type("IfcFurniture")


def test_free_standing_piece_needs_a_position():
    with pytest.raises(StepError, match="needs `position`"):
        build(SHELL + [{"step": "furniture", "kind": "bench", "level": "L1"}])
    with pytest.raises(StepError, match="unknown level"):
        build(SHELL + [{"step": "furniture", "kind": "bench", "level": "L9", "position": [0, 0]}])


def test_free_railing_and_external_stair():
    design = build(SHELL + [
        {"step": "layout", "level": "L1", "rooms": [{"name": "Hall", "kind": "hall", "rect": [0, 0, 10, 8]}]},
        {"step": "element", "kind": "railing", "name": "Site fence", "level": "L1",
         "path": [[-4, -4], [14, -4], [14, 12]], "height": 1.2},
        {"step": "element", "kind": "stair", "name": "Entrance steps", "level": "L1",
         "position": [4, -3], "rotation": 90, "height": 1.2, "width": 1.6}])
    derived, model = compile_design(design)
    rail = next(e for e in derived.spec.elements if e.type == "railing" and e.id == "site-fence")
    assert rail.height == 1.2 and len(rail.path) == 3
    stair = next(e for e in derived.spec.elements if e.type == "stair")
    assert stair.rise == 1.2 and stair.direction == 90.0 and stair.width == 1.6
    assert model.by_type("IfcRailing") and model.by_type("IfcStair")


def test_industrial_openings():
    design = build(SHELL + [
        {"step": "layout", "level": "L1", "rooms": [{"name": "Shed", "kind": "warehouse", "rect": [0, 0, 30, 20]}]},
        {"step": "door", "room": "shed", "to": "outside", "side": "S", "kind": "roller"},
        {"step": "window", "room": "shed", "side": "N", "kind": "clerestory"},
        {"step": "window", "room": "shed", "side": "E", "kind": "ribbon"}])
    derived, model = compile_design(design)
    door = next(e for e in derived.spec.elements if e.type == "door")
    assert door.kind == "roller" and door.width == 4.0
    widths = sorted(e.width for e in derived.spec.elements if e.type == "window")
    assert widths == [3.0, 6.0]
    assert model.by_type("IfcDoor")[0].OperationType == "ROLLINGUP"


@pytest.mark.parametrize("prompt,expected", [
    ("a distribution warehouse with a despatch office", "warehouse"),
    ("a two storey office block with three meeting rooms", "office"),
    ("a primary school with four classrooms", "school"),
    ("a health clinic with a ward", "clinic"),
    ("a corner shop with a stock room", "retail"),
    ("a gym with changing rooms", "gym"),
    ("a 300 seat auditorium with a foyer", "auditorium"),
    ("a machine workshop with a roller door", "workshop"),
    ("a three storey car park", "parking"),
    ("a barn with two stables", "barn"),
    ("a data centre with a plant room", "server"),
])
def test_typologies_build_end_to_end(prompt, expected):
    assert typology(prompt)[0] == expected
    result = TemplatePlanner().plan(prompt)
    model, _ = compile_ifc(result.spec, {})
    assert model.by_type("IfcWall") and model.by_type("IfcSpace") and model.by_type("IfcSlab")
    # Every storey gets a floor plate and every room a space, and nothing was silently dropped.
    assert not [n for n in result.notes if "rejected" in str(n) or "does not fit" in str(n)]


def test_two_storey_house_is_still_a_house():
    """The typology detector must not read "storey" as "store"."""
    assert typology("a two storey house with a basement") is None
    result = TemplatePlanner().plan("a two storey house with a basement, two bedrooms and a kitchen")
    assert result.design.storeys() == 2 and result.design.basements() == 1


def test_site_works_from_a_prompt():
    result = TemplatePlanner().plan("a warehouse with solar panels, a water tank, cycle parking, trees and a loading bay")
    free = {f.kind for f in result.design.fixtures if not f.room}
    assert {"solar_panel", "water_tank", "bicycle_rack"} <= free
    # Trees the prompt names come from the library, placed on the site as bricks.
    assert any(b.brick == "tree" for b in result.design.bricks)
    assert any(e.kind == "slab" and e.name == "Yard" for e in result.design.elements)
    panels = [f for f in result.design.fixtures if f.kind == "solar_panel"]
    assert all(p.elevation > 0 for p in panels), "panels belong on the roof, not the ground"
    compile_ifc(result.spec, {})
