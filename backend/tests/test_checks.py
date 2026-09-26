"""Requirement checks against a derived design, and the evaluation fixtures."""

import json
from pathlib import Path

from agents.template_planner import TemplatePlanner
from core.checks import check, score
from core.derive import analyze
from schemas.requirements import Requirement, RequirementsResponse

EVALS = Path(__file__).parent / "evals" / "prompts.json"


def test_checks_on_template_design():
    plan = TemplatePlanner().plan("Two storey house with a kitchen, living room, dining room and three bedrooms, plus a garage and a gable roof")
    derived = analyze(plan.design)
    reqs = [
        Requirement(text="two storeys", kind="storeys", value=2),
        Requirement(text="three bedrooms", kind="room", room="bedroom", value=3),
        Requirement(text="bedrooms upstairs", kind="room", room="bedroom", value=3, level="L2"),
        Requirement(text="a kitchen", kind="room", room="kitchen"),
        Requirement(text="kitchen next to the dining room", kind="adjacent", room="kitchen", room2="dining room"),
        Requirement(text="a garage", kind="feature", item="garage"),
        Requirement(text="gable roof", kind="roof", item="gable"),
        Requirement(text="a stair", kind="stair"),
        Requirement(text="beds in every bedroom", kind="furniture", item="bed", value=3),
        Requirement(text="a pool", kind="other", supported=False),
        Requirement(text="a sauna", kind="room", room="sauna"),
        Requirement(text="modern look", kind="style"),
    ]
    results = check(plan.design, derived, reqs)
    status = {r.requirement.text: r.status for r in results}
    assert status["two storeys"] == "met" and status["three bedrooms"] == "met" and status["bedrooms upstairs"] == "met"
    assert status["a garage"] == "met" and status["gable roof"] == "met" and status["a stair"] == "met"
    assert status["beds in every bedroom"] == "met"
    assert status["a pool"] == "unsupported" and status["a sauna"] == "unmet" and status["modern look"] == "skipped"
    met, total = score(results)
    assert total == 10 and met >= 9


def test_requirement_coercions():
    r = RequirementsResponse.model_validate({"requirements": {"text": "x", "kind": "room", "room": "bedroom", "level": "upstairs", "side": "north"}})
    assert r.requirements[0].level == "L2" and r.requirements[0].side == "N"
    assert Requirement(text="x", kind="storeys", level=2).level == "L2"


def test_eval_fixtures_are_well_formed():
    cases = json.loads(EVALS.read_text(encoding="utf-8"))
    assert len(cases) >= 15
    for case in cases:
        assert case["prompt"] and case["requirements"]
        for raw in case["requirements"]:
            Requirement.model_validate(raw)
