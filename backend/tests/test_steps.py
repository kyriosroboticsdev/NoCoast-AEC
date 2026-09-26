"""Build steps: application, rejection messages, cascades, and the streaming runner."""

import json

import pytest

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
    for cut in range(0, len(text) + 1, 17):
        stream.feed(text[:cut])
    stream.feed(text)
    stream.close()
    assert stream.applied == 3 and len(stream.accepted) == 2 and len(stream.rejected) == 1
    assert "overlaps" in stream.rejected[0][2] and stream.rejected[0][0] == 2
    assert [r.id for r in stream.design.rooms] == ["hall"] and stream.design.windows
    kinds = [e[0] for e in events]
    assert kinds.count("step") == 3 and "partial" in kinds
    partial = next(e for e in events if e[0] == "partial")
    assert partial[2]["ifc_url"].startswith("/models/partial/") and partial[2]["elements"] >= 5
    assert stream.count >= 1
