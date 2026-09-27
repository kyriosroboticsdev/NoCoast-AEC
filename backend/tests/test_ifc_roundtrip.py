"""Compile, lift, and keep GlobalIds across an edit."""

import ifcopenshell

from core.guids import key_for_part
from core.ops import apply_ops
from ifc.compile import compile_ifc
from ifc.lifter import lift
from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, apply_step
from schemas.ops import Delete, Modify


def _house(tmp_path):
    geo = GeoModel(name="Hut")
    for raw in (
        {"step": "part", "id": "wall", "name": "front", "ifc": "IfcWall", "ifc_type": "SOLIDWALL", "material": "masonry",
         "solid": {"wall": [[0, 0], [6, 0]], "thickness": 0.2, "height": 3}},
        {"step": "part", "id": "door", "name": "door", "ifc": "IfcDoor", "ifc_type": "DOOR",
         "solid": {"box": [0.9, 0.05, 2.1]}},
        {"step": "opening", "id": "door-void", "host": "wall", "along": 1, "width": 0.9, "height": 2.1, "fill": "door"},
    ):
        geo, _ = apply_step(geo, GeoStep.model_validate(raw))
    model, guids = compile_ifc(geo)
    path = tmp_path / "hut.ifc"
    model.write(str(path))
    return geo, guids, path


def test_lift_roundtrip(tmp_path):
    geo, guids, path = _house(tmp_path)
    lifted, lifted_guids = lift(path)
    assert lifted.name == "Hut"
    assert {p.id for p in lifted.parts} == {p.id for p in geo.parts}
    assert lifted.part("wall").material == "masonry"
    wall = ifcopenshell.open(str(path)).by_type("IfcWall")[0]
    assert lifted_guids[key_for_part("wall")] == wall.GlobalId == guids[key_for_part("wall")]


def test_guids_survive_edits(tmp_path):
    geo, guids, _ = _house(tmp_path)
    model1, _ = compile_ifc(geo, guids)
    edited, _ = apply_ops(geo, [Modify(id="wall", set={"material": "timber"}), Delete(id="door")])
    model2, guids2 = compile_ifc(edited, guids)
    assert model1.by_type("IfcWall")[0].GlobalId == model2.by_type("IfcWall")[0].GlobalId
    assert not model2.by_type("IfcDoor")
    assert guids2[key_for_part("wall")] == guids[key_for_part("wall")]
