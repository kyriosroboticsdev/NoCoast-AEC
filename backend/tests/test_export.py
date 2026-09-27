"""Exporting a version: the IFC on its own, the individual artefacts, and the whole bundle."""

import csv
import io
import json
import zipfile

import ifcopenshell
from fastapi.testclient import TestClient

from main import app
from tests.sse import done

client = TestClient(app)


def build() -> tuple[str, dict]:
    pid = client.post("/projects", json={"name": "export"}).json()["id"]
    version = done(client.post(f"/projects/{pid}/prompt",
                               json={"prompt": "Two storey house with a kitchen, living room and two bedrooms"}).text)
    return pid, version


def test_version_carries_its_export_url():
    pid, version = build()
    assert version["export_url"] == f"/projects/{pid}/versions/1/export"
    assert client.get(f"/projects/{pid}").json()["head"]["export_url"] == version["export_url"]


def test_ifc_download_is_named_after_the_version():
    pid, _ = build()
    r = client.get(f"/projects/{pid}/versions/1/ifc")
    assert r.status_code == 200
    assert f'filename="{pid}-v1.ifc"' in r.headers["content-disposition"]
    assert ifcopenshell.file.from_string(r.text).by_type("IfcProject")


def test_single_artifacts():
    pid, _ = build()

    spec = client.get(f"/projects/{pid}/versions/1/export", params={"format": "spec"})
    assert spec.status_code == 200 and json.loads(spec.content)["levels"]

    design = client.get(f"/projects/{pid}/versions/1/export", params={"format": "design"})
    assert json.loads(design.content)["rooms"]

    context = client.get(f"/projects/{pid}/versions/1/export", params={"format": "context"})
    assert "room id=kitchen" in context.text

    summary = client.get(f"/projects/{pid}/versions/1/export", params={"format": "summary"})
    assert summary.text.startswith("# ") and "## Design approach" in summary.text and "## Requirements" in summary.text

    schedule = client.get(f"/projects/{pid}/versions/1/export", params={"format": "schedule"})
    rows = list(csv.DictReader(io.StringIO(schedule.text)))
    assert {r["category"] for r in rows} >= {"room", "wall", "door", "window"}
    kitchen = next(r for r in rows if r["category"] == "room" and r["name"] == "Kitchen")
    assert float(kitchen["quantity"]) > 5 and kitchen["unit"] == "m2"

    assert client.get(f"/projects/{pid}/versions/1/export", params={"format": "nope"}).status_code == 400


def test_bundle_holds_everything():
    pid, _ = build()
    r = client.get(f"/projects/{pid}/versions/1/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert f'filename="{pid}-v1.zip"' in r.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = set(zf.namelist())
        assert names == {"README.md", "guids.json"} | {f"{pid}-v1.{ext}" for ext in
                                                       ("ifc", "summary.md", "spec.json", "design.json",
                                                        "context.txt", "checks.json", "schedule.csv")}
        assert zf.read("README.md").decode().startswith("# NoCoast export")
        model = ifcopenshell.file.from_string(zf.read(f"{pid}-v1.ifc").decode())
        assert model.by_type("IfcWall") and model.by_type("IfcSpace")
        assert json.loads(zf.read("guids.json"))


def test_project_export_is_the_head_version():
    pid, _ = build()
    done(client.post(f"/projects/{pid}/prompt", json={"prompt": "add a bedroom"}).text)
    r = client.get(f"/projects/{pid}/export")
    assert f'filename="{pid}-v2.zip"' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert f"{pid}-v2.ifc" in zf.namelist()
    assert client.get("/projects/nope/export").status_code == 404


def test_exported_ifc_can_be_imported_back():
    pid, _ = build()
    with zipfile.ZipFile(io.BytesIO(client.get(f"/projects/{pid}/versions/1/export").content)) as zf:
        ifc = zf.read(f"{pid}-v1.ifc")
    other = client.post("/projects", json={"name": "round trip"}).json()["id"]
    v = done(client.post(f"/projects/{other}/import", files={"file": ("house.ifc", ifc, "application/x-step")}).text)
    assert v["mode"] == "import" and v["summary"]["elements"] > 10
