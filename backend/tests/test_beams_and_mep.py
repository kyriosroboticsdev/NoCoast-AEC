"""Beams (core/derive.py's ring-beam pass) and electrical/plumbing rough-in (core/derive.py::_mep).
Both are always-derived — the design never has to ask for them, same as roofs and garage doors."""

import ifcopenshell

from core.derive import analyze, derive
from ifc.builder import compile_ifc
from ifc.lifter import lift
from schemas.bim import Beam, LightFixture, Outlet, Panel, Pipe, Wire
from schemas.design import Design, LevelDef, RoomDef


def _design(**kwargs) -> Design:
    levels = kwargs.pop("levels", [LevelDef(id="L1")])
    return Design(levels=levels, rooms=kwargs.pop("rooms"), **kwargs)


def test_a_beam_runs_along_every_exterior_wall_but_not_partitions():
    d = analyze(_design(rooms=[
        RoomDef(id="a", name="A", kind="living", rect=(0, 0, 4, 4)),
        RoomDef(id="b", name="B", kind="kitchen", rect=(4, 0, 4, 4)),
    ]))
    beams = [e for e in d.spec.elements if isinstance(e, Beam)]
    walls = {e.id: e for e in d.spec.elements if e.type == "wall"}
    beamed_walls = {b.id.removesuffix("-beam") for b in beams}
    assert beamed_walls == {w.id for w in walls.values() if w.external}
    assert "L1-wall-a+b-beam" not in {b.id for b in beams}  # the shared partition gets no beam


def test_beam_sits_at_the_top_of_its_level():
    d = analyze(_design(levels=[LevelDef(id="L1", height=2.8)], rooms=[RoomDef(id="a", name="A", kind="living", rect=(0, 0, 5, 4))]))
    beam = next(e for e in d.spec.elements if isinstance(e, Beam))
    model, _ = compile_ifc(d.spec, {})
    product = next(p for p in model.by_type("IfcBeam") if p.Tag == beam.id)
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), product)
    zs = shape.geometry.verts[2::3]
    assert max(zs) == 2.8 and min(zs) > 2.4  # hangs from the level's own top, not the ground


def test_every_room_gets_a_light_and_two_outlets():
    d = analyze(_design(rooms=[RoomDef(id="a", name="A", kind="living", rect=(0, 0, 5, 4)),
                              RoomDef(id="b", name="B", kind="office", rect=(5, 0, 5, 4))]))
    assert len([e for e in d.spec.elements if isinstance(e, LightFixture)]) == 2
    assert len([e for e in d.spec.elements if isinstance(e, Outlet)]) == 4


def test_kitchen_or_bathroom_gets_a_water_riser_others_dont():
    dry = analyze(_design(rooms=[RoomDef(id="a", name="A", kind="office", rect=(0, 0, 5, 4))]))
    assert not [e for e in dry.spec.elements if isinstance(e, Pipe) and e.kind == "water"]

    wet = analyze(_design(rooms=[RoomDef(id="a", name="A", kind="bathroom", rect=(0, 0, 5, 4))]))
    water = [e for e in wet.spec.elements if isinstance(e, Pipe) and e.kind == "water"]
    assert len(water) == 1 and water[0].bottom_level == "L1"


def test_every_wet_room_gets_its_own_riser_not_just_the_first():
    d = analyze(_design(rooms=[
        RoomDef(id="a", name="Kitchen", kind="kitchen", rect=(0, 0, 5, 4)),
        RoomDef(id="b", name="Bathroom 1", kind="bathroom", rect=(5, 0, 4, 4)),
        RoomDef(id="c", name="Bathroom 2", kind="bathroom", rect=(9, 0, 4, 4)),
    ]))
    water = [e for e in d.spec.elements if isinstance(e, Pipe) and e.kind == "water"]
    assert len(water) == 3
    assert len({w.position for w in water}) == 3  # each riser taps its own room, not a shared point


def test_panel_prefers_a_utility_or_garage_room_over_the_first_room_found():
    d = analyze(_design(rooms=[
        RoomDef(id="a", name="Living Room", kind="living", rect=(0, 0, 5, 4)),
        RoomDef(id="b", name="Garage", kind="garage", rect=(5, 0, 5, 5)),
    ]))
    panel = next(e for e in d.spec.elements if isinstance(e, Panel))
    assert 5 <= panel.position[0] <= 10 and 0 <= panel.position[1] <= 5  # inside the garage, not the living room


def test_outlet_wire_ends_at_the_outlet_height_not_the_ceiling():
    d = analyze(_design(rooms=[RoomDef(id="a", name="A", kind="living", rect=(0, 0, 5, 4))]))
    outlet = next(e for e in d.spec.elements if isinstance(e, Outlet))
    wire = next(e for e in d.spec.elements if isinstance(e, Wire) and e.id.startswith(f"{outlet.level}-wire-a-outlet"))
    assert wire.elevation == outlet.height  # the run reaches the outlet instead of floating at ceiling height


def test_electrical_riser_and_panel_always_present_and_span_every_storey():
    d = analyze(_design(levels=[LevelDef(id="L1"), LevelDef(id="L2"), LevelDef(id="L3")],
                        rooms=[RoomDef(id="a", name="A", level="L1", kind="office", rect=(0, 0, 5, 4)),
                               RoomDef(id="b", name="B", level="L3", kind="bedroom", rect=(0, 0, 5, 4))]))
    panels = [e for e in d.spec.elements if isinstance(e, Panel)]
    riser = next(e for e in d.spec.elements if isinstance(e, Pipe) and e.kind == "electrical")
    assert len(panels) == 1 and riser.bottom_level == "L1" and riser.top_level == "L3"
    # every level has at least one wire, so the top-floor bedroom really is wired, not just the ground floor
    wired_levels = {e.level for e in d.spec.elements if isinstance(e, Wire)}
    assert wired_levels == {"L1", "L3"}


def test_no_degenerate_zero_length_wire_when_a_room_sits_on_the_riser_tap():
    # a room at the exact origin makes its own outlet position coincide with the riser tap
    d = analyze(_design(rooms=[RoomDef(id="a", name="A", kind="living", rect=(0, 0, 4, 4))]))
    for w in d.spec.elements:
        if isinstance(w, Wire):
            assert w.path[0] != w.path[1]


def test_mep_and_beams_compile_to_the_expected_ifc_classes():
    d = analyze(_design(rooms=[RoomDef(id="a", name="A", kind="kitchen", rect=(0, 0, 5, 4))]))
    model, _ = compile_ifc(d.spec, {})
    assert model.by_type("IfcBeam")
    assert model.by_type("IfcLightFixture")
    assert model.by_type("IfcOutlet")
    assert model.by_type("IfcElectricDistributionBoard")
    assert model.by_type("IfcCableSegment")            # branch wiring
    assert model.by_type("IfcCableCarrierSegment")      # electrical riser
    assert model.by_type("IfcPipeSegment")              # water riser (kitchen)


def test_mep_and_beams_survive_the_lift_roundtrip(tmp_path):
    d = analyze(_design(rooms=[RoomDef(id="a", name="A", kind="bathroom", rect=(0, 0, 5, 4))]))
    path = tmp_path / "house.ifc"
    model, guids = compile_ifc(d.spec, {})
    model.write(str(path))
    lifted, _design_back, lifted_guids = lift(path)
    by_id = lambda s: sorted((e.model_dump(mode="json") for e in s.elements), key=lambda e: e["id"])  # noqa: E731
    assert by_id(lifted) == by_id(d.spec)
    assert lifted_guids == guids
