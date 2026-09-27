"""The stateful project API end to end, through the mock."""

import ifcopenshell
from fastapi.testclient import TestClient

from main import app
from tests.sse import done, events

client = TestClient(app)


def new_project(name="t") -> str:
    r = client.post("/projects", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def prompt(pid: str, text: str, base: int | None = None, focus: str | None = None) -> tuple[dict, list[dict]]:
    body = {"prompt": text, "base_version": base}
    if focus:
        body["focus"] = focus
    r = client.post(f"/projects/{pid}/prompt", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return done(r.text), events(r.text)


def guids_by_tag(pid: str, number: int) -> dict[str, str]:
    r = client.get(f"/projects/{pid}/versions/{number}/ifc")
    assert r.status_code == 200
    model = ifcopenshell.file.from_string(r.text)
    out = {}
    for product in model.by_type("IfcProduct"):
        tag = getattr(product, "Tag", None)
        if tag:
            out[tag] = product.GlobalId
        elif product.is_a("IfcSpace") and product.Name:
            out[product.Name] = product.GlobalId
    return out


def test_design_then_edit_keeps_guids():
    pid = new_project()
    v1, evs = prompt(pid, "Two storey house with a kitchen, a living room and three bedrooms, plus a garage")
    assert v1["number"] == 1 and v1["mode"] == "design"
    assert v1["summary"]["counts"]["IfcWall"] >= 8
    assert v1["summary"]["counts"]["IfcSpace"] >= 5
    assert "Garage" in v1["summary"]["spaces"]
    stages = [e["stage"] for e in evs]
    assert "requirements" in stages and "verify" in stages and stages[-1] == "done"
    steps = [e for e in evs if e["stage"] == "step"]
    assert len(steps) > 10 and all(e["data"]["ok"] for e in steps), [e["message"] for e in steps if not e["data"]["ok"]]
    assert steps[0]["data"]["index"] == 1
    partials = [e for e in evs if e["stage"] == "partial" and e["data"] and "ifc_url" in e["data"]]
    assert partials, stages
    assert client.get(partials[-1]["data"]["ifc_url"]).status_code == 200
    verify = next(e for e in evs if e["stage"] == "verify")
    assert all(r["status"] == "met" for r in verify["data"]["results"]), verify["data"]

    v2, evs = prompt(pid, "remove the garage", base=1)
    assert v2["number"] == 2 and v2["mode"] == "edit"
    assert "Garage" not in v2["summary"]["spaces"]
    g1, g2 = guids_by_tag(pid, 1), guids_by_tag(pid, 2)
    assert "space-l1-garage-1" in g1 and "space-l1-garage-1" not in g2
    assert g1["wall-l1-south"] == g2["wall-l1-south"]

    v3, _ = prompt(pid, "add a bedroom")
    assert any("Bedroom" in name for name in v3["summary"]["spaces"])
    assert guids_by_tag(pid, 3)["wall-l1-south"] == g1["wall-l1-south"]

    spec = client.get(f"/projects/{pid}/versions/3/spec").json()
    assert spec["design"] is None and spec["model"]["parts"]
    context = client.get(f"/projects/{pid}/versions/3/context").text
    assert "part id=" in context and "IfcWall" in context

    detail = client.get(f"/projects/{pid}").json()
    assert detail["head"]["number"] == 3 and len(detail["versions"]) == 3


def test_conflict_and_errors():
    pid = new_project()
    prompt(pid, "a small cabin")
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "remove the garage", "base_version": 7})
    err = events(r.text)[-1]
    assert err["stage"] == "error" and err["data"]["code"] == 409
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "   "})
    assert events(r.text)[-1]["data"]["code"] == 422
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "remove the garage"})
    assert events(r.text)[-1]["stage"] == "error"
    assert client.get("/projects/nope").status_code == 404


def test_ops_revert_and_import():
    pid = new_project()
    prompt(pid, "a small one storey cabin")
    r = client.post(f"/projects/{pid}/ops", json={"ops": [{"op": "set_model", "set": {"name": "Hut"}},
                                                          {"op": "delete", "id": "door-entrance"}]})
    v2 = done(r.text)
    assert v2["mode"] == "ops"
    spec2 = client.get(f"/projects/{pid}/versions/2/spec").json()
    assert spec2["design"] is None and spec2["model"]["name"] == "Hut"
    assert "door-entrance" not in {p["id"] for p in spec2["model"]["parts"]}

    v3 = done(client.post(f"/projects/{pid}/revert/1").text)
    assert v3["mode"] == "revert" and v3["number"] == 3
    assert guids_by_tag(pid, 3)["door-entrance"] == guids_by_tag(pid, 1)["door-entrance"]

    ifc = client.get(f"/projects/{pid}/versions/2/ifc").content
    pid2 = new_project("imported")
    r = client.post(f"/projects/{pid2}/import", files={"file": ("hut.ifc", ifc, "application/x-step")})
    v = done(r.text)
    assert v["mode"] == "import"
    assert guids_by_tag(pid2, 1)["wall-l1-south"] == guids_by_tag(pid, 2)["wall-l1-south"]
    imported = client.get(f"/projects/{pid2}/versions/1/spec").json()
    assert imported["model"]["name"] == "Hut" and imported["design"] is None

    bad = client.post(f"/projects/{pid2}/import", files={"file": ("x.ifc", b"ISO-10303-21;\nHEADER;ENDSEC;DATA;ENDSEC;END-ISO-10303-21;", "application/x-step")})
    assert bad.status_code == 422
