"""Export formats for handing a file to somebody outside the project: the validation report and the
IFC stamped with its provenance."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as element_util
from fastapi.testclient import TestClient

from core.validate import validate_ifc
from main import app
from tests.sse import done

client = TestClient(app)
DESIGN = "Two storey house with a kitchen, living room and two bedrooms"
EDIT = "add a bedroom"
_shared: dict[str, str] = {}


def new_project(name: str, edit: bool = True) -> str:
    pid = client.post("/projects", json={"name": name}).json()["id"]
    done(client.post(f"/projects/{pid}/prompt", json={"prompt": DESIGN}).text)
    if edit:
        done(client.post(f"/projects/{pid}/prompt", json={"prompt": EDIT, "base_version": 1}).text)
    return pid


def project() -> str:
    """One project with two versions for the whole module: a prompt takes a while, and these tests only
    read it. A test that changes a stored file makes its own with `new_project`."""
    if "pid" not in _shared:
        _shared["pid"] = new_project("export validation")
    return _shared["pid"]


def export(pid: str, number: int, fmt: str, **params):
    return client.get(f"/projects/{pid}/versions/{number}/export", params={"format": fmt, **params})


def stored_path(pid: str, number: int) -> Path:
    detail = client.get(f"/projects/{pid}").json()
    return Path(next(v for v in detail["versions"] if v["number"] == number)["ifc_path"])


def test_validation_report_passes_a_generated_version():
    pid = project()
    r = export(pid, 2, "validation")
    assert r.status_code == 200, r.text
    assert f'filename="{pid}-v2.validation.json"' in r.headers["content-disposition"]
    report = r.json()
    assert report["ok"] and not report["thorough"]
    assert {c["status"] for c in report["checks"]} <= {"pass", "warn"}
    assert not [i for i in report["issues"] if i["level"] == "error"]
    assert report["counts"]["IfcWall"] > 4 and report["counts"]["IfcBuildingStorey"] == 2


def test_thorough_validation_includes_the_schema_rules():
    report = export(project(), 1, "validation", thorough=True).json()
    assert report["ok"] and report["thorough"]
    assert report["checks"][0]["name"] == "IFC schema and rules"


def test_stamped_ifc_carries_its_provenance_and_the_stored_file_is_untouched():
    pid = project()
    path = stored_path(pid, 2)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    r = export(pid, 2, "stamped", project_name="Maple Street House", author="Ada Lovelace", organization="NoCoast")
    assert r.status_code == 200, r.text
    assert f'filename="{pid}-v2.stamped.ifc"' in r.headers["content-disposition"]

    model = ifcopenshell.file.from_string(r.content.decode())
    assert model.header.file_name.author == ("Ada Lovelace",)
    assert model.header.file_name.organization == ("NoCoast",)
    ifc_project = model.by_type("IfcProject")[0]
    assert ifc_project.Name == "Maple Street House"
    pset = element_util.get_psets(ifc_project)["NoCoast_Export"]
    assert pset["SourceProject"] == pid and pset["SourceVersion"] == 2
    assert pset["ExportedBy"] == "Ada Lovelace" and pset["ValidationStatus"] == "passed"
    history = pset["PromptHistory"].splitlines()
    assert history[0].startswith("v1 [design") and "kitchen" in history[0]
    assert history[1].startswith("v2 [") and history[1].endswith(f": {EDIT}")

    stored = ifcopenshell.open(str(path))
    assert {e.GlobalId for e in stored.by_type("IfcElement")} == {e.GlobalId for e in model.by_type("IfcElement")}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert validate_ifc(model).ok


def test_stamp_without_details_still_records_where_the_file_came_from():
    pid = project()
    model = ifcopenshell.file.from_string(export(pid, 1, "stamped").content.decode())
    pset = element_util.get_psets(model.by_type("IfcProject")[0])["NoCoast_Export"]
    assert pset["SourceProject"] == pid and pset["SourceVersion"] == 1 and "ExportedBy" not in pset
    assert pset["PromptHistory"].startswith("v1 [design")


def test_a_stamped_file_can_be_imported_back():
    pid = project()
    stamped = export(pid, 2, "stamped", author="Ada").content
    other = client.post("/projects", json={"name": "round trip"}).json()["id"]
    version = done(client.post(f"/projects/{other}/import", files={"file": ("stamped.ifc", stamped, "application/x-step")}).text)
    assert version["mode"] == "import"
    assert client.get(f"/projects/{other}/versions/1/spec").json()["design"]["rooms"]


def test_long_prompt_history_is_written_as_text_and_stays_valid():
    pid = client.post("/projects", json={"name": "long"}).json()["id"]
    done(client.post(f"/projects/{pid}/prompt", json={"prompt": DESIGN + ", " + "and generous windows " * 20}).text)
    r = export(pid, 1, "stamped", thorough=True)
    assert r.status_code == 200, r.text
    model = ifcopenshell.file.from_string(r.content.decode())
    prop = next(p for p in model.by_type("IfcPropertySingleValue") if p.Name == "PromptHistory")
    assert prop.NominalValue.is_a("IfcText") and len(prop.NominalValue.wrappedValue) > 255
    assert validate_ifc(model, thorough=True).ok


def test_bundle_includes_the_validation_report():
    pid = project()
    with zipfile.ZipFile(io.BytesIO(export(pid, 2, "zip").content)) as zf:
        assert f"{pid}-v2.validation.json" in zf.namelist()
        assert json.loads(zf.read(f"{pid}-v2.validation.json"))["ok"]
        assert "validation.json" in zf.read("README.md").decode()


def test_a_broken_version_fails_validation_and_says_why():
    pid = new_project("broken", edit=False)  # its own project: the stored file is changed below
    path = stored_path(pid, 1)
    model = ifcopenshell.open(str(path))
    walls = model.by_type("IfcWall")
    walls[1].GlobalId = walls[0].GlobalId  # duplicate id: a real problem for receiving tools
    model.write(str(path))

    report = export(pid, 1, "validation").json()
    assert not report["ok"]
    assert any(i["code"] == "guid" for i in report["issues"])
    stamped = ifcopenshell.file.from_string(export(pid, 1, "stamped").content.decode())
    assert element_util.get_psets(stamped.by_type("IfcProject")[0])["NoCoast_Export"]["ValidationStatus"] == "failed"


def test_bad_inputs_are_rejected():
    pid = project()
    assert export(pid, 9, "validation").status_code == 404
    assert export(pid, 1, "stamped", author="x" * 201).status_code == 422
    assert export(pid, 1, "pdf").status_code == 400


def test_an_element_outside_a_storey_is_a_warning_not_an_error():
    model = ifcopenshell.open(str(stored_path(project(), 1)))
    wall = model.by_type("IfcWall")[0]
    for rel in list(model.by_type("IfcRelContainedInSpatialStructure")):
        if wall in rel.RelatedElements:
            rel.RelatedElements = [e for e in rel.RelatedElements if e != wall]
    report = validate_ifc(model)
    assert report.ok
    warn = next(i for i in report.issues if i.code == "uncontained")
    assert warn.level == "warning" and wall.Name in warn.message
