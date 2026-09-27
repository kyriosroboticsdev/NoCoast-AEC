"""Token counts: what each adapter reports, what the pipeline adds up, and what a version keeps."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from core import pipeline
from core.usage import Tally, usage_of
from llm import claude, ollama, openai_compat
from llm.base import LLMRequest, Usage, estimate_tokens
from llm.mock import MockLLM
from main import app
from store.db import Store
from tests.sse import done, events

client = TestClient(app)


def request(system="s" * 400, user="u" * 800) -> LLMRequest:
    return LLMRequest(system=system, user=user, schema={"type": "object"}, schema_name="build")


# --- counting ---------------------------------------------------------------------------------

def test_usage_adds_up_and_remembers_an_estimate():
    total = Usage(100, 20, 40) + Usage(10, 5, estimated=True)
    assert total == Usage(110, 25, 40, True)
    assert total.as_dict() == {"input_tokens": 110, "output_tokens": 25, "cached_tokens": 40, "total_tokens": 135, "estimated": True}
    assert Usage.from_dict(total.as_dict()) == total


def test_a_call_without_provider_counts_is_estimated_from_the_text():
    used = usage_of(request(), "r" * 40)
    assert used == Usage(input_tokens=300, output_tokens=10, estimated=True)
    assert estimate_tokens("") == 0 and estimate_tokens("abcde") == 2


def test_provider_counts_win_over_the_estimate():
    r = request()
    r.usage = Usage(1234, 56, 1000)
    assert usage_of(r, "anything") == Usage(1234, 56, 1000)


def test_tally_totals_the_llm_events_and_leaves_the_rest_alone():
    seen = []
    tally = Tally(lambda stage, message, data: seen.append((stage, data)), "claude", "claude-opus-5")
    assert tally.total() is None
    tally("llm", "consulting", {"provider": "claude"})                     # the start of a call: no counts yet
    tally("llm", "finished", {"usage": Usage(100, 10).as_dict()})
    tally("step", "a wall", {"ok": True})
    tally("llm", "finished", {"usage": Usage(200, 30, 150).as_dict()})
    tally("llm", "a note", None)
    assert tally.total() == {"input_tokens": 300, "output_tokens": 40, "cached_tokens": 150, "total_tokens": 340,
                             "estimated": False, "calls": 2, "provider": "claude", "model": "claude-opus-5"}
    assert "usage_total" not in seen[0][1] and seen[2][1] == {"ok": True} and seen[4][1] is None
    assert seen[1][1]["usage_total"]["total_tokens"] == 110 and seen[3][1]["usage_total"]["total_tokens"] == 340


# --- adapters ---------------------------------------------------------------------------------

def test_claude_counts_cache_reads_and_writes_as_input():
    response = SimpleNamespace(usage=SimpleNamespace(input_tokens=120, output_tokens=800, cache_creation_input_tokens=3000,
                                                     cache_read_input_tokens=9000))
    assert claude.usage_of(response) == Usage(input_tokens=12120, output_tokens=800, cached_tokens=9000)
    bare = SimpleNamespace(usage=SimpleNamespace(input_tokens=50, output_tokens=7, cache_creation_input_tokens=None,
                                                 cache_read_input_tokens=None))
    assert claude.usage_of(bare) == Usage(50, 7, 0)


class FakeStream:
    def __init__(self, status: int, lines: list[str], text: str = ""):
        self.status_code, self.lines, self.text = status, lines, text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.text

    def iter_lines(self):
        return iter(self.lines)


def sse_lines(*chunks: dict) -> list[str]:
    return [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]


def test_openai_compatible_stream_reports_its_usage_chunk(monkeypatch):
    bodies = []

    def fake(method, url, json=None, **kw):
        bodies.append(json)
        return FakeStream(200, sse_lines({"choices": [{"delta": {"content": '{"steps": '}}]},
                                         {"choices": [{"delta": {"content": "[]}"}}]},
                                         {"choices": [], "usage": {"prompt_tokens": 4321, "completion_tokens": 12,
                                                                   "prompt_tokens_details": {"cached_tokens": 4000}}}))

    monkeypatch.setattr(httpx, "stream", fake)
    llm = openai_compat.OpenAICompatibleLLM(model="m", base_url="http://x/v1")
    r = request()
    assert llm.complete(r) == {"steps": []}
    assert bodies[0]["stream_options"] == {"include_usage": True}
    assert r.usage == Usage(input_tokens=4321, output_tokens=12, cached_tokens=4000)


def test_a_server_that_refuses_the_option_is_asked_again_without_it(monkeypatch):
    bodies = []

    def fake(method, url, json=None, **kw):
        bodies.append(json)
        if "stream_options" in json:
            return FakeStream(400, [], text='{"error": "unknown field stream_options"}')
        return FakeStream(200, sse_lines({"choices": [{"delta": {"content": '{"steps": []}'}}]}))

    monkeypatch.setattr(httpx, "stream", fake)
    llm = openai_compat.OpenAICompatibleLLM(model="m", base_url="http://x/v1")
    r = request()
    assert llm.complete(r) == {"steps": []}
    assert len(bodies) == 2 and "stream_options" not in bodies[1]
    assert r.usage is None and usage_of(r, '{"steps": []}').estimated
    llm.complete(request())
    assert len(bodies) == 3 and "stream_options" not in bodies[2]      # remembered for the rest of the process


def test_another_error_is_still_an_error(monkeypatch):
    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: FakeStream(401, [], text="bad key"))
    with pytest.raises(openai_compat.LLMError, match="401"):
        openai_compat.OpenAICompatibleLLM(model="m", base_url="http://x/v1").complete(request())


def test_ollama_reports_its_eval_counts(monkeypatch):
    lines = [json.dumps({"message": {"content": '{"steps": []}'}}),
             json.dumps({"done": True, "prompt_eval_count": 900, "eval_count": 15})]
    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: FakeStream(200, lines))
    r = request()
    assert ollama.OllamaLLM(model="m").complete(r) == {"steps": []}
    assert r.usage == Usage(input_tokens=900, output_tokens=15)


# --- the pipeline and the version -------------------------------------------------------------

def test_a_run_counts_every_call_and_the_version_keeps_the_total():
    pid = client.post("/projects", json={"name": "usage"}).json()["id"]
    evs = events(client.post(f"/projects/{pid}/prompt", json={"prompt": "a small house with 2 bedrooms"}).text)
    calls = [e["data"]["usage"] for e in evs if e["stage"] == "llm" and e["data"] and "usage" in e["data"]]
    totals = [e["data"]["usage_total"] for e in evs if e["stage"] == "llm" and e["data"] and "usage_total" in e["data"]]
    assert len(calls) >= 3                                        # the brief, the research and the build at least
    assert all(c["estimated"] and c["input_tokens"] > 0 for c in calls)      # the mock reports no counts
    assert [t["calls"] for t in totals] == list(range(1, len(calls) + 1))
    assert totals[-1]["input_tokens"] == sum(c["input_tokens"] for c in calls)
    assert totals[-1]["output_tokens"] == sum(c["output_tokens"] for c in calls)

    version = evs[-1]["data"]
    assert evs[-1]["stage"] == "done" and version["usage"] == totals[-1]
    assert version["usage"]["provider"] == "mock" and version["usage"]["total_tokens"] > 1000
    stored = client.get(f"/projects/{pid}").json()
    assert stored["head"]["usage"] == version["usage"] and stored["versions"][0]["usage"] == version["usage"]
    summary = client.get(f"/projects/{pid}/versions/1/export", params={"format": "summary"}).text
    assert f"- Tokens: about {version['usage']['input_tokens']:,} read" in summary


def test_versions_made_without_a_model_have_no_usage():
    pid = client.post("/projects", json={"name": "usage"}).json()["id"]
    done(client.post(f"/projects/{pid}/prompt", json={"prompt": "a small house with 2 bedrooms"}).text)
    reverted = done(client.post(f"/projects/{pid}/revert/1").text)
    assert reverted["usage"] is None


class Counting(MockLLM):
    """A model whose provider reports counts."""

    def complete(self, request, on_text=None, on_note=None):
        request.usage = Usage(input_tokens=1000, output_tokens=100, cached_tokens=600)
        return super().complete(request, on_text, on_note)


def test_provider_counts_reach_the_version(tmp_path):
    store = Store(tmp_path / "db.sqlite3", tmp_path / "projects")
    project = store.create_project("counted")
    seen = []
    version = pipeline.run_prompt(store, Counting(), project.id, "a small house with 2 bedrooms",
                                  emit=lambda stage, message, data=None: seen.append((stage, data)))
    calls = sum(1 for stage, data in seen if stage == "llm" and data and "usage" in data)
    assert version.usage == {"input_tokens": 1000 * calls, "output_tokens": 100 * calls, "cached_tokens": 600 * calls,
                             "total_tokens": 1100 * calls, "estimated": False, "calls": calls, "provider": "mock", "model": None}
    assert store.get_version(project.id, 1).usage == version.usage


def test_an_older_database_gains_the_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite3"
    Store(path, tmp_path / "projects")
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE versions DROP COLUMN usage")
    conn.commit()
    conn.close()
    Store(path, tmp_path / "projects")
    assert "usage" in [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(versions)")]
