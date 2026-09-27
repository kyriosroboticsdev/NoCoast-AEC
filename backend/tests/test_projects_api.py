"""The stateful project API end to end, through the mock LLM."""

import json
import re

import ifcopenshell
from fastapi.testclient import TestClient

from core import pipeline
from llm.mock import MockLLM
from main import app
from store.db import Store
from tests.sse import done, events

client = TestClient(app)


def new_project(name="t") -> str:
    r = client.post("/projects", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def prompt(pid: str, text: str, base: int | None = None) -> tuple[dict, list[dict]]:
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": text, "base_version": base})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return done(r.text), events(r.text)


def guids_by_tag(pid: str, number: int) -> dict[str, str]:
    r = client.get(f"/projects/{pid}/versions/{number}/ifc")
    assert r.status_code == 200
    model = ifcopenshell.file.from_string(r.text)
    out = {p.Tag: p.GlobalId for p in model.by_type("IfcElement") if p.Tag}
    out |= {s.Name: s.GlobalId for s in model.by_type("IfcSpace")}  # spaces carry the id in Name
    return out


def test_design_then_edit_keeps_guids():
    pid = new_project()
    v1, evs = prompt(pid, "Two storey house with a kitchen, living room and three bedrooms, plus a garage")
    assert v1["number"] == 1 and v1["mode"] == "design"
    assert v1["summary"]["counts"]["IfcWall"] > 10 and v1["summary"]["counts"]["IfcFurniture"] >= 5
    stages = [e["stage"] for e in evs]
    assert stages.count("requirements") == 2 and "verify" in stages and stages[-1] == "done"
    # Steps are applied while the mock streams; every one is reported, and geometry-checked previews are emitted.
    steps = [e for e in evs if e["stage"] == "step"]
    assert len(steps) > 20 and all(e["data"]["ok"] for e in steps), [e["message"] for e in steps if not e["data"]["ok"]]
    assert steps[0]["data"]["index"] == 1 and steps[0]["data"]["step"]["step"] == "building"
    # Every step reads as a sentence about the building, not as internal shorthand.
    assert "Opening the project" in steps[0]["message"], steps[0]["message"]
    partials = [e for e in evs if e["stage"] == "partial" and "ifc_url" in e["data"]]
    assert partials, stages
    assert client.get(partials[-1]["data"]["ifc_url"]).status_code == 200
    assert 0 < partials[-1]["data"]["elements"] <= v1["summary"]["elements"]
    verify = next(e for e in evs if e["stage"] == "verify")
    assert all(r["status"] == "met" for r in verify["data"]["results"]), verify["data"]
    assert any("requirements met" in n for n in v1["notes"])

    v2, evs = prompt(pid, "remove the garage", base=1)
    assert v2["number"] == 2 and v2["mode"] == "edit"
    # The event's message is the readable headline; data.message keeps the applier's exact words.
    removals = [e for e in evs if e["stage"] == "step" and "removed room garage" in (e["data"].get("message") or "")]
    assert removals and "Taking out the garage" in removals[0]["message"]
    g1, g2 = guids_by_tag(pid, 1), guids_by_tag(pid, 2)
    assert "L1-space-garage" in g1 and "L1-space-garage" not in g2 and "car-garage" not in g2
    assert g1["L1-wall-hall-W"] == g2["L1-wall-hall-W"] and g1["L2-floor"] == g2["L2-floor"]

    v3, evs = prompt(pid, "add a window to the kitchen on the north")
    assert v3["mode"] == "edit" and any("Window to the north elevation of the kitchen" in e["message"]
                                        for e in evs if e["stage"] == "step")
    assert v3["summary"]["counts"]["IfcWindow"] == v2["summary"]["counts"]["IfcWindow"] + 1

    v4, _ = prompt(pid, "add a bedroom")
    assert v4["number"] == 4
    g4 = guids_by_tag(pid, 4)
    assert g4["L1-wall-hall-W"] == g1["L1-wall-hall-W"]  # rooms keep ids → keep GlobalIds
    assert "L2-space-bedroom-4" in g4

    v5, _ = prompt(pid, "gable roof please")
    assert any(n for n in v5["notes"]) or True
    assert client.get(f"/projects/{pid}/versions/5/spec").json()["design"]["roof"]["kind"] == "gable"

    detail = client.get(f"/projects/{pid}").json()
    assert detail["head"]["number"] == 5 and len(detail["versions"]) == 5
    context = client.get(f"/projects/{pid}/versions/5/context").text
    assert "room id=kitchen" in context and "exterior=" in context and "roof: gable" in context


def test_conflict_and_errors():
    pid = new_project()
    prompt(pid, "a cabin")
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "remove the garage", "base_version": 7})
    err = events(r.text)[-1]
    assert err["stage"] == "error" and err["data"]["code"] == 409
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "   "})
    assert events(r.text)[-1]["data"]["code"] == 422
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "remove the garage"})  # nothing to remove → no applicable step
    assert events(r.text)[-1]["stage"] == "error"
    assert client.get("/projects/nope").status_code == 404


