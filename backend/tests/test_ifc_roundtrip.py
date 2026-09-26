"""Compile → lift round trip, and GlobalId stability across an edit."""

import ifcopenshell

from core.guids import ensure_guids, key_for_element, prune_guids
from core.ops import apply_ops
from ifc.builder import compile_ifc, write_ifc
from ifc.lifter import lift
from schemas.ops import DeleteElement, ModifyElement
from solver.layout import solve
from agents.template_planner import parse_program


def test_lift_roundtrip(tmp_path):
    spec = solve(parse_program("two storey house with a garage, a kitchen, a living room and two bedrooms"))
    path = tmp_path / "house.ifc"
    write_ifc(spec, path)
    lifted, guids = lift(path)
    by_id = lambda s: sorted((e.model_dump(mode="json") for e in s.elements), key=lambda e: e["id"])  # noqa: E731
    assert by_id(lifted) == by_id(spec)
    assert lifted.levels == spec.levels and lifted.building == spec.building
    model = ifcopenshell.open(str(path))
    wall = next(w for w in model.by_type("IfcWall") if w.Tag == "L1-wall-S")
    assert guids[key_for_element("L1-wall-S")] == wall.GlobalId
    assert guids["building"] == model.by_type("IfcBuilding")[0].GlobalId
    # Every product got a spec pset and its GlobalId is in the map.
    assert set(guids) == set(ensure_guids(spec, {}))


def test_guids_survive_edits(tmp_path):
    spec = solve(parse_program("one storey cabin"))
    model1, guids1 = compile_ifc(spec, {})
    spec2, _ = apply_ops(spec, [ModifyElement(id="L1-wall-S", set={"thickness": 0.4}), DeleteElement(id="L1-win-N1")])
    model2, guids2 = compile_ifc(spec2, guids1)
    guids2 = prune_guids(spec2, guids2)

    def gid(model, tag):
        return next(p.GlobalId for p in model.by_type("IfcElement") if p.Tag == tag)

    assert gid(model1, "L1-wall-S") == gid(model2, "L1-wall-S")  # modified in place, same GlobalId
    assert gid(model1, "L1-floor") == gid(model2, "L1-floor")    # untouched
    assert key_for_element("L1-win-N1") not in guids2               # deleted ids are dropped
    assert model1.by_type("IfcProject")[0].GlobalId == model2.by_type("IfcProject")[0].GlobalId
    ids2 = [p.GlobalId for p in model2.by_type("IfcRoot")]
    assert len(ids2) == len(set(ids2))
