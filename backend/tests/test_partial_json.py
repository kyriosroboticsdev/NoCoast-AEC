import json

import pytest

from core.partial_json import parse_partial
from llm.base import clean_reply, parse_reply

FULL = {"mode": "ops", "ops": [{"op": "delete_element", "id": "garage-door"}, {"op": "modify_element", "id": "L1-wall-S", "set": {"thickness": 0.4}}],
        "program": None, "notes": ["removed the garage door", "thicker south wall"]}


def test_complete_json_passes_through():
    text = json.dumps(FULL)
    assert parse_partial(text) == FULL


@pytest.mark.parametrize("cut", range(1, 60, 3))
def test_every_prefix_yields_a_prefix_of_the_truth(cut):
    """Whatever prefix we cut at, the result must be valid JSON that only contains complete values."""
    text = json.dumps(FULL)
    result = parse_partial(text[: len(text) * cut // 60])
    if result is None:
        return
    assert isinstance(result, dict)
    ops = result.get("ops") or []
    assert ops == FULL["ops"][: len(ops)]  # complete ops only, in order
    for note in result.get("notes") or []:
        assert note in FULL["notes"]


def test_specific_tails():
    assert parse_partial('{"rooms": [{"name": "Kitchen", "kind": "kitc') == {"rooms": []}
    assert parse_partial('{"rooms": [{"name": "Kitchen", "kind": "kitchen"}, {"name": "Bed') == {"rooms": [{"name": "Kitchen", "kind": "kitchen"}]}
    assert parse_partial('{"storeys": 2, "bright": tru') == {"storeys": 2}
    assert parse_partial('{"storeys": 2, "footprint": [12, 8') == {"storeys": 2, "footprint": [12, 8]}
    assert parse_partial('{"a": {"b": {"c": 1') == {"a": {"b": {"c": 1}}}
    assert parse_partial('{"ops": [{"op": "modify_element", "id": "w1", "set": {"thick') == {"ops": []}
    assert parse_partial("") is None
    assert parse_partial('{"name": "He said \\"hi') == {}


def test_clean_reply_strips_thinking_and_fences():
    assert clean_reply('<think>hmm</think>\n```json\n{"a": 1}\n```') == '{"a": 1}'
    assert clean_reply("<think>still going") == ""
    assert parse_reply('{"a": 1, "b": [1, 2') == {"a": 1, "b": [1, 2]}  # max_tokens cut → closed
