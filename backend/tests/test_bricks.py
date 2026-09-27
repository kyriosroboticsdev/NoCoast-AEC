"""The brick library: every brick is valid IFC4, its expressions evaluate over its whole parameter
range, and search finds bricks from plain-language requests."""

import itertools

import ifcopenshell.ifcopenshell_wrapper as wrapper
import pytest

from bricks import library
from bricks.expr import ExprError, evaluate, names_in
from bricks.model import Brick

SCHEMA = wrapper.schema_by_name("IFC4")


def _predefined_types(ifc_class: str) -> tuple[str, ...] | None:
    decl = SCHEMA.declaration_by_name(ifc_class)
    for attr in decl.all_attributes():
        if attr.name() == "PredefinedType":
            t = attr.type_of_attribute()
            while hasattr(t, "declared_type"):
                t = t.declared_type()
            return t.enumeration_items()
    return None


def test_library_is_large_and_covers_every_discipline():
    lib = library()
    assert len(lib) >= 150
    assert set(lib.disciplines()) == {"architecture", "interior", "plumbing", "electrical", "hvac", "fire", "structure",
                                      "site", "transport", "energy", "data"}


@pytest.mark.parametrize("brick", list(library().bricks.values()), ids=lambda b: b.id)
def test_brick_is_valid_ifc4_and_evaluates_over_its_range(brick: Brick):
    decl = SCHEMA.declaration_by_name(brick.ifc_class)
    assert decl.is_abstract() is False, f"{brick.ifc_class} is abstract"
    enum = _predefined_types(brick.ifc_class)
    if brick.predefined_type is None:
        assert enum is None or "NOTDEFINED" in enum
    else:
        assert enum and brick.predefined_type in enum, f"{brick.predefined_type} not in {enum}"
    sized = [p for p in brick.params if p.min is not None and p.max is not None]
    for corner in itertools.product(*[(p.min, p.default, p.max) for p in sized[:4]]):
        values = brick.resolve({p.name: v for p, v in zip(sized, corner)})
        values |= {"level_h": 3.0, "length": 4.0}
        solids = brick.solids(values)
        assert solids and all(s[4] > 0 and s[6] > 0 for s in solids)
        brick.mount_height(values)


def test_legacy_fixture_kinds_all_have_a_brick():
    from schemas.bim import FixtureKind
    lib = library()
    assert {k for k in FixtureKind.__args__} == {b.legacy_fixture for b in lib.bricks.values() if b.legacy_fixture}


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


def test_search_can_be_limited_to_a_discipline():
    hits = library().search("light", discipline="fire")
    assert hits and all(b.discipline == "fire" for b, _ in hits)


def test_resolve_rejects_unknown_and_out_of_range_params():
    toilet = library().get("toilet")
    with pytest.raises(ValueError, match="no param"):
        toilet.resolve({"colour": 1})
    with pytest.raises(ValueError, match="outside"):
        toilet.resolve({"w": 3.0})
    assert toilet.resolve({"w": 0.45})["w"] == 0.45


def test_expressions_are_arithmetic_only():
    assert evaluate("max(0.3, h / 2) - w", {"h": 1.0, "w": 0.1}) == pytest.approx(0.4)
    assert names_in("w - arm * 2") == {"w", "arm"}
    for bad in ("__import__('os')", "w.real", "[w for w in x]", "open('f')", "'text'"):
        with pytest.raises(ExprError):
            evaluate(bad, {"w": 1.0})
    with pytest.raises(ExprError):
        evaluate("w / 0", {"w": 1.0})


def test_brick_with_unknown_expression_name_is_refused_at_load():
    with pytest.raises(ValueError, match="unknown names"):
        Brick.model_validate({"id": "bad", "name": "Bad", "discipline": "interior", "category": "x", "ifc_class": "IfcFurniture",
                              "params": {"w": [1, 0.5, 2], "d": [1, 0.5, 2], "h": [1, 0.5, 2]}, "parts": [[0, 0, 0, "width", "d", "h"]]})


def test_index_text_fits_in_a_prompt():
    text = library().index_text()
    assert "toilet" in text and "steel_beam" in text and len(text) < 4000