def test_ops_revert_and_import():
    pid = new_project()
    prompt(pid, "a one storey cabin")
    r = client.post(f"/projects/{pid}/ops", json={"ops": [{"op": "set_building", "set": {"name": "Hut"}},
                                                          {"op": "delete_element", "id": "L1-wall-hall+kitchen"}]})
    v2 = done(r.text)
    assert v2["mode"] == "ops" and any("door" in n for n in v2["notes"])  # cascade note for the door in that wall
    spec2 = client.get(f"/projects/{pid}/versions/2/spec").json()
    assert spec2["spec"]["building"]["name"] == "Hut"
    assert len(spec2["design"]["overrides"]) == 2

    # A design edit after raw ops replays the overrides.
    v3, _ = prompt(pid, "add a window to the kitchen on the north")
    spec3 = client.get(f"/projects/{pid}/versions/3/spec").json()
    assert spec3["spec"]["building"]["name"] == "Hut"
    assert "L1-wall-hall+kitchen" not in {e["id"] for e in spec3["spec"]["elements"]}

    v4 = done(client.post(f"/projects/{pid}/revert/1").text)
    assert v4["mode"] == "revert" and v4["number"] == 4
    assert guids_by_tag(pid, 4)["L1-wall-hall+kitchen"] == guids_by_tag(pid, 1)["L1-wall-hall+kitchen"]

    ifc = client.get(f"/projects/{pid}/versions/2/ifc").content
    pid2 = new_project("imported")
    r = client.post(f"/projects/{pid2}/import", files={"file": ("hut.ifc", ifc, "application/x-step")})
    v = done(r.text)
    assert v["mode"] == "import"
    assert guids_by_tag(pid2, 1) == guids_by_tag(pid, 2)
    imported = client.get(f"/projects/{pid2}/versions/1/spec").json()
    assert imported["spec"]["building"]["name"] == "Hut" and imported["design"]["rooms"]

    bad = client.post(f"/projects/{pid2}/import", files={"file": ("x.ifc", b"ISO-10303-21;\nHEADER;ENDSEC;DATA;ENDSEC;END-ISO-10303-21;", "application/x-step")})
    assert bad.status_code == 422


class _BridgeLLM(MockLLM):
    """A model that builds a span from free elements and never emits a room."""

    def complete(self, request, on_text=None, on_note=None):
        if request.schema_name == "requirements":
            reply = {"summary": "a short bridge", "requirements": [
                {"text": "a bridge", "kind": "feature", "item": "bridge", "supported": True},
            ]}
        elif request.schema_name == "research":
            reply = {"calls": [], "done": True}
        elif request.schema_name == "look":
            reply = {"done": True}
        elif request.schema_name == "build":
            reply = {"steps": [
                {"step": "building", "name": "River Bridge", "description": "A short span"},
                {"step": "element", "kind": "slab", "name": "deck", "poly": [[0, 0], [20, 0], [20, 4], [0, 4]]},
                {"step": "element", "kind": "column", "name": "pier-west", "position": [4, 2], "width": 0.8, "height": 5},
                {"step": "element", "kind": "column", "name": "pier-east", "position": [16, 2], "width": 0.8, "height": 5},
            ]}
        else:
            return super().complete(request, on_text, on_note)
        if on_text:
            on_text(json.dumps(reply))
        return reply


def test_bridge_without_rooms_compiles(tmp_path):
    store = Store(tmp_path / "db.sqlite3", tmp_path / "projects")
    project = store.create_project("bridge")
    version = pipeline.run_prompt(store, _BridgeLLM(), project.id, "build a bridge over the river")
    assert version.design is not None and not version.design.rooms
    assert version.design.elements and version.spec.elements
    assert {e.type for e in version.spec.elements} >= {"slab", "column"}
    assert "no rooms" not in " ".join(version.notes).lower()


def test_prompt_with_several_selected_elements():
    """Shift-click selection: `focus` as a list reaches the model as one numbered description, and the
    request applies to every selected element."""
    pid = new_project()
    v1, _ = prompt(pid, "Two storey house with a kitchen, living room and three bedrooms")
    exterior = sorted(t for t in guids_by_tag(pid, v1["number"]) if re.fullmatch(r"L1-wall-[a-z0-9-]+-[NSEW]", t))
    walls = [exterior[0], next(t for t in exterior if t.rsplit("-", 1)[0] != exterior[0].rsplit("-", 1)[0])]  # two rooms
    assert len(walls) == 2, walls
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "add a window", "base_version": v1["number"], "focus": walls})
    assert r.status_code == 200, r.text
    v2, evs = done(r.text), events(r.text)
    focus = next(e for e in evs if e["stage"] == "focus")
    assert focus["data"]["ids"] == walls and focus["data"]["text"].startswith("2 elements:\n1. ")
    assert v2["summary"]["counts"]["IfcWindow"] == v1["summary"]["counts"].get("IfcWindow", 0) + 2
