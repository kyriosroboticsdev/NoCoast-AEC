"""The research loop (tool calls into bricks and skills), the mock's use of it, and the pipeline end to end."""

from fastapi.testclient import TestClient

from agents.brick_words import mentioned_bricks
from agents.template_planner import parse_requirements
from core.issues import Issue
from core.pipeline import Feedback, _verify, build_round
from core.research import TOOLBOX_CAP, Toolbox, research, run_tool
from llm.mock import MockLLM
from main import app
from schemas.design import Design
from schemas.research import MAX_CALLS, ResearchTurn, ToolCall
from schemas.steps import Step, apply_step
from tests.sse import done, events

client = TestClient(app)


def _room(w=5, d=4, name="Kitchen") -> Design:
    d_, _ = apply_step(Design(name="t"), Step(step="room", name=name, rect=[0, 0, w, d]))
    return d_


def test_tools_search_read_and_check():
    box = Toolbox()
    hits = run_tool(ToolCall(tool="search_bricks", query="fresh air ventilation"), Design(), box)
    assert "mvhr_unit" in hits or "air_handling_unit" in hits
    assert "no bricks match" in run_tool(ToolCall(tool="search_bricks", query="zzzz"), Design(), box)
    card = run_tool(ToolCall(tool="get_brick", id="gas_boiler"), Design(), box)
    assert "needs" in card and "params:" in card
    assert "closest" in run_tool(ToolCall(tool="get_brick", id="gas_boilr"), Design(), box)
    assert "structural-spans" in run_tool(ToolCall(tool="list_skills"), Design(), box)
    assert "SKILL hvac-systems" in run_tool(ToolCall(tool="get_skill", id="hvac-systems"), Design(), box)
    assert run_tool(ToolCall(tool="check_design"), Design(), box).startswith("the design is empty")
    assert "unsupported" in run_tool(ToolCall(tool="structure_report"), _room(12, 10, "Hall"), box)
    assert box.bricks == ["gas_boiler"] and box.skills == ["hvac-systems"]


def test_toolbox_puts_skills_first_and_is_capped():
    box = Toolbox()
    box.add("search:x|None", "search")
    box.add("brick:a", "card")
    box.add("skill:s", "skill")
    assert box.text().split("\n\n") == ["skill", "card", "search"]
    for i in range(40):
        box.add(f"brick:{i}", "x" * 1000)
    assert len(box.text()) <= TOOLBOX_CAP


def test_research_turns_stop_when_done_and_matched_skills_are_always_included():
    turns = iter([{"calls": [{"tool": "search_bricks", "query": "heat pump"}], "done": False}, {"calls": [], "done": True},
                  {"calls": [{"tool": "list_skills"}]}])
    events_ = []
    box = research(lambda log: next(turns), "a kitchen with an island", Design(), lambda *a: events_.append(a), rounds=3)
    assert "kitchen-layout" in box.skills
    assert [e[0] for e in events_].count("tool") == 1
    assert next(turns)["calls"][0]["tool"] == "list_skills"  # the third turn was never asked for


def test_an_invalid_research_turn_ends_research_without_failing():
    box = research(lambda log: {"calls": [{"tool": "rm -rf"}]}, "house", Design(), lambda *a: None, rounds=2)
    assert box.bricks == []


def test_research_turn_caps_calls():
    turn = ResearchTurn.model_validate({"calls": [{"tool": "list_skills"}] * 20})
    assert len(turn.calls) == MAX_CALLS


def test_mock_researches_the_bricks_a_prompt_names():
    prompt = "a house with a heat pump, solar panels and an elevator"
    assert {m.brick for m in mentioned_bricks(prompt)} == {"air_source_heat_pump", "solar_pv_array", "passenger_elevator"}
    first = MockLLM()._research(prompt, {"log": [], "checklist": []})
    rest = MockLLM()._research(prompt, {"log": ["x"] * len(first["calls"]), "checklist": []})
    tools = [c["tool"] for c in first["calls"] + rest["calls"]]
    assert tools.count("search_bricks") == 3 and tools.count("get_brick") == 3 and "get_skill" in tools
    assert len(first["calls"]) <= MAX_CALLS and rest["done"]
    assert MockLLM()._research("a small cabin", {"log": []}) == {"calls": [], "done": True}


