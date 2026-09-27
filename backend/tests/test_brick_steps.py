"""Placing bricks: the `brick` and `asset` steps, generic placement against frames, and the IFC compile."""

import json

import ifcopenshell.util.element
import pytest

from bricks import library
from core.construction import build_order, phase_of
from core.context import describe_design, describe_focus
from core.derive import DesignError, analyze, derive
from ifc.builder import check_geometry, compile_ifc
from schemas.bim import Asset, BuildingSpec
from schemas.design import Design
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
    """Arguments that place `brick` with its defaults in or around a roomy single-storey building."""
    outdoor = "outdoor" in brick.tags
    if "foundations" in brick.tags:   # below the ground, so on the bare level rather than in a room
        return {"start": [1, 6], "end": [7, 6]} if brick.mount == "path" else {"position": [6, 6]}
    if brick.mount == "path":
        return {"ref": "site", "start": [-12, 2], "end": [-12, 8]} if outdoor else {"ref": "hall", "start": [1, 6], "end": [7, 6]}
    if "roof" in brick.tags:
        return {"ref": "roof"}
    if outdoor:
        return {"ref": "site", "position": [-12, 6]}
    return {"ref": "hall"}


def test_every_brick_places_with_defaults_and_compiles_to_valid_ifc():
    lib = library()
    els, failures = [], []
    for brick in lib.bricks.values():
        d = _design(dict(step="level", id="L1", height=4.0), dict(step="room", name="Hall", rect=[0, 0, 12, 12]))
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


def test_rest_brick_goes_against_the_named_side_facing_into_the_room():
    a = _assets(_house(dict(step="brick", brick="fridge", ref="kitchen", side="N")))["fridge-kitchen"]
    assert a.ifc_class == "IfcElectricAppliance" and a.predefined_type == "FRIDGE_FREEZER"
    assert a.rotation == 180 and a.position[1] > 3 and a.elevation == 0 and a.ref == "kitchen"
    assert [(c.kind, c.direction) for c in a.connectors] == [("power", "in")]


def test_fix_brick_is_lifted_to_its_elevation():
    a = _assets(_house(dict(step="brick", brick="radiator", ref="living", side="S")))["radiator-living"]
    assert a.elevation == pytest.approx(0.15)
    assert a.position[1] < 1


def test_hang_brick_hangs_under_the_ceiling():
    a = _assets(_house(dict(step="brick", brick="supply_diffuser", ref="living")))["supply-diffuser-living"]
    assert a.elevation + a.size[2] == pytest.approx(3.0 - 0.2)
    assert a.position == pytest.approx((8.0, 2.0))


def test_roof_brick_sits_on_the_roof_and_must_fit_on_it():
    a = _assets(_house(dict(step="brick", brick="solar_pv_array", ref="roof")))["solar-pv-array-roof"]
    assert a.elevation == pytest.approx(3.25) and a.position == pytest.approx((5.5, 2.0))
    with pytest.raises(DesignError, match="off"):
        derive(_house(dict(step="brick", brick="solar_pv_array", ref="roof", position=[20, 20])))


def test_path_brick_runs_between_its_points_and_takes_the_length():
    a = _assets(_house(dict(step="brick", brick="steel_beam", ref="living", start=[5.5, 1], end=[5.5, 3.5])))["steel-beam-living"]
    assert a.position == pytest.approx((5.5, 1)) and a.rotation == pytest.approx(90)
    assert a.params["length"] == pytest.approx(2.5)
    assert a.elevation + a.size[2] == pytest.approx(2.8)


def test_fitted_params_take_the_frame_height_and_footings_go_below_ground():
    assets = _assets(_house(dict(step="level", id="L1", height=3.4),
                            dict(step="brick", brick="concrete_column", ref="living", position=[8, 2]),
                            dict(step="brick", brick="pad_footing", position=[8, 2])))
    assert assets["concrete-column-living"].size[2] == pytest.approx(3.2)
    footing = assets["pad-footing-l1"]
    assert footing.elevation == pytest.approx(-footing.size[2])


def test_site_bricks_must_stand_clear_of_the_building():
    assert phase_of(_assets(_house(dict(step="brick", brick="tree", ref="site", position=[-4, 2])))["tree-site"]) == "site"
    with pytest.raises(DesignError, match="tree"):
        derive(_house(dict(step="brick", brick="tree", ref="site", position=[3, 2])))


def test_bricks_stand_on_and_hang_from_other_bricks():
    assets = _assets(_house(dict(step="brick", brick="dining_table", ref="living", id="table"),
                            dict(step="brick", brick="nightstand", ref="table", id="stand"),
                            dict(step="brick", brick="pendant_light", ref="living", id="lamp")))
    table, stand, lamp = assets["table"], assets["stand"], assets["lamp"]
    assert stand.elevation == pytest.approx(table.elevation + table.size[2])
    assert lamp.elevation + lamp.size[2] == pytest.approx(2.8)


@pytest.mark.parametrize("step, match", [
    (dict(step="brick", brick="toaster_9000", ref="kitchen"), "no brick 'toaster_9000'"),
    (dict(step="brick", brick="steel_beam", ref="living", start=[0, 0]), "give `start` and `end`"),
    (dict(step="brick", brick="fridge", ref="kitchen", start=[0, 0], end=[1, 0]), "not a path"),
    (dict(step="brick", brick="fridge", ref="kitchen", params={"w": 9}), "outside"),
    (dict(step="brick", brick="fridge", ref="kitchen", params={"colour": 1}), "no param 'colour'"),
    (dict(step="brick", brick="fridge", level="L7"), "unknown level"),
])
def test_bad_brick_steps_are_rejected_with_a_message_for_the_model(step, match):
    with pytest.raises(StepError, match=match):
        apply_step(_house(), Step(**step))


