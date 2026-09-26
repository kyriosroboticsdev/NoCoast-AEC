"""Parse an SSE body as returned by the TestClient into a list of event dicts."""

import json


def events(text: str) -> list[dict]:
    out = []
    for chunk in text.strip().split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def done(text: str) -> dict:
    evs = events(text)
    last = evs[-1]
    assert last["stage"] == "done", evs
    return last["data"]
