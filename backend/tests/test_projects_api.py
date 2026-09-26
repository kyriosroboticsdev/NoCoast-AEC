"""The stateful project API end to end, through the mock LLM."""

import ifcopenshell
from fastapi.testclient import TestClient

from main import app
from tests.sse import done, events

client = TestClient(app)


def new_project(name="t") -> str:
    r = client.post("/projects", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def prompt(pid: str, text: str, base: int | None = None) -> dict:
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": text, "base_version": base})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return done(r.text)


def guids_by_tag(pid: str, number: int) -> dict[str, str]:
    r = client.get(f"/projects/{pid}/versions/{number}/ifc")
    assert r.status_code == 200
    model = ifcopenshell.file.from_string(r.text)
    out = {p.Tag: p.GlobalId for p in model.by_type("IfcElement") if p.Tag}
    out |= {s.Name: s.GlobalId for s in model.by_type("IfcSpace")}  # spaces carry the id in Name
    return out


def test_design_then_edit_keeps_guids():
    pid = new_project()
    v1 = prompt(pid, "Two storey house with a kitchen, living room and three bedrooms, plus a garage")
    assert v1["number"] == 1 and v1["mode"] == "design"
    assert v1["summary"]["counts"]["IfcWall"] > 5

    v2 = prompt(pid, "remove the garage", base=1)
    assert v2["number"] == 2 and v2["mode"] == "ops"
    assert all(op["op"] == "delete_element" for op in v2["ops"])
    g1, g2 = guids_by_tag(pid, 1), guids_by_tag(pid, 2)
    assert "garage-door" in g1 and "garage-door" not in g2
    assert g1["L1-wall-S"] == g2["L1-wall-S"] and g1["L2-floor"] == g2["L2-floor"]

    v3 = prompt(pid, "add a window to L1-wall-W")
    assert v3["mode"] == "ops" and v3["ops"][0]["op"] == "add_element"

    v4 = prompt(pid, "add a bedroom")
    assert v4["mode"] == "redesign" and v4["number"] == 4
    g4 = guids_by_tag(pid, 4)
    assert g4["L1-wall-S"] == g1["L1-wall-S"]  # redesign keeps ids → keeps GlobalIds
    assert "L2-space-bedroom-4" in g4

    detail = client.get(f"/projects/{pid}").json()
    assert detail["head"]["number"] == 4 and len(detail["versions"]) == 4
    assert "CURRENT MODEL" not in client.get(f"/projects/{pid}/versions/4/context").text
    assert "wall id=L1-wall-S" in client.get(f"/projects/{pid}/versions/4/context").text


def test_conflict_and_errors():
    pid = new_project()
    prompt(pid, "a cabin")
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "remove the garage", "base_version": 7})
    err = events(r.text)[-1]
    assert err["stage"] == "error" and err["data"]["code"] == 409
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "   "})
    assert events(r.text)[-1]["data"]["code"] == 422
    assert client.get("/projects/nope").status_code == 404


def test_ops_revert_and_import():
    pid = new_project()
    prompt(pid, "a one storey cabin")
    r = client.post(f"/projects/{pid}/ops", json={"ops": [{"op": "set_building", "set": {"name": "Hut"}},
                                                          {"op": "delete_element", "id": "L1-wall-spine"}]})
    v2 = done(r.text)
    assert v2["mode"] == "ops" and any("door" in n for n in v2["notes"])  # cascade note for the spine doors
    spec2 = client.get(f"/projects/{pid}/versions/2/spec").json()
    assert spec2["spec"]["building"]["name"] == "Hut"

    v3 = done(client.post(f"/projects/{pid}/revert/1").text)
    assert v3["mode"] == "revert" and v3["number"] == 3
    assert guids_by_tag(pid, 3)["L1-wall-spine"] == guids_by_tag(pid, 1)["L1-wall-spine"]

    ifc = client.get(f"/projects/{pid}/versions/2/ifc").content
    pid2 = new_project("imported")
    r = client.post(f"/projects/{pid2}/import", files={"file": ("hut.ifc", ifc, "application/x-step")})
    v = done(r.text)
    assert v["mode"] == "import"
    assert guids_by_tag(pid2, 1) == guids_by_tag(pid, 2)
    assert client.get(f"/projects/{pid2}/versions/1/spec").json()["spec"]["building"]["name"] == "Hut"

    bad = client.post(f"/projects/{pid2}/import", files={"file": ("x.ifc", b"ISO-10303-21;\nHEADER;ENDSEC;DATA;ENDSEC;END-ISO-10303-21;", "application/x-step")})
    assert bad.status_code == 422


def test_prompt_streams_build_steps_layer_by_layer():
    """The reasoning panel's feed: stage events plus nested build steps, storey by storey."""
    pid = new_project()
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "Two storey house with three bedrooms and a garage"})
    evs = events(r.text)
    assert evs[-1]["stage"] == "done"
    stages = [e["stage"] for e in evs if e["stage"] != "step"]
    assert stages[0] == "program" and "compile" in stages
    steps = [e["data"] for e in evs if e["stage"] == "step"]
    done_steps = {s["id"]: s for s in steps if s["status"] == "done"}
    assert {s["id"] for s in steps if s["status"] == "running"} == set(done_steps)  # everything that starts, finishes
    layers = [s["title"] for s in done_steps.values() if s["layer"]]
    assert layers[0] == "Building Ground Floor" and layers[-1] == "Building Roof" and len(layers) >= 3
    ids = {s["id"] for s in steps}
    assert all(s["parent"] in ids for s in steps if s["parent"])
    assert any(s["title"] == "Checking geometry" for s in done_steps.values())
    # the step events come before the version they describe
    assert max(i for i, e in enumerate(evs) if e["stage"] == "step") < len(evs) - 1
