"""The generic compiler: every solid op, an opening, a repeat and an instance, all tessellated."""

import math

import ifcopenshell.geom

from ifc.compile import compile_ifc, summarize
from schemas.geo import (GeoAssembly, GeoInstance, GeoLevel, GeoModel, GeoOpening, GeoPart, Placement, Profile,
                         Repeat, Solid)
from schemas.geosteps import GeoStep, apply_step


def _tessellated(model) -> dict[str, int]:
    settings = ifcopenshell.geom.settings()
    counts = {}
    for product in model.by_type("IfcProduct"):
        if not getattr(product, "Representation", None) or product.is_a("IfcOpeningElement"):
            continue
        shape = ifcopenshell.geom.create_shape(settings, product)
        assert shape.geometry.verts, product.Name
        counts[product.is_a()] = counts.get(product.is_a(), 0) + 1
    return counts


def _part(pid, ifc, solid, **kw) -> GeoPart:
    return GeoPart(id=pid, name=kw.pop("name", pid), ifc=ifc, solids=[solid], **kw)


def test_extruded_wall_opens_and_tessellates(tmp_path):
    geo = GeoModel(name="wall", parts=[_part("w", "IfcWall", Solid(op="extrude", profile=Profile(rect=(6, 0.2)), depth=3),
                                           ifc_type="SOLIDWALL", material="masonry")])
    model, guids = compile_ifc(geo)
    assert model.schema == "IFC4"
    assert summarize(model)["counts"] == {"IfcWall": 1}
    assert _tessellated(model) == {"IfcWall": 1}
    assert model.by_type("IfcBuildingStorey")[0].Description == "L1"
    building = model.by_type("IfcBuilding")[0]
    psets = [rel.RelatingPropertyDefinition.Name for rel in building.IsDefinedBy or [] if rel.is_a("IfcRelDefinesByProperties")]
    assert "NoCoast_Model" in psets
    assert guids["building"] == building.GlobalId


def test_revolve_sweep_and_mesh(tmp_path):
    dome_pts = [[round(4 * math.cos(a), 4), round(4 * math.sin(a), 4)]
                for a in [(-math.pi / 2) + math.pi * i / 12 for i in range(13)]]
    vault_pts = [[round(5 * math.cos(a), 4), round(2.5 * math.sin(a), 4)] for a in [math.pi * i / 8 for i in range(9)]]
    geo = GeoModel(name="curved", parts=[
        _part("dome", "IfcRoof", Solid(op="revolve", place=Placement(axis=(0, -1, 0)), profile=Profile(points=dome_pts),
                                       angle=360, axis_dir=(0, 1)), ifc_type="DOME_ROOF"),
        _part("vault", "IfcRoof", Solid(op="revolve", profile=Profile(points=vault_pts), angle=180, axis_dir=(1, 0)),
              ifc_type="BARREL_ROOF", name="barrel vault"),
        _part("deck", "IfcSlab", Solid(op="sweep", profile=Profile(rect=(4, 0.3)),
                                       path=[[i, round(2 * math.sin(i / 8), 4), 6] for i in range(0, 25, 5)]),
              ifc_type="FLOOR", name="curved deck"),
        _part("hip", "IfcRoof", Solid(op="mesh", faces=[
            [[0, 0, 0], [4, 0, 0], [4, 3, 0], [0, 3, 0]],
            [[0, 0, 2], [0, 3, 2], [4, 3, 2], [4, 0, 2]],
            [[0, 0, 0], [0, 0, 2], [4, 0, 2], [4, 0, 0]],
            [[4, 0, 0], [4, 0, 2], [4, 3, 2], [4, 3, 0]],
            [[4, 3, 0], [4, 3, 2], [0, 3, 2], [0, 3, 0]],
            [[0, 3, 0], [0, 3, 2], [0, 0, 2], [0, 0, 0]],
        ]), ifc_type="HIP_ROOF"),
    ])
    model, _ = compile_ifc(geo)
    assert _tessellated(model)["IfcRoof"] == 3 and _tessellated(model)["IfcSlab"] == 1


def test_repeat_opening_and_instance():
    geo = GeoModel(
        name="composed",
        levels=[GeoLevel(id="L1", height=4)],
        parts=[
            _part("tread", "IfcStair", Solid(op="extrude", place=Placement(at=(0.5, 0, 0)), profile=Profile(rect=(0.9, 0.28)), depth=0.04),
                  ifc_type="SPIRAL_STAIR", name="helical stair", repeat=Repeat(count=12, translate=(0, 0, 0.18), rotate=20, about=(0, 0))),
            _part("wall", "IfcWall", Solid(op="extrude", profile=Profile(rect=(5, 0.2)), depth=3), ifc_type="SOLIDWALL"),
            _part("door", "IfcDoor", Solid(op="extrude", profile=Profile(rect=(0.9, 0.05)), depth=2.1), ifc_type="DOOR",
                  place=Placement(at=(-1.5, 0, 0))),
            _part("col", "IfcColumn", Solid(op="extrude", profile=Profile(rect=(0.4, 0.4)), depth=4), ifc_type="COLUMN"),
        ],
        openings=[GeoOpening(id="door-void", host="wall", along=0.4, width=0.9, height=2.1, fill="door")],
        assemblies=[GeoAssembly(id="bay", name="bay", parts=["col"])],
        instances=[GeoInstance(id="row", of="bay", repeat=Repeat(count=3, translate=(4, 0, 0)))],
    )
    model, _ = compile_ifc(geo)
    counts = summarize(model)["counts"]
    assert counts["IfcStair"] == 1 and counts["IfcColumn"] == 4  # one authored, three instanced
    assert counts["IfcElementAssembly"] == 4
    assert model.by_type("IfcOpeningElement")
    assert _tessellated(model)["IfcWall"] == 1


def test_step_sugar_compiles():
    model = GeoModel()
    model, msg = apply_step(model, GeoStep.model_validate({
        "step": "part", "id": "front", "name": "front wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
        "solid": {"wall": [[0, 0], [8, 0], [8, 5]], "thickness": 0.2, "height": 3},
    }))
    assert "IfcWall" in msg
    ifc, _ = compile_ifc(model)
    assert _tessellated(ifc) == {"IfcWall": 1}
