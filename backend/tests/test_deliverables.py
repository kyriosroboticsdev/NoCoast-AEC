"""The architect-facing deliverables of a version: code review, drawing set, cost/carbon and BCF issues."""

import csv
import io
import re
import zipfile
import zlib
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from core.derive import derive
from core.remedy import remedies
from core.review import review
from main import app
from schemas.design import Design
from tests.sse import done, events

client = TestClient(app)
HOUSE = "Two storey house with a kitchen, living room and two bedrooms"
OFFICE = "Two storey offices with an open office, two meeting rooms, reception and WCs"
STUDIO = "An architecture studio with open studio, 2 meeting rooms, model shop, kitchen and WCs over two floors"


def build(prompt: str = HOUSE) -> tuple[str, str]:
    pid = client.post("/projects", json={"name": "deliverables"}).json()["id"]
    text = client.post(f"/projects/{pid}/prompt", json={"prompt": prompt}).text
    done(text)
    return pid, text


def analysis(pid: str) -> dict:
    r = client.get(f"/projects/{pid}/versions/1/analysis")
    assert r.status_code == 200
    return r.json()


def test_run_streams_code_cost_and_delivery_before_done():
    _, text = build()
    stages = [e["stage"] for e in events(text)]
    assert stages.index("code") < stages.index("estimate") < stages.index("deliver") < stages.index("done")
    code = next(e for e in events(text) if e["stage"] == "code")
    assert code["data"]["occupancy"]["group"] == "R-3"
    assert all({"reference", "status", "title"} <= set(c) for c in code["data"]["checks"])
    deliver = next(e for e in events(text) if e["stage"] == "deliver")
    assert deliver["data"]["sheets"][0]["number"] == "G-001"


def test_house_review_is_clean_and_cites_clauses():
    rev = analysis(build()[0])["review"]
    assert rev["occupancy"]["group"] == "R-3" and rev["code"].startswith("IRC")
    assert rev["score"]["fail"] == 0 and rev["score"]["pass"] >= 8
    for check in rev["checks"]:
        assert check["status"] in {"pass", "warn", "fail", "info"}
        assert re.search(r"\d", check["reference"]) or check["status"] in ("info", "pass"), check
    numbers = [r["number"] for r in rev["rooms"]]
    assert len(numbers) == len(set(numbers)) and any(n.startswith("1") for n in numbers)
    assert 0 < rev["totals"]["nia"] < rev["totals"]["gia"]


def test_office_is_classified_as_business_with_plumbing_and_egress():
    rev = analysis(build(OFFICE)[0])["review"]
    assert rev["occupancy"]["group"] == "B" and rev["code"].startswith("IBC")
    refs = " ".join(c["reference"] for c in rev["checks"])
    assert "1006" in refs and "2902" in refs


def test_code_failures_go_back_to_the_model_before_issue():
    pid, text = build(STUDIO)
    evs = events(text)
    pre = next(e for e in evs if e["stage"] == "precheck")
    failing = {c["reference"] for c in pre["data"]["checks"]}
    assert {"IBC 1006.3.3", "IBC Table 2902.1"} <= failing
    assert all(c["fix"] >= 1 for c in pre["data"]["checks"])
    rounds = [e["data"]["round"] for e in evs if e["stage"] == "build"]
    assert rounds[-1] == "code"
    rev = analysis(pid)["review"]
    assert rev["score"]["fail"] == 0, [c for c in rev["checks"] if c["status"] == "fail"]


def test_remedies_are_buildable_and_do_not_stack_fixtures():
    pid, _ = build(STUDIO)
    design = Design.model_validate(client.get(f"/projects/{pid}/versions/1/spec").json()["design"])
    spec, _ = derive(design)
    fixes = remedies([c for c in review(spec, design)["checks"] if c["status"] == "fail"], spec, design)
    assert fixes == {}
    design.fixtures = [f for f in design.fixtures if f.kind != "toilet"]
    spec, _ = derive(design)
    failing = [c for c in review(spec, design)["checks"] if c["status"] == "fail"]
    steps = remedies(failing, spec, design)["plumbing.wc"]
    places = {(s["room"], s["side"], s["at"]) for s in steps}
    assert len(places) == len(steps) >= 2


def test_drawing_set_sheets_are_svg_and_pdf():
    pid, _ = build()
    data = analysis(pid)
    numbers = [s["number"] for s in data["sheets"]]
    assert numbers[:2] == ["G-001", "G-002"] and {"A-101", "A-102", "A-201", "A-301", "A-601"} <= set(numbers)
    for sheet in data["sheets"]:
        r = client.get(sheet["url"])
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        ElementTree.fromstring(r.content)
    assert client.get(f"/projects/{pid}/versions/1/sheets/Z-999.svg").status_code == 404

    pdf = client.get(f"/projects/{pid}/versions/1/export", params={"format": "drawings"})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF-1.")
    assert pdf.content.rstrip().endswith(b"%%EOF")
    assert pdf.content.count(b"/Type /Page ") == len(numbers)
    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf.content, re.S)
    assert streams and b"Tj" in zlib.decompress(streams[0])


def test_estimate_is_consistent():
    est = analysis(build()[0])["estimate"]
    cost, carbon = est["cost"], est["carbon"]
    assert cost["total"] == cost["direct"] + cost["general_conditions"] + cost["contingency"]
    assert cost["low"] < cost["total"] < cost["high"]
    assert abs(sum(l["total"] for l in cost["lines"]) - cost["direct"]) <= len(cost["lines"])
    assert 100 < carbon["per_m2"] < 1500 and carbon["band"] in {"A++", "A+", "A", "B", "C", "D", "E", "F", "G"}
    assert carbon["options"] and all(o["saving_kg"] > 0 for o in carbon["options"])


def test_estimate_csv_and_review_markdown():
    pid, _ = build()
    rows = list(csv.reader(io.StringIO(client.get(f"/projects/{pid}/versions/1/export",
                                                  params={"format": "estimate"}).text)))
    assert rows[0][:2] == ["uniformat", "element"] and any(r[1:2] == ["TOTAL"] for r in rows)
    md = client.get(f"/projects/{pid}/versions/1/export", params={"format": "review"}).text
    assert md.startswith("# Design review") and "## Cost plan" in md and "## Upfront carbon" in md


def test_bcf_topics_reference_ifc_guids():
    pid, _ = build(OFFICE)
    rev = analysis(pid)["review"]
    r = client.get(f"/projects/{pid}/versions/1/export", params={"format": "bcf"})
    assert r.status_code == 200 and 'issues.bcfzip"' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert "bcf.version" in names and "project.bcfp" in names
        topics = [n for n in names if n.endswith("/markup.bcf")]
        assert len(topics) == sum(1 for c in rev["checks"] if c["status"] in ("fail", "warn"))
        for t in topics:
            markup = ElementTree.fromstring(zf.read(t))
            assert markup.find("Topic/Title").text
            view = ElementTree.fromstring(zf.read(t.replace("markup.bcf", "viewpoint.bcfv")))
            assert view.find("PerspectiveCamera/CameraViewPoint/X") is not None
            for comp in view.iter("Component"):
                assert len(comp.get("IfcGuid")) == 22
