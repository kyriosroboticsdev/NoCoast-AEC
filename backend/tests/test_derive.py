"""Design → spec derivation: walls from room edges, openings, stairs, roofs, and the ids that make GlobalIds stable."""

import pytest

from core.derive import DesignError, analyze, derive
from schemas.design import Design, DoorDef, LevelDef, RoomDef, StairDef, WindowDef


def two_rooms() -> Design:
    return Design(levels=[LevelDef(id="L1")], rooms=[
        RoomDef(id="a", name="A", level="L1", kind="living", rect=(0, 0, 5, 4)),
        RoomDef(id="b", name="B", level="L1", kind="kitchen", rect=(5, 0, 4, 4)),
    ])


def test_walls_from_shared_and_free_edges():
    d = analyze(two_rooms())
    walls = {e.id: e for e in d.spec.elements if e.type == "wall"}
    assert "L1-wall-a+b" in walls and not walls["L1-wall-a+b"].external
    assert walls["L1-wall-a+b"].start == (5, 0) and walls["L1-wall-a+b"].end == (5, 4)
    assert walls["L1-wall-a-S"].external and walls["L1-wall-a-W"].external
    assert "L1-wall-a-E" not in walls  # the east edge of A is shared, not exterior
    # exterior horizontal walls are extended to the outer face of the corner walls
    assert walls["L1-wall-a-S"].start == (-0.15, 0) and walls["L1-wall-a-S"].end == (5, 0)
    assert d.rooms["a"].sides == ["S", "W", "N"] and d.rooms["a"].neighbours == ["b"]
    slab = next(e for e in d.spec.elements if e.type == "slab")
    assert len(slab.outline) == 4
    # beams (ring beam per exterior wall) and MEP rough-in (light/outlet/wire/panel + a plumbing
    # riser, since "b" is a kitchen) are always derived alongside the structural shell
    assert {e.type for e in d.spec.elements} == {"wall", "slab", "space", "roof", "beam", "light", "outlet", "wire", "panel", "pipe"}


def test_overlap_and_unknown_level_are_rejected():
    design = two_rooms()
    design.rooms[1].rect = (4, 0, 4, 4)
    with pytest.raises(DesignError, match="overlaps"):
        derive(design)
    design = two_rooms()
    design.rooms[1].level = "L3"
    with pytest.raises(DesignError, match="unknown level"):
        derive(design)


def test_openings_need_the_right_wall():
    design = two_rooms()
    design.doors.append(DoorDef(id="d1", room="a", to="b"))
    design.doors.append(DoorDef(id="d2", room="a", to="outside", side="S"))
    design.windows.append(WindowDef(id="w1", room="b", side="E", kind="large"))
    spec, _ = derive(design)
    doors = {e.id: e for e in spec.elements if e.type == "door"}
    assert doors["d1"].wall == "L1-wall-a+b" and doors["d2"].wall == "L1-wall-a-S"
    win = next(e for e in spec.elements if e.type == "window")
    assert win.wall == "L1-wall-b-E" and win.width == 2.0
    design.windows.append(WindowDef(id="w2", room="a", side="E"))
    with pytest.raises(DesignError, match="exterior sides are S, W, N"):
        derive(design)


def test_stair_and_well():
    design = Design(levels=[LevelDef(id="L1"), LevelDef(id="L2")], rooms=[
        RoomDef(id="hall", name="Hall", level="L1", kind="hall", rect=(0, 0, 3, 6)),
        RoomDef(id="landing", name="Landing", level="L2", kind="hall", rect=(0, 0, 3, 6)),
    ], stairs=[StairDef(id="s", room="hall", side="W")])
    spec, _ = derive(design)
    stair = next(e for e in spec.elements if e.type == "stair")
    assert stair.to_level == "L2" and stair.direction == 90 and stair.position[0] == pytest.approx(0.65)
    design.rooms[0].rect = (0, 0, 3, 4)
    with pytest.raises(DesignError, match="needs"):
        derive(design)


def test_roof_shapes_and_lower_roofs():
    design = Design(levels=[LevelDef(id="L1"), LevelDef(id="L2")], rooms=[
        RoomDef(id="a", name="A", level="L1", rect=(0, 0, 6, 6)),
        RoomDef(id="g", name="Garage", level="L1", kind="garage", rect=(6, 0, 6, 6)),
        RoomDef(id="b", name="B", level="L2", rect=(0, 0, 6, 6)),
    ])
    design.roof.kind = "gable"
    spec, notes = derive(design)
    roofs = {e.id: e for e in spec.elements if e.type == "roof"}
    assert roofs["roof"].shape == "gable" and roofs["roof"].level == "L2"
    assert roofs["L1-roof"].shape == "gable" and roofs["L1-roof"].level == "L1"  # over the garage only
    assert any(e.type == "door" and e.kind == "garage" for e in spec.elements)  # auto garage door
    assert any("garage door" in n for n in notes)


def test_ids_are_stable_when_a_room_moves():
    design = two_rooms()
    ids1 = {e.id for e in derive(design)[0].elements}
    design.rooms[1].rect = (5, 0, 6, 4)
    ids2 = {e.id for e in derive(design)[0].elements}
    assert ids1 == ids2
