"""End-to-end backend checks: prompt → spec → IFC that reopens and tessellates."""

import ifcopenshell
import pytest
from fastapi.testclient import TestClient

from agents.template_planner import TemplatePlanner
from api.routes import OUTPUT_DIR
from main import app
from schemas.bim import BuildingSpec

client = TestClient(app)

SPEC_PROMPT = ("Create a two-story rectangular house. The first floor should have a kitchen and living room. "
               "The second floor should have three bedrooms. Add windows to the exterior walls and a garage.")

PROMPTS = [
    SPEC_PROMPT,
    "Create a two-story house with four bedrooms, a garage, and a flat roof.",
    "A small one storey cabin",
    "Design a modern two-story house with lots of natural light and a front porch.",
    "Three storey house, 40 by 30 feet, with a kitchen, dining room, office and five bedrooms",
    "A gable roof cottage with 2 bathrooms",
]


@pytest.mark.parametrize("prompt", PROMPTS)
def test_generate(prompt):
    r = client.post("/generate", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    body = r.json()
    model = ifcopenshell.open(str(OUTPUT_DIR / f"{body['id']}.ifc"))
    assert model.schema == "IFC4"
    assert len(model.by_type("IfcProject")) == 1
    assert model.by_type("IfcWall") and model.by_type("IfcSlab") and model.by_type("IfcRoof")
    assert client.get(body["ifc_url"]).status_code == 200


def test_spec_prompt_interpretation():
    plan = TemplatePlanner().plan(SPEC_PROMPT)
    rooms = {l.id: [e.name for e in plan.spec.elements if e.type == "space" and e.level == l.id] for l in plan.spec.levels}
    assert len(plan.spec.levels) == 2
    assert {"Kitchen", "Living Room", "Garage"} <= set(rooms["L1"])
    assert {"Bedroom 1", "Bedroom 2", "Bedroom 3"} <= set(rooms["L2"])


def test_invalid_spec_is_rejected():
    bad = {"levels": [{"id": "L1", "name": "G"}],
           "elements": [{"type": "wall", "id": "w", "level": "L1", "start": [0, 0], "end": [2, 0]},
                        {"type": "door", "wall": "w", "offset": 1.5, "width": 1.0},
                        {"type": "window", "wall": "nope", "offset": 0}]}
    r = client.post("/build", json={"spec": bad})
    assert r.status_code == 422
    msg = str(r.json())
    assert "runs past the end" in msg and "unknown host wall" in msg


def test_build_from_handwritten_spec():
    spec = BuildingSpec.model_validate({
        "levels": [{"id": "L1", "name": "Ground", "height": 3}],
        "elements": [
            {"type": "wall", "id": "w1", "level": "L1", "start": [0, 0], "end": [6, 0], "external": True},
            {"type": "door", "wall": "w1", "offset": 2.5},
            {"type": "column", "level": "L1", "position": [3, 3]},
            {"type": "slab", "level": "L1", "outline": [[0, 0], [6, 0], [6, 4], [0, 4]]},
            {"type": "roof", "level": "L1", "outline": [[0, 0], [6, 0], [6, 4], [0, 4]]},
        ],
    })
    r = client.post("/build", json={"spec": spec.model_dump()})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["counts"] == {"IfcColumn": 1, "IfcDoor": 1, "IfcRoof": 1, "IfcSlab": 1, "IfcWall": 1}
