from ifc.builder import compile_ifc
from slicer.gcode import to_gcode
from slicer.slice import PHASES, slice_model
from agents.template_planner import TemplatePlanner


def test_slices_are_grouped_and_ordered_by_construction_phase():
    spec = TemplatePlanner().plan("one storey cabin").spec
    model, _ = compile_ifc(spec)
    layers = slice_model(model, layer_height=0.5)

    assert len(layers) > 1
    phase_order = [label for label, _ in PHASES]
    seen = [l.phase for l in layers]
    # phases appear as contiguous runs, in build order (foundation, structure, roof, spaces, details)
    runs = [p for i, p in enumerate(seen) if i == 0 or p != seen[i - 1]]
    assert runs == sorted(runs, key=phase_order.index)
    assert set(runs) <= set(phase_order)
    # within each phase the layer heights climb bottom to top
    for label in set(seen):
        zs = [l.z for l in layers if l.phase == label]
        assert zs == sorted(zs)
    # a mid-wall-height layer in the structure phase must cross some wall geometry
    structure = [l for l in layers if l.phase == "structure"]
    mid = min(structure, key=lambda l: abs(l.z - spec.levels[0].height / 2))
    assert mid.segments


def test_slice_is_empty_for_a_model_with_no_geometry():
    import ifcopenshell

    assert slice_model(ifcopenshell.file()) == []


def test_gcode_has_a_move_per_segment():
    spec = TemplatePlanner().plan("one storey cabin").spec
    model, _ = compile_ifc(spec)
    layers = slice_model(model, layer_height=0.5)
    gcode = to_gcode(layers)

    assert gcode.count("G1 ") == sum(len(l.segments) for l in layers)
