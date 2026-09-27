"""Build steps: application, rejection messages, cascades, and the streaming runner."""

import json
import time
from unittest.mock import patch

import pytest

from core.derive import analyze
from core.stream import StepStream
from schemas.design import Design
from schemas.steps import Step, StepError, apply_step


def run(design: Design, *steps: dict) -> tuple[Design, list[str]]:
    msgs = []
    for raw in steps:
        design, msg = apply_step(design, Step.model_validate(raw))
        msgs.append(msg)
    return design, msgs


def test_rooms_doors_and_removal_cascade():
    d, msgs = run(Design(),
                  {"step": "room", "name": "Living Room", "rect": [0, 0, 5, 4]},
                  {"step": "room", "name": "Kitchen", "rect": [5, 0, 4, 4]},
                  {"step": "door", "room": "kitchen", "to": "Living Room"},
                  {"step": "window", "room": "kitchen", "side": "east"},
                  {"step": "furniture", "room": "kitchen", "kind": "fridge", "side": "N"})
    assert [r.id for r in d.rooms] == ["living-room", "kitchen"]
    assert d.doors[0].to == "living-room" and d.windows[0].side == "E"
    d, msgs = run(d, {"step": "remove", "id": "kitchen"})
    assert "removed room kitchen and 3 item(s)" in msgs[-1]
    assert not d.doors and not d.windows and not d.fixtures


def test_rejections_are_explained():
    d, _ = run(Design(), {"step": "room", "name": "Hall", "rect": [0, 0, 3, 5]})
    with pytest.raises(StepError, match="unknown room 'bedroom'"):
        run(d, {"step": "door", "room": "bedroom", "to": "hall"})
    with pytest.raises(StepError, match="add it first"):
        run(d, {"step": "room", "name": "Bedroom", "level": "L2"})
    d2, _ = run(d, {"step": "window", "id": "kitchen", "room": "hall", "side": "S"})
    with pytest.raises(StepError, match="already used"):
        run(d2, {"step": "room", "name": "Kitchen", "rect": [3, 0, 3, 5]})
    with pytest.raises(StepError, match="furniture kind"):
        run(d, {"step": "furniture", "room": "hall", "kind": "piano"})
    with pytest.raises(StepError, match="no room, level"):
        run(d, {"step": "remove", "id": "nope"})


def test_qualified_furniture_and_out_of_range_roof_pitch_still_build():
    d, _ = run(Design(), {"step": "room", "name": "Office", "rect": [0, 0, 4, 4]},
               {"step": "furniture", "room": "office", "kind": "office chair"},
               {"step": "furniture", "room": "office", "kind": "teacher_desk"},
               {"step": "roof", "kind": "flat", "pitch": 2})
    assert [f.kind for f in d.fixtures] == ["chair", "desk"] and d.roof.kind == "flat"
    d, _ = run(d, {"step": "roof", "kind": "gable", "pitch": 75})
    assert d.roof.pitch == 60


def test_levels_in_order_and_updates():
    d, _ = run(Design(), {"step": "level", "id": "L1", "height": 3.2}, {"step": "level", "id": 2, "name": "Upper"})
    assert [l.id for l in d.levels] == ["L1", "L2"] and d.levels[0].height == 3.2 and d.levels[1].display == "Upper"
    with pytest.raises(StepError, match="in order"):
        run(d, {"step": "level", "id": "L5"})
    d, _ = run(d, {"step": "room", "name": "Hall", "rect": [0, 0, 3, 5]}, {"step": "room", "id": "hall", "rect": [0, 0, 4, 6]})
    assert d.rooms[0].rect == (0, 0, 4, 6)