def test_plain_house_prompts_name_no_bricks_and_asset_requirements_are_extracted():
    assert mentioned_bricks("Two storey house with a kitchen, living room and three bedrooms, plus a garage and a porch") == []
    reqs = parse_requirements("a cottage with two trees and a swimming pool")
    assets = {(r.item, r.value) for r in reqs if r.kind == "asset"}
    assert assets == {("tree", 2), ("swimming_pool", 1)} and all(r.supported for r in reqs)


def test_a_structure_issue_is_fixed_by_a_coordination_round():
    design = _room(12, 10, "Hall")
    results, issues = _verify(design, [], lambda *a: None)
    assert any(i.kind == "structure" for i in issues)
    stream = build_round(MockLLM(), "a hall", design, [], lambda *a: None, guids={}, first_index=0, feedback=Feedback(issues=issues))
    assert stream.accepted and any(b.brick == "steel_beam" for b in stream.design.bricks)
    _, after = _verify(stream.design, [], lambda *a: None)
    assert not [i for i in after if i.severity == "error"]


def test_fix_round_labels_name_only_what_is_being_fixed():
    warning = Issue("structure", "warning", "long span")
    error = Issue("structure", "error", "no support")
    assert Feedback().label(False) == "building the design"
    assert Feedback(issues=[warning]).label(True) == "editing the design"
    assert Feedback(unmet=["x"], issues=[error]).label(False) == "fixing unmet requirements and coordination issues"


def _prompt(pid: str, text: str):
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": text})
    assert r.status_code == 200, r.text
    return done(r.text), events(r.text)


def test_pipeline_researches_places_bricks_and_resolves_coordination_over_sse():
    pid = client.post("/projects", json={"name": "bricks"}).json()["id"]
    v1, evs = _prompt(pid, "A two storey house with a kitchen, living room and three bedrooms, a lift, solar panels, "
                           "a gas boiler and two trees in the garden")
    stages = [e["stage"] for e in evs]
    assert "research" in stages and "tool" in stages and "coordinate" in stages
    assert stages.index("research") < stages.index("build")
    tools = [e["data"]["tool"] for e in evs if e["stage"] == "tool"]
    assert "search_bricks" in tools and "get_brick" in tools and "get_skill" in tools
    first = next(e for e in evs if e["stage"] == "coordinate")
    assert {i["kind"] for i in first["data"]["issues"]} >= {"service"}          # the boiler needs gas and a flue …
    last = [e for e in evs if e["stage"] == "coordinate"][-1]
    assert not [i for i in last["data"]["issues"] if i["severity"] == "error"]  # … which the fix round added
    verify = [e for e in evs if e["stage"] == "verify"][-1]
    assert all(r["status"] == "met" for r in verify["data"]["results"]), verify["data"]
    counts = v1["summary"]["counts"]
    assert counts.get("IfcTransportElement") == 1 and counts.get("IfcSolarDevice") == 1 and counts.get("IfcGeographicElement") == 2
    assert counts.get("IfcBoiler") == 1

    v2, evs = _prompt(pid, "add a heat pump")
    assert v2["summary"]["counts"].get("IfcUnitaryEquipment", 0) >= 1
    spec = client.get(f"/projects/{pid}/versions/2/spec").json()
    assert any(b["brick"] == "air_source_heat_pump" for b in spec["design"]["bricks"])


def test_library_endpoints():
    r = client.get("/bricks", params={"q": "hot water"}).json()
    assert r["total"] >= 150 and r["bricks"] and "water_heater" in {b["id"] for b in r["bricks"]}
    listing = client.get("/bricks", params={"discipline": "structure", "limit": 100}).json()["bricks"]
    assert listing and all(b["discipline"] == "structure" for b in listing)
    brick = client.get("/bricks/steel_beam").json()
    assert brick["host"] == "span" and "card" in brick
    missing = client.get("/bricks/steel_beem")
    assert missing.status_code == 404 and "steel_beam" in missing.json()["detail"]
    skills = client.get("/skills").json()
    assert "placing-bricks" in {s["name"] for s in skills}
    assert "span" in client.get("/skills/structural-spans").json()["body"]
    assert client.get("/skills/nope").status_code == 404
