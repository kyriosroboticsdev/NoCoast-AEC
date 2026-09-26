"""Compile → lift round trip, and GlobalId stability across an edit."""

import ifcopenshell

from agents.template_planner import TemplatePlanner
from core.guids import ensure_guids, key_for_element, prune_guids
from core.ops import apply_ops
from ifc.builder import compile_ifc, write_ifc
from ifc.lifter import lift
from schemas.ops import DeleteElement, ModifyElement


def test_lift_roundtrip(tmp_path):
    plan = TemplatePlanner().plan("two storey house with a garage, a kitchen, a living room and two bedrooms and a gable roof")
    spec, design = plan.spec, plan.design
    path = tmp_path / "house.ifc"
    write_ifc(spec, path, design_json=design.model_dump_json())
    lifted, lifted_design, guids = lift(path)
    by_id = lambda s: sorted((e.model_dump(mode="json") for e in s.elements), key=lambda e: e["id"])  # noqa: E731
    assert by_id(lifted) == by_id(spec)
    assert lifted.levels == spec.levels and lifted.building == spec.building
    assert lifted_design == design
    model = ifcopenshell.open(str(path))
    wall = next(w for w in model.by_type("IfcWall") if w.Tag == "L1-wall-hall-W")
    assert guids[key_for_element("L1-wall-hall-W")] == wall.GlobalId
    assert guids["building"] == model.by_type("IfcBuilding")[0].GlobalId
    # Every product got a spec pset and its GlobalId is in the map (incl. the stair well opening).
    assert set(guids) == set(ensure_guids(spec, {}))
    assert {e.type for e in spec.elements} >= {"wall", "slab", "space", "roof", "door", "window", "stair", "fixture"}


def test_guids_survive_edits(tmp_path):
    spec = TemplatePlanner().plan("one storey cabin").spec
    model1, guids1 = compile_ifc(spec, {})
    spec2, _ = apply_ops(spec, [ModifyElement(id="L1-wall-hall-S", set={"thickness": 0.4}), DeleteElement(id="win-kitchen-W")])
    model2, guids2 = compile_ifc(spec2, guids1)
    guids2 = prune_guids(spec2, guids2)

    def gid(model, tag):
        return next(p.GlobalId for p in model.by_type("IfcElement") if p.Tag == tag)

    assert gid(model1, "L1-wall-hall-S") == gid(model2, "L1-wall-hall-S")  # modified in place, same GlobalId
    assert gid(model1, "L1-floor") == gid(model2, "L1-floor")              # untouched
    assert key_for_element("win-kitchen-W") not in guids2                    # deleted ids are dropped
    assert model1.by_type("IfcProject")[0].GlobalId == model2.by_type("IfcProject")[0].GlobalId
    ids2 = [p.GlobalId for p in model2.by_type("IfcRoot")]
    assert len(ids2) == len(set(ids2))
