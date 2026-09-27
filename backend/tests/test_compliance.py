"""Compliance warnings the model sees: blocked doors, intersections, bad hosts."""

from core.coordinate import coordinate
from core.derive import analyze
from core.pipeline import _context
from core.research import Toolbox, run_tool
from schemas.research import ToolCall
from schemas.steps import Step, apply_step
from schemas.design import Design


def _design(*steps) -> Design:
    d = Design(name="t")
    for s in steps:
        d, _ = apply_step(d, Step(**s))
    return d


def _warnings(d: Design, kind: str | None = None):
    found = [i for i in coordinate(d, analyze(d)) if i.severity == "warning"]
    return [i for i in found if kind is None or i.kind == kind]


ROOM = dict(step="room", name="Hall", rect=[0, 0, 6, 5])


def test_a_piece_in_the_door_swing_is_a_warning_the_model_can_see():
    blocked = _design(ROOM, dict(step="door", room="hall", to="outside", side="S", at=0.5),
                      dict(step="furniture", id="sofa-hall", room="hall", kind="sofa", position=[3, 0.5]))
    [door] = [i for i in _warnings(blocked, "clearance") if "blocked" in i.message]
    assert "sofa-hall" in door.ids and any(i.startswith("door-") for i in door.ids)
    assert "swing" in door.message or "opening" in door.message or "clearance" in door.message
    clear = _design(ROOM, dict(step="door", room="hall", to="outside", side="S", at=0.5),
                    dict(step="furniture", id="sofa-hall", room="hall", kind="sofa", side="N"))
    assert not [i for i in _warnings(clear, "clearance") if "blocked" in i.message]
    text = _context(blocked)
    assert text is not None and "sofa-hall" in text and "blocked" in text
    heard = run_tool(ToolCall(tool="check_design"), blocked, Toolbox())
    assert "blocked" in heard and "sofa-hall" in heard


def test_two_pieces_in_the_same_place_intersect_and_separated_ones_do_not():
    piled = _design(ROOM, dict(step="furniture", id="sofa-hall", room="hall", kind="sofa", position=[3, 2.5]),
                    dict(step="furniture", id="chair-hall", room="hall", kind="armchair", position=[3, 2.5]))
    [hit] = _warnings(piled, "intersection")
    assert set(hit.ids) == {"sofa-hall", "chair-hall"} and "intersect" in hit.message
    apart = _design(ROOM, dict(step="furniture", id="sofa-hall", room="hall", kind="sofa", side="N"),
                    dict(step="furniture", id="chair-hall", room="hall", kind="armchair", side="S"))
    assert not _warnings(apart, "intersection")


def test_a_fix_mounted_piece_floating_in_the_room_is_not_hosted():
    floating = _design(ROOM, dict(step="brick", brick="wall_hung_wc", ref="hall", position=[3, 2.5]))
    [issue] = _warnings(floating, "insertion")
    assert "wall-hung-wc-hall" in issue.ids
    assert "not hosted in a wall" in issue.message and "floating" in issue.message
    seated = _design(ROOM, dict(step="brick", brick="wall_hung_wc", ref="hall", side="S"))
    assert not _warnings(seated, "insertion")


def test_a_wall_hosted_piece_turned_away_from_its_wall_is_the_wrong_orientation():
    turned = _design(ROOM, dict(step="brick", brick="wall_hung_wc", ref="hall", position=[3, 0.55], rotation=180))
    [issue] = _warnings(turned, "insertion")
    assert "wrong orientation" in issue.message and "wall-hung-wc-hall" in issue.ids
    facing = _design(ROOM, dict(step="brick", brick="wall_hung_wc", ref="hall", position=[3, 0.55], rotation=0))
    assert not [i for i in _warnings(facing, "insertion") if "orientation" in i.message]


def test_a_buried_piece_and_a_floating_one_are_named():
    # A shallow piece pushed into the wall face: it still fits in the room, but most of its depth is in the wall.
    buried = _design(ROOM, dict(step="furniture", id="sofa-hall", room="hall", kind="sofa", position=[3, 0.18],
                                width=0.8, depth=0.35))
    [issue] = _warnings(buried, "insertion")
    assert "partially inserted" in issue.message and "sofa-hall" in issue.ids
    floating = _design(ROOM, dict(step="furniture", id="sofa-hall", kind="sofa", position=[3, 2], elevation=1.2))
    [up] = _warnings(floating, "insertion")
    assert "floating" in up.message and "sofa-hall" in up.ids
    hung = _design(ROOM, dict(step="brick", brick="pendant_light", ref="hall", position=[3, 2.5, 1]))
    [low] = [i for i in _warnings(hung, "insertion") if "pendant" in i.message]
    assert "ceiling" in low.message or "floating" in low.message
    seated = _design(ROOM, dict(step="brick", brick="pendant_light", ref="hall"))
    assert not [i for i in _warnings(seated, "insertion") if "pendant" in i.message]
