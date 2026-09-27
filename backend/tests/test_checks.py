"""Geometric checks against a compiled model, and the evaluation fixtures."""

import json
from pathlib import Path

from core.checks import check, score
from ifc.compile import compile_ifc
from llm.mock import author_steps
from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, apply_step
from schemas.requirements import Requirement

EVALS = Path(__file__).parent / "evals" / "prompts.json"


def _model(prompt: str):
    geo = GeoModel()
    for raw in author_steps(prompt):
        geo, _ = apply_step(geo, GeoStep.model_validate(raw))
    return compile_ifc(geo)[0]


def test_checks_on_a_house():
    model = _model("Two storey house with a kitchen, living room, dining room and three bedrooms, plus a garage and a gable roof")
    reqs = [
        Requirement(text="two storeys", kind="levels", value=2),
        Requirement(text="three bedrooms", kind="count", ifc="IfcSpace", name="bedroom", value=3, level="L2"),
        Requirement(text="a kitchen", kind="count", ifc="IfcSpace", name="kitchen", value=1),
        Requirement(text="a garage", kind="count", name="garage", value=1),
        Requirement(text="gable roof", kind="count", ifc="IfcRoof", name="gable", value=1),
        Requirement(text="a stair", kind="entity", ifc="IfcStair", value=1),
        Requirement(text="a pool", kind="other", supported=False),
        Requirement(text="modern look", kind="style"),
    ]
    results = check(model, reqs)
    status = {r.requirement.text: r.status for r in results}
    assert status["two storeys"] == "met" and status["three bedrooms"] == "met"
    assert status["a garage"] == "met" and status["gable roof"] == "met" and status["a stair"] == "met"
    assert status["a pool"] == "unsupported" and status["modern look"] == "skipped"
    met, total = score(results)
    assert total == 6 and met == 6


def test_dome_is_curved_and_a_box_is_not():
    dome = _model("a stone dome")
    assert check(dome, [Requirement(text="curved", kind="curved", ifc="IfcRoof")])[0].status == "met"
    from schemas.geo import GeoPart, Solid, Profile
    box = GeoModel(parts=[GeoPart(id="b", ifc="IfcWall", ifc_type="SOLIDWALL",
                                  solids=[Solid(op="extrude", profile=Profile(rect=(2, 0.2)), depth=3)])])
    model, _ = compile_ifc(box)
    assert check(model, [Requirement(text="curved", kind="curved")])[0].status == "unmet"


def test_eval_file_uses_the_geometric_kinds():
    cases = json.loads(EVALS.read_text(encoding="utf-8"))
    assert cases and any(c.get("residential") for c in cases)
    kinds = {r["kind"] for c in cases for r in c["requirements"]}
    assert "room" not in kinds and "storeys" not in kinds
    assert {"levels", "count", "curved"} <= kinds
    for case in cases:
        for raw in case["requirements"]:
            Requirement.model_validate(raw)
