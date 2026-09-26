"""Model-composed shapes (schemas.bim.CustomFixture): furniture the fixed FixtureKind catalog
doesn't cover, built from box/round parts — via the step schema, derivation, and IFC compile."""

import ifcopenshell

from core.derive import DesignError, analyze
from ifc.builder import compile_ifc
from ifc.lifter import lift
from llm.mock import MockLLM
from schemas.bim import CustomFixture
from schemas.design import CustomShapeDef, Design, LevelDef, RoomDef, ShapePartDef
from schemas.steps import Step, apply_step

ROUND_TABLE = [
    ShapePartDef(shape="round", x=0.0, y=0.0, z=0.72, w=1.0, h=0.05),
    ShapePartDef(shape="box", x=0.05, y=0.05, z=0.0, w=0.06, d=0.06, h=0.72),
    ShapePartDef(shape="box", x=0.89, y=0.05, z=0.0, w=0.06, d=0.06, h=0.72),
    ShapePartDef(shape="box", x=0.05, y=0.89, z=0.0, w=0.06, d=0.06, h=0.72),
    ShapePartDef(shape="box", x=0.89, y=0.89, z=0.0, w=0.06, d=0.06, h=0.72),
]


def _design(**kwargs) -> Design:
    rooms = kwargs.pop("rooms")
    return Design(levels=[LevelDef(id="L1")], rooms=rooms, **kwargs)


def test_custom_shape_is_centred_and_placed_like_a_catalog_fixture():
    d = _design(rooms=[RoomDef(id="a", name="Dining Room", kind="dining", rect=(0, 0, 6, 5))],
               custom_shapes=[CustomShapeDef(id="table", room="a", name="Round table", side="center", parts=ROUND_TABLE)])
    derived = analyze(d)
    table = next(e for e in derived.spec.elements if isinstance(e, CustomFixture))
    assert table.position == (3.0, 2.5)  # room centre
    round_part = next(p for p in table.parts if p.shape == "round")
    assert round_part.x == -0.5 and round_part.y == -0.5  # bbox re-centred on the origin


def test_custom_shape_against_a_wall_faces_the_room_like_furniture_does():
    d = _design(rooms=[RoomDef(id="a", name="Study", kind="office", rect=(0, 0, 5, 4))],
               custom_shapes=[CustomShapeDef(id="desk", room="a", name="L-desk", side="S",
                                             parts=[ShapePartDef(shape="box", x=0, y=0, z=0, w=1.4, d=0.6, h=0.75)])])
    derived = analyze(d)
    shape = next(e for e in derived.spec.elements if isinstance(e, CustomFixture))
    assert shape.rotation == 0.0 and shape.position[1] == 0.45  # CLEAR (0.15) + d/2 (0.3), against the south wall


def test_custom_shape_too_big_for_the_room_is_rejected():
    d = _design(rooms=[RoomDef(id="a", name="Closet", kind="storage", rect=(0, 0, 1, 1))],
               custom_shapes=[CustomShapeDef(id="table", room="a", name="Round table", side="center", parts=ROUND_TABLE)])
    try:
        analyze(d)
        assert False, "expected a DesignError"
    except DesignError as exc:
        assert "too small" in str(exc)


def test_step_schema_applies_a_custom_step_and_rejects_bare_furniture_without_parts():
    d = _design(rooms=[RoomDef(id="a", name="Dining Room", kind="dining", rect=(0, 0, 6, 5))])
    step = Step(step="custom", room="a", name="Round table", side="center",
               parts=[p.model_dump() for p in ROUND_TABLE])
    d2, msg = apply_step(d, step)
    assert len(d2.custom_shapes) == 1 and "Round table" in msg
    try:
        apply_step(d, Step(step="custom", room="a", name="No parts"))
        assert False, "expected a StepError"
    except Exception as exc:  # StepError
        assert "parts" in str(exc)


def test_mock_llm_falls_back_to_custom_for_an_uncatalogued_furniture_request():
    d = _design(rooms=[RoomDef(id="a", name="Dining Room", kind="dining", rect=(0, 0, 6, 5))])
    steps = MockLLM()._edit("put a round table in the dining room", d)
    assert steps and steps[0]["step"] == "custom" and steps[0]["parts"]
    d2, _ = apply_step(d, Step.model_validate(steps[0]))
    analyze(d2)  # must actually derive without error


def test_custom_shape_compiles_to_ifc_furniture():
    d = _design(rooms=[RoomDef(id="a", name="Dining Room", kind="dining", rect=(0, 0, 6, 5))],
               custom_shapes=[CustomShapeDef(id="table", room="a", name="Round table", side="center", parts=ROUND_TABLE)])
    model, _ = compile_ifc(analyze(d).spec, {})
    products = model.by_type("IfcFurniture")
    assert len(products) == 1 and products[0].ObjectType == "custom"
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), products[0])
    assert shape.geometry.verts  # tessellates to something real, not an empty solid


def test_custom_shape_survives_the_lift_roundtrip(tmp_path):
    d = _design(rooms=[RoomDef(id="a", name="Dining Room", kind="dining", rect=(0, 0, 6, 5))],
               custom_shapes=[CustomShapeDef(id="table", room="a", name="Round table", side="center", parts=ROUND_TABLE)])
    spec = analyze(d).spec
    model, guids = compile_ifc(spec, {})
    path = tmp_path / "house.ifc"
    model.write(str(path))
    lifted, _design_back, lifted_guids = lift(path)
    by_id = lambda s: sorted((e.model_dump(mode="json") for e in s.elements), key=lambda e: e["id"])  # noqa: E731
    assert by_id(lifted) == by_id(spec)
    assert lifted_guids == guids
