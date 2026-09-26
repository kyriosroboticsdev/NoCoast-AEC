"""Uploaded IFC components end to end: upload (normalised to IFC4/metres), place by prompt, move,
rotate, remove, stable GlobalIds across versions, lift round trip, and rejection of bad uploads."""

import io

import ifcopenshell
import ifcopenshell.util.element as element_util
import ifcopenshell.util.placement as placement_util
import pytest
from fastapi.testclient import TestClient

from export.validate import validate_ifc
from ifc.lifter import lift
from main import app
from tests.fixtures.make_components import make_island
from tests.sse import done

client = TestClient(app)


@pytest.fixture(scope="module")
def island_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("components")
    return {
        "mm": make_island(d / "kitchen-island-mm.ifc", millimetres=True, name="Kitchen island"),
        "2x3": make_island(d / "bench-2x3.ifc", millimetres=False, schema="IFC2X3", name="Garden bench"),
    }


def new_project() -> str:
    return client.post("/projects", json={"name": "Components"}).json()["id"]


def prompt(pid: str, text: str, base: int | None = None) -> dict:
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": text, "base_version": base})
    assert r.status_code == 200, r.text
    return done(r.text)


def upload(pid: str, *paths) -> dict:
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    r = client.post(f"/projects/{pid}/components", files=files)
    assert r.status_code == 200, r.text
    return r.json()


def version_model(pid: str, n: int) -> ifcopenshell.file:
    r = client.get(f"/projects/{pid}/versions/{n}/ifc")
    assert r.status_code == 200
    return ifcopenshell.file.from_string(r.text)


def component_products(model: ifcopenshell.file, cid: str) -> list:
    return [e for e in model.by_type("IfcElement") if e.Tag == cid or str(e.Tag or "").startswith(f"{cid}#")]


def test_upload_normalises_units_and_schema(island_files):
    pid = new_project()
    res = upload(pid, island_files["mm"], island_files["2x3"])
    assert res["errors"] == []
    by_name = {c["name"]: c for c in res["added"]}
    island, bench = by_name["Kitchen island"], by_name["Garden bench"]
    assert island["unit_in"] == "millimetre" and island["schema_in"] == "IFC4"
    assert bench["unit_in"] == "metre" and bench["schema_in"] == "IFC2X3"
    for c in (island, bench):  # both measured in metres after normalisation
        assert (c["width"], c["depth"], c["height"]) == (1.9, 1.0, 0.9)
        assert c["elements"] == 2 and c["counts"] == {"IfcFurnishingElement": 2}
    listed = client.get(f"/projects/{pid}/components").json()
    assert [c["id"] for c in listed] == [island["id"], bench["id"]]


def test_bad_uploads_are_reported_per_file(island_files):
    pid = new_project()
    files = [
        ("files", ("notes.txt", b"hello", "text/plain")),
        ("files", ("broken.ifc", b"ISO-10303-21;\nHEADER;\nnonsense", "application/octet-stream")),
        ("files", (island_files["mm"].name, island_files["mm"].read_bytes(), "application/octet-stream")),
    ]
    res = client.post(f"/projects/{pid}/components", files=files).json()
    assert [c["name"] for c in res["added"]] == ["Kitchen island"]
    errors = {e["filename"]: e["error"] for e in res["errors"]}
    assert "only .ifc files" in errors["notes.txt"]
    assert "broken.ifc" in errors


def test_place_move_rotate_remove_keeps_ids_and_validity(island_files):
    pid = new_project()
    v1 = prompt(pid, "Two storey house with a kitchen, living room and three bedrooms and a garage")
    upload(pid, island_files["mm"])

    v2 = prompt(pid, "place the kitchen island in the kitchen", base=v1["number"])
    assert v2["summary"]["counts"].get("IfcFurnishingElement", 0) >= 2
    model = version_model(pid, v2["number"])
    comps = [e for e in model.by_type("IfcElement") if "NoCoast_Spec" in element_util.get_psets(e)
             and '"type":"component"' in element_util.get_psets(e)["NoCoast_Spec"]["Json"]]
    assert len(comps) == 1
    cid = comps[0].Tag
    products = component_products(model, cid)
    assert len(products) == 2
    assert all(element_util.get_container(p) is not None for p in products)
    report = validate_ifc(model, thorough=True)
    assert report.ok, [i.message for i in report.issues][:5]
    guids_v2 = {p.Tag: p.GlobalId for p in products}
    base_v2 = placement_util.get_local_placement(comps[0].ObjectPlacement)[:3, 3].copy()

    v3 = prompt(pid, "add a bedroom", base=v2["number"])  # unrelated edit: component untouched
    assert {p.Tag: p.GlobalId for p in component_products(version_model(pid, v3["number"]), cid)} == guids_v2

    v4 = prompt(pid, "move the kitchen island to the north wall", base=v3["number"])
    moved = version_model(pid, v4["number"])
    after = component_products(moved, cid)
    assert {p.Tag: p.GlobalId for p in after} == guids_v2  # same identities after the move
    head = next(p for p in after if p.Tag == cid)
    assert (placement_util.get_local_placement(head.ObjectPlacement)[:3, 3] != base_v2).any()

    v5 = prompt(pid, "rotate the kitchen island by 90 degrees", base=v4["number"])
    spec = client.get(f"/projects/{pid}/versions/{v5['number']}/spec").json()["spec"]
    placed = next(e for e in spec["elements"] if e["type"] == "component")
    assert placed["rotation"] == 90

    # The lifter reads the component back as one element (its extra part is skipped).
    path = client.get(f"/projects/{pid}").json()["versions"][-1]["ifc_path"]
    lifted, design, guids = lift(path)
    assert sum(1 for e in lifted.elements if e.type == "component") == 1
    assert design is not None and design.components and design.components[0].id == cid

    v6 = prompt(pid, f"remove {cid}", base=v5["number"])
    assert component_products(version_model(pid, v6["number"]), cid) == []


def test_new_design_can_place_an_uploaded_component(island_files):
    pid = new_project()
    upload(pid, island_files["mm"])
    v1 = prompt(pid, "Two storey house with a kitchen, living room and three bedrooms; put the kitchen island in the kitchen")
    spec = client.get(f"/projects/{pid}/versions/{v1['number']}/spec").json()["spec"]
    placed = [e for e in spec["elements"] if e["type"] == "component"]
    assert len(placed) == 1 and placed[0]["asset"] == "kitchen-island"


def test_deleting_an_upload_keeps_old_versions_compiling(island_files):
    pid = new_project()
    v1 = prompt(pid, "Two storey house with a kitchen, living room and three bedrooms")
    cid = upload(pid, island_files["mm"])["added"][0]["id"]
    v2 = prompt(pid, "place the kitchen island in the kitchen", base=v1["number"])
    assert client.delete(f"/projects/{pid}/components/{cid}").status_code == 200
    assert client.get(f"/projects/{pid}/components").json() == []
    # The next edit no longer offers it, and drops the placement with a note instead of failing.
    v3 = prompt(pid, "add a bedroom", base=v2["number"])
    spec = client.get(f"/projects/{pid}/versions/{v3['number']}/spec").json()["spec"]
    assert not [e for e in spec["elements"] if e["type"] == "component"]
    assert client.get(f"/projects/{pid}/versions/{v2['number']}/ifc").status_code == 200
