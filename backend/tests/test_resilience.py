"""What happens when the model misbehaves: prose around the JSON, a reply that breaks off
mid-building, a repair round that never comes back. None of these may throw the work away."""

import json

import pytest

from core.pipeline import PipelineError, run_prompt
from core.stream import StepStream
from llm.base import EmptyReply, LLMError, LLMRequest, body
from llm.mock import MockLLM
from schemas.design import Design
from store.db import Store

STEPS = [
    {"step": "building", "name": "Prose House"},
    {"step": "level", "id": "L1"},
    {"step": "layout", "level": "L1", "rooms": [
        {"name": "Hall", "kind": "hall", "rect": [0, 0, 3, 8]},
        {"name": "Kitchen", "kind": "kitchen", "rect": [3, 0, 4, 8]}]},
    {"step": "door", "room": "kitchen", "to": "hall"},
    {"step": "door", "room": "hall", "to": "outside", "side": "S"},
]


def feed(text: str) -> StepStream:
    """Stream `text` in through the parser one character at a time, as an adapter would."""
    stream = StepStream(lambda *a: None, Design())
    for i in range(1, len(text) + 1):
        stream.consume(text[:i])
    stream.close()
    return stream


def test_body_finds_the_object_inside_prose():
    assert body('Here is the design:\n{"steps": []}') == '{"steps": []}'
    assert body('```json\n{"steps": []}\n```') == '{"steps": []}'
    assert body('{"steps": []}') == '{"steps": []}'
    assert body("no json here") == "no json here"


def test_steps_stream_in_even_with_a_preamble():
    """An unconstrained model introduces itself first; the steps must still land as they arrive,
    not all at once when the reply finally ends."""
    reply = json.dumps({"approach": "A simple through-plan.", "steps": STEPS})
    plain, chatty = feed(reply), feed("Sure — here is the building:\n\n" + reply)
    assert len(plain.accepted) == len(STEPS)
    assert len(chatty.accepted) == len(STEPS)
    assert chatty.approach == "A simple through-plan."


def test_a_reply_that_breaks_off_keeps_what_it_built(tmp_path):
    """max_tokens (or a dropped connection) after the model has laid out the plan must not lose it."""
    cut = json.dumps({"steps": STEPS})[:-60]  # stops mid-way through the last door

    class Truncating(MockLLM):
        name = "truncating"

        def complete(self, request: LLMRequest, on_text=None, on_note=None) -> dict:
            if request.schema_name != "build":
                return super().complete(request, on_text, on_note)
            for i in range(1, len(cut) + 1, 7):
                if on_text:
                    on_text(cut[:i])
            raise LLMError("the model's answer was cut off (max_tokens)")

    store = Store(tmp_path / "db.sqlite3", tmp_path / "ifc")
    pid = store.create_project("truncated").id
    events: list[tuple[str, str]] = []
    version = run_prompt(store, Truncating(), pid, "a hall and a kitchen",
                         emit=lambda stage, message, data=None: events.append((stage, message)))
    assert version.number == 1
    assert {r.id for r in version.design.rooms} == {"hall", "kitchen"}
    assert any("broke off" in m for s, m in events if s == "llm")


def test_a_reply_that_breaks_off_with_nothing_built_is_an_error(tmp_path):
    class Silent(MockLLM):
        name = "silent"

        def complete(self, request: LLMRequest, on_text=None, on_note=None) -> dict:
            if request.schema_name != "build":
                return super().complete(request, on_text, on_note)
            raise LLMError("the model's answer was cut off (max_tokens)")

    store = Store(tmp_path / "db.sqlite3", tmp_path / "ifc")
    pid = store.create_project("silent").id
    with pytest.raises(PipelineError, match="cut off"):
        run_prompt(store, Silent(), pid, "a hall and a kitchen")


def test_an_empty_build_reply_means_no_changes(tmp_path):
    """"Nothing to fix" comes back as an empty completion from some models; a checklist may not."""
    class SaysNothing(MockLLM):
        name = "says-nothing"

        def complete(self, request: LLMRequest, on_text=None, on_note=None) -> dict:
            if request.schema_name != "build" or not request.meta.get("problems"):
                return super().complete(request, on_text, on_note)
            if on_text:
                on_text("")
            raise EmptyReply("the model returned an empty reply")

    store = Store(tmp_path / "db.sqlite3", tmp_path / "ifc")
    pid = store.create_project("empty").id
    events: list[tuple[str, str]] = []
    version = run_prompt(store, SaysNothing(), pid, "a two storey house with a kitchen and two bedrooms",
                         emit=lambda stage, message, data=None: events.append((stage, message)))
    assert version.number == 1 and version.design.rooms
    assert not any("empty reply" in m for _, m in events)


def test_a_failing_repair_round_still_produces_a_version(tmp_path):
    """The first round builds; the repair round (there is one rejected step) dies. Keep the build."""
    reply = {"steps": STEPS + [{"step": "window", "room": "kitchen", "side": "W"}]}  # kitchen has no W wall

    class FailsOnRepair(MockLLM):
        name = "fails-on-repair"

        def complete(self, request: LLMRequest, on_text=None, on_note=None) -> dict:
            if request.schema_name != "build":
                return super().complete(request, on_text, on_note)
            if request.meta.get("problems") or request.meta.get("unmet"):
                raise LLMError("upstream connect error")
            text = json.dumps(reply)
            for i in range(1, len(text) + 1, 13):
                if on_text:
                    on_text(text[:i])
            return reply

    store = Store(tmp_path / "db.sqlite3", tmp_path / "ifc")
    pid = store.create_project("repair").id
    events: list[tuple[str, str]] = []
    version = run_prompt(store, FailsOnRepair(), pid, "a hall and a kitchen",
                         emit=lambda stage, message, data=None: events.append((stage, message)))
    assert version.number == 1 and {r.id for r in version.design.rooms} == {"hall", "kitchen"}
    assert any("did not come back" in m for s, m in events if s == "build")
