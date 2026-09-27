"""The brick library and the expression language: every brick is a valid IFC4 element whose geometry
evaluates over its whole parameter range, and search finds bricks from plain-language requests."""

import itertools

import pytest

from bricks import PLACEMENT_VARS, library
from bricks.expr import ExprError, evaluate, names_in
from bricks.geometry import bounds
from bricks.model import Brick, predefined_types
from schemas.bim import FixtureKind

CONTEXT = {"ref_w": 12.0, "ref_d": 12.0, "ref_h": 4.0, "path_length": 4.0}


def test_library_is_large_and_uses_every_mount():
    lib = library()
    assert len(lib) >= 150
    assert {b.mount for b in lib.bricks.values()} == {"rest", "fix", "hang", "path"}
    assert all(b.tags for b in lib.bricks.values())


@pytest.mark.parametrize("brick", list(library().bricks.values()), ids=lambda b: b.id)
def test_brick_is_valid_ifc4_and_evaluates_over_its_range(brick: Brick):
    enum = predefined_types(brick.ifc_class)
    if brick.predefined_type is None:
        assert not enum or "NOTDEFINED" in enum
    sized = [p for p in brick.params if p.min is not None and p.max is not None and not p.fit]
    for corner in itertools.product(*[(p.min, p.default, p.max) for p in sized[:4]]):
        values = brick.resolve({p.name: v for p, v in zip(sized, corner)}, CONTEXT)
        x0, y0, z0, x1, y1, z1 = bounds(brick.solids(values))
        assert x1 > x0 and y1 > y0 and z1 > z0
        brick.elevation_of(values)
        brick.keepout_boxes(values)


def test_catalogue_fixture_kinds_all_have_a_brick():
    lib = library()
    assert set(FixtureKind.__args__) == {b.properties["fixture"] for b in lib.bricks.values() if "fixture" in b.properties}


@pytest.mark.parametrize("query,expected", [
    ("somewhere to hang coats", {"coat_closet", "entry_bench"}),
    ("fresh air for the whole house", {"mvhr_unit", "air_handling_unit"}),
    ("solar panels on the roof", {"solar_pv_array"}),
    ("a lift for a wheelchair user", {"passenger_elevator", "platform_lift"}),
    ("sprinklers", {"sprinkler_head"}),
    ("stop the floor sagging", {"steel_beam", "glulam_beam", "steel_column", "timber_joist"}),
    ("loo", {"toilet", "wall_hung_wc"}),
    ("charge my electric car", {"ev_charger"}),
])
def test_search_understands_plain_language(query, expected):
    top = {b.id for b, _ in library().search(query, limit=4)}
    assert top & expected, top


def test_search_can_be_limited_to_a_tag():
    hits = library().search("light", tag="fire")
    assert hits and all("fire" in b.tags for b, _ in hits)


def test_resolve_rejects_unknown_and_out_of_range_params():
    toilet = library().get("toilet")
    with pytest.raises(ValueError, match="no param"):
        toilet.resolve({"colour": 1})
    with pytest.raises(ValueError, match="outside"):
        toilet.resolve({"w": 3.0})
    assert toilet.resolve({"w": 0.45})["w"] == 0.45


def test_fitted_params_follow_the_placement_unless_given():
    column = library().get("steel_column")
    assert column.resolve({}, {"ref_h": 3.2})["h"] == pytest.approx(3.2)
    assert column.resolve({"h": 2.5}, {"ref_h": 3.2})["h"] == 2.5
    with pytest.raises(ValueError, match="outside"):
        column.resolve({}, {"ref_h": 40.0})


def test_expressions_are_arithmetic_only():
    assert evaluate("max(0.3, h / 2) - w", {"h": 1.0, "w": 0.1}) == pytest.approx(0.4)
    assert names_in("w - arm * 2 + sin(a) * pi") == {"w", "arm", "a"}
    for bad in ("__import__('os')", "w.real", "[w for w in x]", "open('f')", "'text'", "w ** 1000"):
        with pytest.raises(ExprError):
            evaluate(bad, {"w": 1.0})
    with pytest.raises(ExprError):
        evaluate("w / 0", {"w": 1.0})


def test_expressions_have_degrees_trig_comparisons_and_conditionals():
    assert evaluate("sin(30)", {}) == pytest.approx(0.5)
    assert evaluate("atan2(1, 1)", {}) == pytest.approx(45)
    assert evaluate("hypot(3, 4)", {}) == 5
    assert evaluate("clamp(n, 1, 3)", {"n": 7}) == 3
    assert evaluate("1 if w > 2 and not h else 0", {"w": 3, "h": 0}) == 1
    assert evaluate("w // 0.5 + w % 0.5", {"w": 1.7}) == pytest.approx(3.2)
    assert evaluate("2 * pi", {}) == pytest.approx(6.283185)


def _brick(**over) -> dict:
    return {"id": "thing", "name": "Thing", "params": {"w": [1, 0.5, 2]}, "geometry": [{"shape": "box", "size": ["w", 1, 1]}]} | over


def test_definitions_are_checked_when_loaded():
    Brick.model_validate(_brick())
    cases = [
        (_brick(geometry=[{"shape": "box", "size": ["width", 1, 1]}]), "unknown names"),
        (_brick(ifc_class="IfcBuildingElement"), "abstract"),
        (_brick(ifc_class="IfcSpace"), "not an IfcElement"),
        (_brick(ifc_class="IfcWall", predefined_type="BANANA"), "no predefined type"),
        (_brick(geometry=[{"shape": "box", "size": [1, 1, 1], "material": "gold"}]), "does not define"),
        (_brick(mount="path"), "path_length"),
        (_brick(id="Thing"), "lower_snake_case"),
        (_brick(params={"w": [5, 0.5, 2]}), "outside"),
        (_brick(params={"w": {"default": 1, "fit": "room_width"}}), "fit may only use"),
    ]
    for data, match in cases:
        with pytest.raises(ValueError, match=match):
            Brick.model_validate(data)


def test_placement_vars_may_be_used_in_geometry():
    brick = Brick.model_validate(_brick(geometry=[{"shape": "box", "size": ["w", 1, "ref_h"]}]))
    assert bounds(brick.solids(brick.resolve({}, {"ref_h": 2.5})))[5] == pytest.approx(2.5)
    assert set(PLACEMENT_VARS) == {"ref_w", "ref_d", "ref_h", "path_length"}


def test_index_text_fits_in_a_prompt():
    text = library().index_text()
    assert "toilet" in text and "steel_beam" in text and len(text) < 4000
