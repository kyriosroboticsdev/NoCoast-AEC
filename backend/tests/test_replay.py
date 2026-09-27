"""Recorded runs play back as the same event stream, previews included, without calling the model."""

from fastapi.testclient import TestClient

from api.routes import store
from core import replay
from main import app
from store.db import Store
from tests.sse import done, events

client = TestClient(app)
PROMPT = "Single storey house with a kitchen, living room and two bedrooms"


def test_a_prompt_run_is_recorded_and_replays_the_same_trace():
    pid = client.post("/projects", json={"name": "replay"}).json()["id"]
    live = client.post(f"/projects/{pid}/prompt", json={"prompt": PROMPT}).text
    version = done(live)

    runs = [r for r in client.get("/runs").json() if r["project"] == pid]
    assert len(runs) == 1 and runs[0]["prompt"] == PROMPT and runs[0]["version"] == version["number"]

    replayed = client.get(f"/projects/{pid}/versions/{version['number']}/replay", params={"speed": 1000}).text
    original, again = events(live), events(replayed)
    assert [e["stage"] for e in again] == [e["stage"] for e in original]
    assert done(replayed)["number"] == version["number"]
    assert all(e["data"] is None or "text" not in e["data"] for e in again if e["stage"] == "stream")

    previews = [e["data"]["ifc_url"] for e in again if e["stage"] == "partial"]
    assert previews and all(u.startswith(f"/models/projects/{pid}/previews/") for u in previews)
    assert client.get(previews[0]).status_code == 200


def test_a_packed_run_restores_on_a_fresh_machine(tmp_path):
    pid = client.post("/projects", json={"name": "pack"}).json()["id"]
    version = done(client.post(f"/projects/{pid}/prompt", json={"prompt": PROMPT}).text)
    data = replay.pack(store, pid)

    fresh = Store(tmp_path / "fresh.sqlite3", tmp_path / "projects")
    assert replay.unpack(fresh, data) == pid
    assert replay.unpack(fresh, data) is None
    restored = fresh.get_version(pid, 1)
    assert restored.summary == version["summary"] and restored.prompt == PROMPT
    assert fresh.ifc_path(pid, 1).read_bytes() == store.ifc_path(pid, 1).read_bytes()
    run = replay.load(fresh, pid, 1)
    previews = [e["data"]["ifc_url"] for e in run["events"] if e["stage"] == "partial"]
    assert 0 < len(previews) <= replay.PACK_PREVIEWS + 1
    assert all((fresh.ifc_dir / pid / "previews" / u.rsplit("/", 1)[1]).is_file() for u in previews)


def test_replay_of_an_unrecorded_version_is_404():
    pid = client.post("/projects", json={"name": "none"}).json()["id"]
    assert client.get(f"/projects/{pid}/versions/1/replay").status_code == 404