@pytest.mark.parametrize("step, match", [
    (dict(step="brick", brick="fridge"), "needs `position`"),
    (dict(step="brick", brick="fridge", ref="attic"), "nothing called 'attic'"),
    (dict(step="brick", brick="fridge", ref="kitchen", near=[50, 50]), "from every side"),
])
def test_placement_errors_surface_when_derived(step, match):
    with pytest.raises(DesignError, match=match):
        derive(_house(step))


def test_unknown_brick_suggests_close_matches():
    with pytest.raises(StepError, match="closest: .*fridge"):
        apply_step(_house(), Step(step="brick", brick="refrigerator", ref="kitchen"))


PLANTER = {
    "id": "planter", "name": "Planter", "description": "a tapered box planter", "ifc_class": "IfcFurniture",
    "tags": ["planter", "garden"],
    "params": [{"name": "w", "default": 0.8, "min": 0.3, "max": 2}, {"name": "h", "default": 0.5, "min": 0.2, "max": 1}],
    "geometry": [{"shape": "loft", "sections": [{"z": 0, "profile": {"rect": ["w * 0.8", "w * 0.8"], "centered": True}},
                                                {"z": "h", "profile": {"rect": ["w", "w"], "centered": True}}]},
                 {"shape": "cylinder", "radius": "w * 0.1", "height": 0.05, "at": [0, 0, "h"], "material": "soil"}],
    "materials": {"default": {"color": [0.6, 0.5, 0.4]}, "soil": {"color": [0.3, 0.2, 0.1]}},
}


def test_an_asset_step_defines_a_brick_the_model_can_place_and_compile():
    d, msg = apply_step(_house(), Step(step="asset", definition=json.dumps(PLANTER)))
    assert msg.startswith("asset planter: Planter (2 solid(s)")
    d, _ = apply_step(d, Step(step="brick", brick="planter", ref="living", params=[{"name": "w", "value": 1.2}]))
    spec, _ = derive(d)
    a = next(e for e in spec.elements if isinstance(e, Asset) and e.brick == "planter")
    assert a.size == pytest.approx((1.2, 1.2, 0.55)) and a.params["w"] == pytest.approx(1.2)
    model, _ = compile_ifc(spec)
    assert check_geometry(model) == []
    proxy = next(p for p in model.by_type("IfcFurniture") if ifcopenshell.util.element.get_pset(p, "NoCoast_Brick", "Brick") == "planter")
    assert proxy.Name.startswith("Planter")


def test_asset_steps_are_validated_and_removing_one_removes_its_placements():
    with pytest.raises(StepError, match="not valid JSON"):
        apply_step(_house(), Step(step="asset", definition="{nope"))
    with pytest.raises(StepError, match="library brick"):
        apply_step(_house(), Step(step="asset", definition=json.dumps({**PLANTER, "id": "fridge"})))
    with pytest.raises(StepError, match="asset"):
        apply_step(_house(), Step(step="asset", definition=json.dumps({**PLANTER, "geometry": [{"shape": "box", "size": ["q", 1, 1]}]})))
    d = _house(dict(step="asset", definition=json.dumps(PLANTER)), dict(step="brick", brick="planter", ref="living"))
    d2, msg = apply_step(d, Step(step="remove", id="planter"))
    assert msg == "removed asset planter and its 1 placement(s)" and not d2.bricks and not d2.library


def test_params_resize_the_brick():
    a = _assets(_house(dict(step="brick", brick="kitchen_counter", ref="kitchen", side="S", params=[{"name": "w", "value": 3.0}])))
    assert next(iter(a.values())).size[0] == pytest.approx(3.0)


def test_removing_a_room_removes_what_is_in_it_and_a_brick_can_be_removed_by_id():
    d = _house(dict(step="brick", brick="fridge", ref="kitchen", side="N"), dict(step="brick", brick="tree", ref="site", position=[-4, 2]))
    d2, _ = apply_step(d, Step(step="remove", id="kitchen"))
    assert [b.id for b in d2.bricks] == ["tree-site"]
    d3, msg = apply_step(d, Step(step="remove", id="tree-site"))
    assert msg == "removed brick tree-site" and [b.id for b in d3.bricks] == ["fridge-kitchen"]


def test_bricks_that_no_longer_fit_are_pruned():
    d = _house(dict(step="brick", brick="dining_table", ref="living"))
    d.rooms[1].rect = (5.0, 0.0, 1.0, 1.0)
    derived = analyze(d, prune=True)
    assert any("dining-table-living" in p for p in derived.pruned)


def test_a_room_with_water_bricks_gets_a_plumbing_riser():
    spec, _ = derive(_house(dict(step="brick", brick="washing_machine", ref="living", side="N")))
    risers = [e for e in spec.elements if e.type == "pipe" and e.kind == "water"]
    assert (8.0, 2.0) in [r.position for r in risers]


def test_construction_order_follows_the_ifc_class():
    spec, _ = derive(_house(dict(step="brick", brick="pad_footing", position=[8, 2]),
                            dict(step="brick", brick="tree", ref="site", position=[-4, 2])))
    order = [e.id for e in build_order(spec)]
    assert order.index("pad-footing-l1") < order.index("L1-wall-kitchen-W")
    assert order[-1] == "tree-site"


def test_context_lists_bricks_footprint_and_focus():
    d = _house(dict(step="brick", brick="fridge", ref="kitchen", side="N"))
    text = describe_design(d, analyze(d))
    assert "bricks: fridge-kitchen fridge on kitchen side=N" in text
    assert "footprint: L1 x 0..11 y 0..4" in text
    assert "fridge freezer" in describe_focus(d, "fridge-kitchen").lower()