def test_stream_applies_steps_as_they_complete_and_rejects_bad_ones():
    events = []
    stream = StepStream(lambda stage, msg, data=None: events.append((stage, msg, data)), Design(), {})
    steps = [{"step": "room", "name": "Hall", "rect": [0, 0, 3, 5]},
             {"step": "room", "name": "Kitchen", "rect": [1, 0, 3, 5]},   # overlaps → rejected
             {"step": "window", "room": "hall", "side": "S"}]
    text = json.dumps({"steps": steps})
    # Previews write the IFC without tessellating; the finished model is what gets geometry-checked.
    with patch("ifc.builder.ifcopenshell.geom.create_shape") as shape:
        for cut in range(0, len(text) + 1, 17):
            stream.feed(text[:cut])
        stream.feed(text)
        stream.close()
        assert shape.call_count == 0
    assert stream.applied == 3 and len(stream.accepted) == 2 and len(stream.rejected) == 1
    assert "overlaps" in stream.rejected[0][2] and stream.rejected[0][0] == 2
    assert [r.id for r in stream.design.rooms] == ["hall"] and stream.design.windows
    kinds = [e[0] for e in events]
    assert kinds.count("step") == 3 and "partial" in kinds
    partial = next(e for e in events if e[0] == "partial")
    assert partial[2]["ifc_url"].startswith("/models/partial/") and partial[2]["elements"] >= 5
    assert stream.count >= 1


def drawn(events: list) -> list:
    return [e for e in events if e[0] == "partial" and e[2] and "ifc_url" in e[2]]


def wait_for_preview(events: list, count: int = 1, timeout: float = 10.0) -> list:
    """Previews render on a worker thread; give it the moment a real run would."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(drawn(events)) < count:
        time.sleep(0.02)
    return drawn(events)


def test_an_open_layout_is_previewed_before_the_step_closes():
    events = []
    stream = StepStream(lambda stage, msg, data=None: events.append((stage, msg, data)), Design(), {})
    text = ('{"steps":[{"step":"level","id":"L1"},'
            '{"step":"layout","level":"L1","rooms":[{"name":"Hall","rect":[0,0,4,6]},{"name":"Kitchen","rect":[4,0,4,4]}]}]}')
    cut = text.index(',{"name":"Kitchen"')
    stream.feed(text[:cut])
    previews = wait_for_preview(events)
    assert previews and previews[0][2]["elements"] >= 4
    assert stream.design.rooms == []  # the layout step has not closed, so nothing is committed
    # The reply stops mid-step: the hall was never applied, so the viewer is put back on the real design.
    stream.close()
    assert drawn(events)[-1][2]["elements"] == 0


def test_a_rejected_layout_takes_its_preview_back_off_the_screen():
    events = []
    design, _ = run(Design(), {"step": "level", "id": "L1"}, {"step": "room", "name": "Hall", "rect": [0, 0, 4, 6]})
    stream = StepStream(lambda stage, msg, data=None: events.append((stage, msg, data)), design, {})
    good = '{"steps":[{"step":"layout","level":"L1","rooms":[{"name":"Hall","rect":[0,0,4,6]},{"name":"Kitchen","rect":[4,0,4,4]}'
    stream.feed(good)
    shown = wait_for_preview(events)[-1][2]["elements"]
    # The step ends up overlapping the hall, so it is rejected and the preview of it must not stay.
    stream.feed(good.replace('{"name":"Kitchen","rect":[4,0,4,4]', '{"name":"Kitchen","rect":[1,0,4,4]') + "]}]}")
    stream.close()
    assert [r.id for r in stream.design.rooms] == ["hall"]
    assert any("rejected" in e[1] for e in events if e[0] == "step")
    back = drawn(events)[-1][2]["elements"]
    assert back < shown and back == len(analyze(design).spec.elements)


def test_an_unfinished_rewrite_does_not_preview_a_storey_with_rooms_missing():
    events = []
    design, _ = run(Design(), {"step": "level", "id": "L1"},
                    {"step": "room", "name": "Hall", "rect": [0, 0, 4, 6]},
                    {"step": "room", "name": "Kitchen", "rect": [4, 0, 4, 4]})
    stream = StepStream(lambda stage, msg, data=None: events.append((stage, msg, data)), design, {})
    # The model has restated only the hall so far; previewing that would erase the kitchen.
    stream.feed('{"steps":[{"step":"layout","level":"L1","rooms":[{"name":"Hall","rect":[0,0,5,6]},{"name":"Kit')
    stream.close()
    assert [r.id for r in stream.design.rooms] == ["hall", "kitchen"]
    assert not [e for e in events if e[0] == "partial" and e[2] and "ifc_url" in e[2]]
