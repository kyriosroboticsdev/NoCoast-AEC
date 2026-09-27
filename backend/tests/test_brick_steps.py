"""Placing library bricks: the `brick` step, derivation per host, and the IFC compile."""

import ifcopenshell.util.element
import pytest

from bricks import library
from core.construction import build_order
from core.context import describe_design, describe_focus
from core.derive import DesignError, analyze, derive
from ifc.builder import check_geometry, compile_ifc
from schemas.bim import Asset, BuildingSpec
from schemas.design import UNROOFED_KINDS, UNWALLED_KINDS, Design
from schemas.steps import Step, StepError, apply_step


def _design(*steps) -> Design:
    d = Design(name="t")
    for s in steps:
        d, _ = apply_step(d, Step(**s))
    return d


def _house(*extra) -> Design:
    return _design(dict(step="room", name="Kitchen", rect=[0, 0, 5, 4]), dict(step="room", name="Living", rect=[5, 0, 6, 4]), *extra)


def _assets(design: Design) -> dict[str, Asset]:
    spec, _ = derive(design)
    return {e.id: e for e in spec.elements if isinstance(e, Asset)}


def _placement(brick) -> dict:
    """Arguments that place `brick` with its defaults in a roomy single-storey building."""
    if brick.host == "site_span":
        return {"start": [-12, 2], "end": [-12, 8]}
    if brick.host == "span":
        return {"start": [1, 6], "end": [7, 6]}
    if brick.host == "roof":
        return {}
    if brick.host == "site":
        return {"position": [-12, 6]}
    if brick.host == "free":
        return {"room": "hall", "position": [6, 6]}
    return {"room": "hall"}


def test_every_brick_places_with_defaults_and_compiles_to_valid_ifc():
    lib = library()
    els, failures = [], []
    for brick in lib.bricks.values():
        kinds = brick.rules.rooms or ["living"]
        kind = next((k for k in kinds if k not in UNWALLED_KINDS + UNROOFED_KINDS), kinds[0])
        d = _design(dict(step="level", id="L1", height=4.0), dict(step="room", name="Hall", kind=kind, rect=[0, 0, 12, 12]))
        try:
            d, _ = apply_step(d, Step(step="brick", brick=brick.id, id=f"b-{brick.id}", **_placement(brick)))
            spec, _ = derive(d)
        except (StepError, DesignError) as exc:
            failures.append(f"{brick.id}: {exc}")
            continue
        els += [e for e in spec.elements if isinstance(e, Asset)]
        if not els or els[-1].brick != brick.id:
            failures.append(f"{brick.id}: no asset derived")
    assert not failures, failures
    spec = BuildingSpec(building={"name": "all bricks"}, levels=[{"id": "L1", "name": "Ground", "height": 4.0, "elevation": 0}], elements=els)
    model, _ = compile_ifc(spec)
    assert check_geometry(model) == []
    compiled = {ifcopenshell.util.element.get_pset(p, "NoCoast_Brick", "Brick") for p in model.by_type("IfcProduct")}
    assert set(lib.bricks) <= compiled


def test_floor_brick_goes_against_the_named_wall_facing_into_the_room():
    a = _assets(_house(dict(step="brick", brick="fridge", room="kitchen", side="N")))["fridge-kitchen"]
    assert a.ifc_class == "IfcElectricAppliance" and a.predefined_type == "FRIDGE_FREEZER"
    assert a.rotation == 180 and a.position[1] > 3 and a.elevation == 0
    assert "power:in" in [p.label for p in a.ports]


def test_wall_brick_is_lifted_to_its_mount_height():
    a = _assets(_house(dict(step="brick", brick="radiator", room="living", side="S")))["radiator-living"]
    brick = library().get("radiator")
    assert a.elevation == pytest.approx(brick.mount_height(brick.resolve()))
    assert a.position[1] < 1


def test_ceiling_brick_hangs_under_the_ceiling():
    a = _assets(_house(dict(step="brick", brick="supply_diffuser", room="living")))["supply-diffuser-living"]
    assert a.elevation + a.size[2] == pytest.approx(3.0 - 0.2)
    assert a.position == (8.0, 2.0)


def test_roof_brick_sits_on_the_top_roof_and_must_fit_on_it():
    a = _assets(_house(dict(step="brick", brick="solar_pv_array")))["solar-pv-array-l1"]
    assert a.elevation == pytest.approx(3.25) and a.position == (5.5, 2.0)
    with pytest.raises(DesignError, match="off the roof"):
        derive(_house(dict(step="brick", brick="solar_pv_array", position=[20, 20])))


def test_span_brick_runs_between_its_points_at_the_top_of_the_storey():
    a = _assets(_house(dict(step="brick", brick="steel_beam", start=[5.5, 1], end=[5.5, 3.5])))["steel-beam-l1"]
    assert a.position == (5.5, 2.25) and a.rotation == 90
    assert a.size[0] == pytest.approx(2.5)
    assert a.elevation + a.size[2] == pytest.approx(3.0)


