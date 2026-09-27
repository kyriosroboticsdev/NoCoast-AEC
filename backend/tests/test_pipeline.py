"""Prompt and handwritten spec → IFC that reopens and tessellates."""

import ifcopenshell
import pytest
from fastapi.testclient import TestClient

from api.routes import OUTPUT_DIR
from main import app
from schemas.bim import BuildingSpec

client = TestClient(app)

PROMPTS = [
    "a stone dome",
    "a barrel vault",
    "an underground tunnel",
    "a helical stair",
    "a bridge with piers and a curved deck",
    "a small one storey cabin",
]


@pytest.mark.parametrize("prompt", PROMPTS)
def test_generate(prompt):
    r = client.post("/generate", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    body = r.json()
    model = ifcopenshell.open(str(OUTPUT_DIR / f"{body['id']}.ifc"))
    assert model.schema == "IFC4"
    assert len(model.by_type("IfcProject")) == 1
    assert any(getattr(p, "Representation", None) for p in model.by_type("IfcProduct"))
    assert client.get(body["ifc_url"]).status_code == 200


def test_plan_is_a_card_not_a_house():
    r = client.post("/plan", json={"prompt": "a stone dome"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["planner"] == "cards"
    assert body["model"]["parts"][0]["ifc"] == "IfcRoof"
    assert r.json()["model"]["parts"][0]["name"] == "dome"


def test_unknown_prompt_is_not_given_a_house():
    r = client.post("/plan", json={"prompt": "qqqq xxxx"})
    assert r.status_code == 422


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
    openings = model.by_type("IfcOpeningElement")
    assert openings and "well" in openings[0].Name
    assert model.by_type("IfcSlab")[0].HasOpenings
    assert {roof.PredefinedType for roof in model.by_type("IfcRoof")} == {"GABLE_ROOF", "HIP_ROOF"}
    bad = spec.model_dump()
    bad["elements"][1]["outline"] = [[0, 0], [8, 0], [8, 6], [4, 6], [4, 3], [0, 3]]
    assert client.post("/build", json={"spec": bad}).status_code == 422


def test_focus_names_the_part():
    from core.context import describe_focus
    from schemas.geo import GeoModel, GeoPart, Solid, Profile

    geo = GeoModel(parts=[GeoPart(id="wall-l1-south", name="south wall", ifc="IfcWall", ifc_type="SOLIDWALL",
                                  solids=[Solid(op="extrude", profile=Profile(rect=(6, 0.2)), depth=3)])])
    text = describe_focus(geo, "wall-l1-south")
    assert text is not None and "id=wall-l1-south" in text and "IfcWall" in text
    assert describe_focus(geo, "missing") == "element id=missing"
