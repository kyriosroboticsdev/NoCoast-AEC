"""Skills: every playbook parses, only references bricks that exist, and is found from a request."""

import re

import pytest

from bricks import library
from skills import skillbook


def test_every_skill_parses_and_references_real_bricks():
    book = skillbook()
    assert len(book.all()) >= 12
    lib = library()
    connectors = {c.kind for b in lib.bricks.values() for c in b.connectors}
    for skill in book.all():
        assert skill.title and skill.body.strip() and skill.triggers, skill.name
        for bid in skill.bricks:
            assert lib.get(bid) is not None, f"{skill.name} lists unknown brick {bid}"
        # backticked ids in the body must be real bricks too, so the model is never taught a name that fails
        for bid in re.findall(r"`([a-z0-9_]+)`", skill.body):
            if bid in connectors:
                continue
            if "_" in bid or bid in lib.bricks:
                assert lib.get(bid) is not None, f"{skill.name} body mentions unknown brick {bid}"


@pytest.mark.parametrize("request_text,expected", [
    ("a kitchen with a big island", "kitchen-layout"),
    ("open plan living space with no columns", "structural-spans"),
    ("net zero house with solar panels", "energy-and-renewables"),
    ("add sprinklers everywhere", "fire-safety"),
    ("wheelchair accessible bungalow", "accessibility"),
    ("a garden with a swimming pool and trees", "site-and-landscape"),
    ("heat pump and underfloor heating", "hvac-systems"),
    ("a bespoke curved reception sculpture", "writing-assets"),
])
def test_match_finds_the_playbook(request_text, expected):
    assert expected in [s.name for s in skillbook().match(request_text)]


def test_index_lists_every_skill():
    text = skillbook().index_text()
    assert all(s.name in text for s in skillbook().all())
