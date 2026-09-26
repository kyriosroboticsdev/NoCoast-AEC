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
    assert not plan.notes or all("garage door" in n for n in plan.notes), plan.notes  # every template step applies
    assert any(e.type == "stair" for e in plan.spec.elements)


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


def test_build_new_element_kinds():
    spec = BuildingSpec.model_validate({
        "levels": [{"id": "L1", "name": "Ground", "height": 3}, {"id": "L2", "name": "Upper", "height": 3}],
        "elements": [
            {"type": "slab", "id": "L2-floor", "level": "L2", "outline": [[0, 0], [8, 0], [8, 6], [0, 6]]},
            {"type": "roof", "id": "roof", "level": "L2", "outline": [[0, 0], [8, 0], [8, 6], [0, 6]], "shape": "gable", "pitch": 35},
            {"type": "roof", "id": "roof2", "level": "L1", "outline": [[8, 0], [12, 0], [12, 4], [8, 4]], "shape": "hip"},
            {"type": "stair", "id": "s", "level": "L1", "position": [1, 0.5], "direction": 90, "to_level": "L2"},
            {"type": "fixture", "id": "f", "level": "L1", "kind": "sofa", "position": [5, 3], "rotation": 90, "width": 2, "depth": 0.9, "height": 0.85},
            {"type": "railing", "id": "r", "level": "L2", "path": [[0, 0], [8, 0], [8, 6]]},
            {"type": "beam", "id": "b", "level": "L1", "start": [0, 3], "end": [8, 3]},
            {"type": "wall", "id": "w", "level": "L1", "start": [0, 6], "end": [8, 6], "material": "timber", "external": True},
        ],
    })
    r = client.post("/build", json={"spec": spec.model_dump()})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["counts"] == {"IfcBeam": 1, "IfcFurniture": 1, "IfcRailing": 1, "IfcRoof": 2, "IfcSlab": 1, "IfcStair": 1, "IfcWall": 1}
    model = ifcopenshell.open(str(OUTPUT_DIR / f"{r.json()['id']}.ifc"))
    slab = model.by_type("IfcSlab")[0]
    assert slab.HasOpenings and slab.HasOpenings[0].RelatedOpeningElement.Name == "s well"
    assert {roof.PredefinedType for roof in model.by_type("IfcRoof")} == {"GABLE_ROOF", "HIP_ROOF"}
    bad = spec.model_dump()
    bad["elements"][1]["outline"] = [[0, 0], [8, 0], [8, 6], [4, 6], [4, 3], [0, 3]]
    assert client.post("/build", json={"spec": bad}).status_code == 422  # gable needs a rectangle


def test_focus_describes_selection_and_mock_acts_on_it(tmp_path):
    from core.context import describe_focus
    from schemas.design import Design, LevelDef, RoomDef, DoorDef

    d = Design(levels=[LevelDef(id="L1")], rooms=[RoomDef(id="hall", name="Hall", level="L1", kind="hall", rect=(0, 0, 4, 6)),
                                                RoomDef(id="kitchen", name="Kitchen", level="L1", kind="kitchen", rect=(4, 0, 4, 6))],
               doors=[DoorDef(id="door-kitchen-hall", room="kitchen", to="hall")])
    assert describe_focus(d, "L1-wall-hall-W") == "the west exterior wall of the Hall (L1) (wall id L1-wall-hall-W; side=W)"
    assert describe_focus(d, "L1-wall-hall+kitchen").startswith("the partition wall between the Hall (L1) and the Kitchen (L1)")
    assert describe_focus(d, "L1-space-kitchen") == "the room the Kitchen (L1) (room id kitchen)"
    assert describe_focus(d, "door-kitchen-hall") == "the door door-kitchen-hall of the Kitchen (L1) to the Hall (L1)"
    assert describe_focus(d, "L1-floor") == "the floor slab of level L1"
    assert describe_focus(d, "something-else") == "the element something-else"

    from llm.mock import MockLLM
    steps = MockLLM()._edit("add a window", d, describe_focus(d, "L1-wall-hall-W"))
    assert steps == [{"step": "window", "room": "hall", "side": "W", "kind": "standard"}]
    steps = MockLLM()._edit("remove this", d, describe_focus(d, "door-kitchen-hall"))
    assert steps == [{"step": "remove", "id": "door-kitchen-hall"}]
