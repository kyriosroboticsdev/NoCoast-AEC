"""Ops edit a GeoModel and the result still compiles."""

import pytest

from core.ops import OpError, apply_ops
from ifc.compile import compile_ifc
from schemas.geo import GeoModel, GeoPart, Profile, Solid
from schemas.ops import Delete, Modify, SetModel


def _wall() -> GeoModel:
    return GeoModel(name="Start", parts=[GeoPart(
        id="wall", name="front", ifc="IfcWall", ifc_type="SOLIDWALL",
        solids=[Solid(op="extrude", profile=Profile(rect=(4, 0.2)), depth=3)],
    )])


def test_rename_move_and_delete():
    geo, notes = apply_ops(_wall(), [SetModel(set={"name": "Hut"}), Modify(id="wall", set={"material": "timber", "at": [1, 0, 0]})])
    assert geo.name == "Hut" and geo.part("wall").material == "timber"
    assert geo.part("wall").place.at[0] == 1
    assert notes
    compile_ifc(geo)
    geo, _ = apply_ops(geo, [Delete(id="wall")])
    assert geo.parts == []


def test_unknown_id_names_a_neighbour():
    with pytest.raises(OpError, match="wall"):
        apply_ops(_wall(), [Delete(id="wal")])