def test_full_height_brick_takes_the_storey_height_and_footings_go_below_ground():
    assets = _assets(_house(dict(step="level", id="L1", height=3.4),
                            dict(step="brick", brick="steel_column", room="living", position=[8, 2]),
                            dict(step="brick", brick="pad_footing", position=[8, 2])))
    assert assets["steel-column-living"].size[2] == pytest.approx(3.4)
    footing = assets["pad-footing-l1"]
    assert footing.elevation == pytest.approx(-footing.size[2])


def test_exterior_brick_must_stand_clear_of_the_building():
    assert _assets(_house(dict(step="brick", brick="tree", position=[-4, 2])))["tree-l1"].phase == "site"
    with pytest.raises(DesignError, match="overlaps the building"):
        derive(_house(dict(step="brick", brick="tree", position=[3, 2])))


@pytest.mark.parametrize("step, match", [
    (dict(step="brick", brick="toaster_9000", room="kitchen"), "no brick 'toaster_9000'"),
    (dict(step="brick", brick="fridge"), "give `room`"),
    (dict(step="brick", brick="tree", room="kitchen"), "outside the building.*drop `room`"),
    (dict(step="brick", brick="steel_beam", start=[0, 0]), "give `end`"),
        (dict(step="brick", brick="hedge"), "give `start` and `end`"),
    (dict(step="brick", brick="fridge", room="kitchen", params={"w": 9}), "outside"),
    (dict(step="brick", brick="fridge", room="kitchen", params={"colour": 1}), "no param 'colour'"),
    (dict(step="brick", brick="air_source_heat_pump"), "give `position`"),
])
def test_bad_brick_steps_are_rejected_with_a_message_for_the_model(step, match):
    with pytest.raises(StepError, match=match):
        apply_step(_house(), Step(**step))


def test_unknown_brick_suggests_close_matches():
    with pytest.raises(StepError, match="closest: .*fridge"):
        apply_step(_house(), Step(step="brick", brick="refrigerator", room="kitchen"))


def test_one_per_building_and_ground_only_rules():
    one = next(b for b in library().bricks.values() if b.rules.one_per_building)
    d = _house(dict(step="brick", brick=one.id, **_placement_for(one)))
    with pytest.raises(StepError, match="one per building"):
        apply_step(d, Step(step="brick", brick=one.id, **_placement_for(one)))


def _placement_for(brick) -> dict:
    if brick.host == "site":
        return {"position": [-6, 2]}
    if brick.host == "roof":
        return {}
    return {"room": "living", **({"position": [8, 2]} if brick.host == "free" else {})}


def test_params_resize_the_brick():
    a = _assets(_house(dict(step="brick", brick="kitchen_counter", room="kitchen", side="S", params=[{"name": "w", "value": 3.0}])))
    assert next(iter(a.values())).size[0] == pytest.approx(3.0)


def test_removing_a_room_removes_its_bricks_and_a_brick_can_be_removed_by_id():
    d = _house(dict(step="brick", brick="fridge", room="kitchen", side="N"), dict(step="brick", brick="tree", position=[-4, 2]))
    d2, msg = apply_step(d, Step(step="remove", id="kitchen"))
    assert [b.id for b in d2.bricks] == ["tree-l1"]
    d3, msg = apply_step(d, Step(step="remove", id="tree-l1"))
    assert msg == "removed brick tree-l1" and [b.id for b in d3.bricks] == ["fridge-kitchen"]


def test_bricks_that_no_longer_fit_are_pruned():
    d = _house(dict(step="brick", brick="dining_table", room="living"))
    d.rooms[1].rect = (5.0, 0.0, 1.0, 1.0)
    derived = analyze(d, prune=True)
    assert any("dining-table-living" in p for p in derived.pruned)


def test_a_room_with_water_bricks_gets_a_plumbing_riser():
    spec, _ = derive(_house(dict(step="brick", brick="washing_machine", room="living", side="N")))
    risers = [e for e in spec.elements if e.type == "pipe" and e.kind == "water"]
    assert (8.0, 2.0) in [r.position for r in risers]


def test_construction_order_puts_bricks_in_their_own_phase():
    spec, _ = derive(_house(dict(step="brick", brick="pad_footing", position=[8, 2]), dict(step="brick", brick="tree", position=[-4, 2])))
    order = [e.id for e in build_order(spec)]
    assert order.index("pad-footing-l1") < order.index("L1-wall-kitchen-W")
    assert order[-1] == "tree-l1"


def test_context_lists_bricks_footprint_and_focus():
    d = _house(dict(step="brick", brick="fridge", room="kitchen", side="N"))
    text = describe_design(d, analyze(d))
    assert "bricks: fridge-kitchen fridge in kitchen side=N" in text
    assert "footprint: L1 x 0..11 y 0..4" in text
    assert "fridge freezer" in describe_focus(d, "fridge-kitchen")
