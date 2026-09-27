"""The look loop (core/look.py): the model is shown screenshots, picks more views, and what it sees goes
back into a fix round; the adapters carry the images; the API serves every screenshot."""

from fastapi.testclient import TestClient

import config
from core import pipeline
from core.look import first_views, look, shooter
from llm import get_llm
from llm.base import Image, LLMRequest
from llm.claude import user_content as claude_content
from llm.mock import MockLLM
from llm.ollama import user_message as ollama_message
from llm.openai_compat import user_content as openai_content
from llm.prompts import SEEN_INTRO
from main import app
from render.png import png_size
from schemas.look import View
from store.db import Store
from tests.sse import done, events
from tests.test_render import _house

client = TestClient(app)
PNG = b"\x89PNG\r\n\x1a\n"


class Scripted(MockLLM):
    """The mock, except for look turns, which follow `looks`; every request is recorded."""

    def __init__(self, looks: list[dict], vision: bool = True):
        self.looks, self.vision, self.requests = list(looks), vision, []

    def complete(self, request, on_text=None, on_note=None):
        self.requests.append(request)
        if request.schema_name == "look":
            return self.looks.pop(0) if self.looks else {"done": True}
        return super().complete(request, on_text, on_note)


def _run(llm, prompt="a 2 bedroom house with a kitchen with a fridge", tmp_path=None):
    store = Store(tmp_path / "db.sqlite3", tmp_path / "projects")
    project = store.create_project("t")
    seen = []
    version = pipeline.run_prompt(store, llm, project.id, prompt, emit=lambda stage, msg, data=None: seen.append((stage, msg, data or {})))
    return store, project.id, version, seen


def test_the_model_sees_screenshots_and_asks_for_more(tmp_path):
    llm = Scripted([{"views": [{"target": "fridge-kitchen", "azimuth": 180, "elevation": 20}]}, {"done": True}])
    store, pid, version, seen = _run(llm, tmp_path=tmp_path)
    looks = [r for r in llm.requests if r.schema_name == "look"]
    assert [len(r.images) for r in looks] == [2, 1]
    assert all(im.png.startswith(PNG) for r in looks for im in r.images)
    assert looks[0].images[1].caption.startswith("view of everything from azimuth 180° elevation 90° (level L1)")
    assert "fridge-kitchen" in looks[1].images[0].caption and "SCREENSHOTS SO FAR" in looks[1].user
    shots = [d for s, _, d in seen if s == "look" and d.get("image")]
    assert len(shots) == 3 and all(store.shot_path(pid, d["image"].rsplit("/", 1)[1]).is_file() for d in shots)
    assert not any(s == "build" and d.get("seen") for s, _, d in seen)
    assert version.number == 1


def test_what_the_model_sees_goes_into_a_fix_round(tmp_path):
    problem = "fridge-kitchen faces the wall: move it to side S"
    llm = Scripted([{"problems": [problem], "done": True}])
    _, _, _, seen = _run(llm, tmp_path=tmp_path)
    fix = [r for r in llm.requests if r.schema_name == "build" and r.meta.get("seen")]
    assert len(fix) == 1 and SEEN_INTRO in fix[0].user and problem in fix[0].user
    assert any(s == "build" and msg.startswith("fixing what the screenshots showed") for s, msg, _ in seen)


def test_models_that_cannot_see_skip_the_look(tmp_path):
    llm = Scripted([], vision=False)
    _, _, _, seen = _run(llm, tmp_path=tmp_path)
    assert not [r for r in llm.requests if r.schema_name == "look"]
    assert any(s == "look" and d.get("skipped") for s, _, d in seen)


def test_a_view_that_cannot_be_taken_is_reported_back_to_the_model():
    logs = []

    def complete(log, shots):
        logs.append(list(log))
        return {"done": True}

    review = look(complete, shooter(_house(), {}), lambda *a: None, [View(target="toaster"), View()], turns=2)
    assert review.problems == [] and review.shots == 1
    assert "could not take it: nothing called 'toaster'" in logs[0][0]


def test_first_views_are_the_whole_model_and_each_level_plan():
    views = first_views(["L1", "L2", "L3"])
    assert len(views) == 3 and views[0].target is None and [v.level for v in views[1:]] == ["L1", "L2"]
    assert all(v.elevation == 90 for v in views[1:])


def test_adapters_send_each_image_after_its_caption():
    request = LLMRequest(system="s", user="u", schema={}, schema_name="look", images=[Image(PNG + b"x", "view one")])
    claude = claude_content(request)
    assert claude[0] == {"type": "text", "text": "u"} and claude[1]["text"] == "Image 1: view one"
    assert claude[2]["source"]["media_type"] == "image/png" and claude[2]["source"]["data"] == request.images[0].b64()
    openai = openai_content(request)
    assert openai[2]["image_url"]["url"].startswith("data:image/png;base64,")
    ollama = ollama_message(request)
    assert ollama["content"] == "u\n\nImage 1: view one" and ollama["images"] == [request.images[0].b64()]
    plain = LLMRequest(system="s", user="u", schema={}, schema_name="build")
    assert claude_content(plain) == "u" and openai_content(plain) == "u" and ollama_message(plain) == {"role": "user", "content": "u"}


def test_llm_vision_overrides_the_provider_default(monkeypatch):
    assert get_llm("mock").vision is True
    monkeypatch.setattr(config, "reload", lambda: None)
    monkeypatch.setattr(config, "LLM_VISION", False)
    assert get_llm("mock").vision is False


def test_the_api_serves_screenshots_and_renders_any_view():
    pid = client.post("/projects", json={"name": "look"}).json()["id"]
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "a 2 bedroom house with a kitchen with a fridge"})
    version = done(r.text)
    urls = [e["data"]["image"] for e in events(r.text) if e["stage"] == "look" and e["data"].get("image")]
    assert urls and client.get(urls[0]).headers["content-type"] == "image/png"
    assert client.get(f"/projects/{pid}/shots/../../db.png").status_code == 404
    base = f"/projects/{pid}/versions/{version['number']}/render"
    shot = client.get(base, params={"level": "L1", "elevation": 90, "width": 400, "height": 300})
    assert shot.status_code == 200 and png_size(shot.content) == (400, 300) and "fridge-kitchen" in shot.headers["x-visible"]
    assert client.get(base, params={"target": "fridge-kitchen", "hide": "IfcRoof,ground"}).status_code == 200
    bad = client.get(base, params={"target": "toaster"})
    assert bad.status_code == 400 and "nothing called 'toaster'" in bad.json()["detail"]
    assert client.get(base, params={"position": "1,x"}).status_code == 400


def test_look_rounds_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("BIM_LOOK_ROUNDS", "0")
    llm = Scripted([])
    _, _, _, seen = _run(llm, tmp_path=tmp_path)
    assert not [r for r in llm.requests if r.schema_name == "look"] and not any(s == "look" for s, _, _ in seen)
