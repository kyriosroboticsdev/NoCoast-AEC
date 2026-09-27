from ifc.compile import compile_ifc
from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, apply_step
from slicer.gcode import to_gcode
from slicer.slice import PHASES, slice_model


def _cabin():
    geo = GeoModel()
    for raw in (
        {"step": "part", "id": "slab", "name": "floor", "ifc": "IfcSlab", "ifc_type": "FLOOR",
         "solid": {"op": "extrude", "depth": 0.2, "profile": {"points": [[0, 0], [6, 0], [6, 4], [0, 4]]}}},
        {"step": "part", "id": "wall", "name": "wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
         "solid": {"wall": [[0, 0], [6, 0], [6, 4], [0, 4]], "thickness": 0.2, "height": 3}},
        {"step": "part", "id": "roof", "name": "roof", "ifc": "IfcRoof", "ifc_type": "FLAT_ROOF", "at": [0, 0, 3],
         "solid": {"op": "extrude", "depth": 0.2, "profile": {"points": [[0, 0], [6, 0], [6, 4], [0, 4]]}}},
    ):
        geo, _ = apply_step(geo, GeoStep.model_validate(raw))
    return compile_ifc(geo)[0]


def test_slices_are_grouped_and_ordered_by_construction_phase():
    model = _cabin()
    layers = slice_model(model, layer_height=0.5)
    assert len(layers) > 1
    phase_order = [label for label, _ in PHASES]
    seen = [l.phase for l in layers]
    runs = [p for i, p in enumerate(seen) if i == 0 or p != seen[i - 1]]
    assert runs == sorted(runs, key=phase_order.index)
    assert set(runs) <= set(phase_order)
    for label in set(seen):
        zs = [l.z for l in layers if l.phase == label]
        assert zs == sorted(zs)
    structure = [l for l in layers if l.phase == "structure"]
    assert structure and any(l.segments for l in structure)


def test_slice_is_empty_for_a_model_with_no_geometry():
    import ifcopenshell
    assert slice_model(ifcopenshell.file()) == []


def test_gcode_has_a_move_per_segment():
    layers = slice_model(_cabin(), layer_height=0.5)
    gcode = to_gcode(layers)
    assert gcode.count("G1 ") == sum(len(l.segments) for l in layers)
