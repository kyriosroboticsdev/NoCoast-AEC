"""Every recipe card is a real GeoStep exemplar, and retrieval is deterministic."""

from blocks import load_cards, retrieve
from ifc.compile import compile_ifc
from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, apply_step


def test_every_card_compiles():
    cards = load_cards()
    assert len(cards) >= 25
    ids = [c.id for c in cards]
    assert len(ids) == len(set(ids))
    for card in cards:
        model = GeoModel()
        for raw in card.steps:
            model, _ = apply_step(model, GeoStep.model_validate(raw))
        assert not model.is_empty(), card.id
        ifc, _ = compile_ifc(model)
        assert ifc.schema == "IFC4"
        assert ifc.by_type("IfcProduct")


def test_retrieval_prefers_the_specific_card():
    assert retrieve("a barrel vault over the nave")[0].id == "barrel-vault"
    assert retrieve("helical stair up the tower")[0].id == "spiral-stair"
    dome = [c.id for c in retrieve("a stone dome")]
    assert dome[0] == "dome"
    party = [c.id for c in retrieve("semi-detached houses sharing a party wall")]
    assert party[0] == "party-wall"
    tunnel = [c.id for c in retrieve("an underground tunnel bore")]
    assert tunnel[0] == "tunnel"
    assert retrieve("a bridge with piers and a curved deck")[0].id == "bridge"
    # Empty and unknown prompts do not invent a card.
    assert retrieve("") == []
    assert retrieve("qqqq xxxx") == []
