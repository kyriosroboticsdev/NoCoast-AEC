"""Final-deliverable export: validation, stamping and the zip bundle, through the HTTP API."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as element_util
from fastapi.testclient import TestClient

from export.validate import validate_ifc
from main import app
from tests.sse import done

client = TestClient(app)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # the export only checks the signature


def project_with_two_versions(name="Export test"):
    pid = client.post("/projects", json={"name": name}).json()["id"]
    done(client.post(f"/projects/{pid}/prompt", json={"prompt": "Two storey house with a kitchen and two bedrooms"}).text)
    done(client.post(f"/projects/{pid}/prompt", json={"prompt": "add a bedroom", "base_version": 1}).text)
    return pid


def export(pid, number, files=None, **options):
    return client.post(f"/projects/{pid}/versions/{number}/export",
                       data={"options": json.dumps({"thorough": False, **options})}, files=files or [])


def stored_path(pid, number) -> Path:
    detail = client.get(f"/projects/{pid}").json()
    return Path(next(v for v in detail["versions"] if v["number"] == number)["ifc_path"])


def test_validate_endpoint_passes_a_generated_version():
    pid = project_with_two_versions()
    r = client.get(f"/projects/{pid}/versions/2/validate")
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["ok"] and not report["thorough"]
    assert {c["status"] for c in report["checks"]} == {"pass"}
    assert report["counts"]["IfcWall"] > 4 and report["counts"]["IfcBuildingStorey"] == 2


def test_thorough_validation_includes_schema_rules():
    pid = project_with_two_versions()
    report = client.get(f"/projects/{pid}/versions/1/validate", params={"thorough": True}).json()
    assert report["ok"] and report["thorough"]
    assert report["checks"][0]["name"] == "IFC schema and rules"


def test_ifc_export_is_stamped_and_leaves_the_stored_version_untouched():
    pid = project_with_two_versions()
    path = stored_path(pid, 2)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    r = export(pid, 2, project_name="Maple Street House", author="Ada Lovelace", organization="NoCoast")
    assert r.status_code == 200, r.text
    assert r.headers["x-export-filename"] == "maple-street-house-v2.ifc"
    assert r.headers["x-validation-status"] == "passed"
    assert 'filename="maple-street-house-v2.ifc"' in r.headers["content-disposition"]

    model = ifcopenshell.file.from_string(r.content.decode())
    assert model.header.file_name.author == ("Ada Lovelace",)
    assert model.header.file_name.organization == ("NoCoast",)
    project = model.by_type("IfcProject")[0]
    assert project.Name == "Maple Street House"
    pset = element_util.get_psets(project)["NoCoast_Export"]
    assert pset["SourceProject"] == pid and pset["SourceVersion"] == 2
    assert pset["ExportedBy"] == "Ada Lovelace" and pset["ValidationStatus"] == "passed"
    history = pset["PromptHistory"].splitlines()
    assert history[0].startswith("v1 [design") and "kitchen" in history[0]
    assert history[1].startswith("v2 [") and history[1].endswith(": add a bedroom")

    # Same element identities as the stored version, and the stored file itself is unchanged.
    stored = ifcopenshell.open(str(path))
    assert {e.GlobalId for e in stored.by_type("IfcElement")} == {e.GlobalId for e in model.by_type("IfcElement")}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert validate_ifc(model).ok


def test_long_prompt_history_uses_ifctext_and_stays_valid():
    pid = client.post("/projects", json={"name": "Long"}).json()["id"]
    long_prompt = "Two storey house with a kitchen and two bedrooms, " + "and generous windows " * 20
    done(client.post(f"/projects/{pid}/prompt", json={"prompt": long_prompt}).text)
    r = export(pid, 1, thorough=True)
    assert r.status_code == 200, r.text
    model = ifcopenshell.file.from_string(r.content.decode())
    prop = next(p for p in model.by_type("IfcPropertySingleValue") if p.Name == "PromptHistory")
    assert prop.NominalValue.is_a("IfcText") and len(prop.NominalValue.wrappedValue) > 255
    assert validate_ifc(model, thorough=True).ok


def test_zip_bundle_contents_and_manifest():
    pid = project_with_two_versions("Bundle Test")
    files = [("snapshots", ("iso.png", PNG, "image/png")), ("snapshots", ("top.png", PNG, "image/png"))]
    r = export(pid, 2, files=files, format="zip", author="Ada")
    assert r.status_code == 200, r.text
    assert r.headers["x-export-filename"] == "bundle-test-v2.zip"

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    stem = "bundle-test-v2/"
    assert names == {stem + n for n in ["bundle-test-v2.ifc", "README.md", "validation.json",
                                        "snapshots/iso.png", "snapshots/top.png", "manifest.json"]}
    manifest = json.loads(zf.read(stem + "manifest.json"))
    assert manifest["validation_ok"] and manifest["version"] == 2
    for entry in manifest["files"]:  # every listed file is present with the recorded hash
        assert hashlib.sha256(zf.read(stem + entry["path"])).hexdigest() == entry["sha256"]
    readme = zf.read(stem + "README.md").decode()
    assert "add a bedroom" in readme and "Validation: **passed**" in readme and "by Ada" in readme
    assert json.loads(zf.read(stem + "validation.json"))["ok"]


def test_strict_export_refuses_a_broken_version():
    pid = project_with_two_versions()
    path = stored_path(pid, 1)
    model = ifcopenshell.open(str(path))
    walls = model.by_type("IfcWall")
    walls[1].GlobalId = walls[0].GlobalId  # duplicate id: a real problem for receiving tools
    model.write(str(path))

    r = export(pid, 1)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert not detail["report"]["ok"]
    assert any(i["code"] == "guid" for i in detail["report"]["issues"])

    loose = export(pid, 1, strict=False)
    assert loose.status_code == 200 and loose.headers["x-validation-status"] == "failed"


def test_bad_inputs_are_rejected():
    pid = project_with_two_versions()
    assert export(pid, 9).status_code == 404
    bad_json = client.post(f"/projects/{pid}/versions/1/export", data={"options": "{nope"})
    assert bad_json.status_code == 422
    assert export(pid, 1, format="pdf").status_code == 422
    not_png = [("snapshots", ("x.png", b"GIF89a....", "image/png"))]
    assert export(pid, 1, files=not_png, format="zip").status_code == 422


def test_uncontained_element_is_a_warning_not_an_error():
    pid = project_with_two_versions()
    model = ifcopenshell.open(str(stored_path(pid, 1)))
    wall = model.by_type("IfcWall")[0]
    for rel in list(model.by_type("IfcRelContainedInSpatialStructure")):
        if wall in rel.RelatedElements:
            rel.RelatedElements = [e for e in rel.RelatedElements if e != wall]
    report = validate_ifc(model)
    assert report.ok
    warn = next(i for i in report.issues if i.code == "uncontained")
    assert warn.level == "warning" and wall.Name in warn.message
    assert next(c for c in report.checks if c.name.startswith("Elements")).status == "warn"
