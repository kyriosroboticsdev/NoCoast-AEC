"""Recorded runs: every prompt's event stream is kept next to the version it produced, and can be played
back later at any speed — the same trace, previews and screenshots, without calling the model again.

A recording is `projects/<id>/v<n>.run.json`: the prompt, the model, and the events as they were sent.
The reply text carried by `stream` events is dropped (the UI shows only their message), and the preview
IFCs, which are pruned from `partial/` after a while, are copied beside the recording so a replay next
week still shows the building growing.
"""
from __future__ import annotations

import io
import json
import math
import shutil
import time
import zipfile
from pathlib import Path
from typing import Iterator

import config
from logsetup import log
from store.db import Store, VersionData

PARTIAL = "/models/partial/"
MAX_GAP = 1.5  # seconds: the longest pause a replay holds, however long the model thought
PACK_PREVIEWS = 12  # previews a packed run keeps, evenly spaced, so the zip stays a few MB


def path(store: Store, project_id: str, number: int) -> Path:
    return store.ifc_dir / project_id / f"v{number}.run.json"


def _slim(event: dict) -> dict:
    if event["stage"] == "stream":
        data = event.get("data") or {}
        return {**event, "data": {"waiting": True} if data.get("waiting") else None}
    return event


def _keep_previews(store: Store, project_id: str, events: list[dict]) -> None:
    folder = store.ifc_dir / project_id / "previews"
    for e in events:
        url = (e.get("data") or {}).get("ifc_url") if e["stage"] == "partial" else None
        if not isinstance(url, str) or not url.startswith(PARTIAL):
            continue
        name = url[len(PARTIAL):]
        src = config.OUTPUT_DIR / "partial" / name
        if not src.is_file():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, folder / name)
        e["data"] = {**e["data"], "ifc_url": f"/models/projects/{project_id}/previews/{name}"}


def record(store: Store, project_id: str, prompt: str, llm: str, events: list[dict]) -> Path | None:
    """Keep a finished run; runs that ended in an error are not worth replaying."""
    done = next((e for e in reversed(events) if e["stage"] == "done"), None)
    if done is None or not isinstance(done.get("data"), dict):
        return None
    number = done["data"].get("number")
    if not isinstance(number, int):
        return None
    slim = [_slim(e) for e in events]
    try:
        _keep_previews(store, project_id, slim)
        out = path(store, project_id, number)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"prompt": prompt, "llm": llm, "recorded": time.time(),
                                   "duration": slim[-1].get("t", 0.0), "events": slim}))
        return out
    except OSError as exc:
        log.warning("could not record run %s v%s: %s", project_id, number, exc)
        return None


def load(store: Store, project_id: str, number: int) -> dict | None:
    p = path(store, project_id, number)
    if not p.is_file():
        return None
    return json.loads(p.read_text())


def summary(run: dict) -> dict:
    return {"prompt": run["prompt"], "llm": run["llm"], "recorded": run["recorded"], "duration": run["duration"],
            "events": len(run["events"])}


def pack(store: Store, project_id: str, number: int = 1) -> bytes:
    """A recorded design run as one zip — recording, version, final IFC, a thinned set of previews and the
    screenshots the model was shown — that `unpack` restores on another machine under the same project id."""
    run, version = load(store, project_id, number), store.get_version(project_id, number)
    if run is None or version is None:
        raise LookupError(f"version {number} of '{project_id}' has no recorded run")
    if number != 1:
        raise ValueError("only a project's first version can be packed: its replay must land on version 1")
    partials = [i for i, e in enumerate(run["events"]) if e["stage"] == "partial"]
    keep = set(partials[::max(1, math.ceil(len(partials) / PACK_PREVIEWS))] + partials[-1:])
    events = [e for i, e in enumerate(run["events"]) if e["stage"] != "partial" or i in keep]
    folder = store.ifc_dir / project_id
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("run.json", json.dumps({**run, "events": events}))
        z.writestr("version.json", version.model_dump_json(exclude={"ifc_path"}))
        z.write(store.ifc_path(project_id, number), "model.ifc")
        for e in events:
            url = (e.get("data") or {}).get("ifc_url", "") if e["stage"] == "partial" else ""
            src = folder / "previews" / Path(url).name
            if url and src.is_file():
                z.write(src, f"previews/{src.name}")
        for shot in sorted((folder / "shots").glob("*.png")):
            z.write(shot, f"shots/{shot.name}")
    return buf.getvalue()


def unpack(store: Store, data: bytes) -> str | None:
    """Restore a packed run; returns its project id, or None when that project is already here."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        run = json.loads(z.read("run.json"))
        version = VersionData.model_validate({**json.loads(z.read("version.json")), "ifc_path": ""})
        pid = version.project_id
        if store.get_project(pid) is not None:
            return None
        folder = store.ifc_dir / pid
        for name in z.namelist():
            kind, _, file = name.partition("/")
            if kind in ("previews", "shots") and file and Path(file).name == file:
                (folder / kind).mkdir(parents=True, exist_ok=True)
                (folder / kind / file).write_bytes(z.read(name))
        ifc = store.ifc_path(pid, 1)
        ifc.parent.mkdir(parents=True, exist_ok=True)
        ifc.write_bytes(z.read("model.ifc"))
    store.create_project(run["prompt"][:48], project_id=pid, created=run["recorded"])
    store.add_version(pid, spec=version.spec, guids=version.guids, mode=version.mode, summary=version.summary,
                      ifc_path=ifc, prompt=version.prompt, llm=version.llm, ops=version.ops, notes=version.notes,
                      design=version.design, checks=version.checks, images=version.images, approach=version.approach)
    path(store, pid, 1).write_text(json.dumps(run))
    return pid


def seed(store: Store, folder: Path) -> list[str]:
    """Restore every packed run in `folder` that this machine does not have yet (the shipped demo runs)."""
    restored = []
    for f in sorted(folder.glob("*.zip")):
        try:
            pid = unpack(store, f.read_bytes())
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            log.warning("could not restore the recorded run %s: %s", f.name, exc)
            continue
        if pid:
            restored.append(pid)
            log.info("restored the recorded run %s as project %s", f.name, pid)
    return restored


def pace(events: list[dict], speed: float) -> Iterator[tuple[float, dict]]:
    """Each event with the pause before it: the recorded gap divided by `speed`, never more than MAX_GAP."""
    last = 0.0
    for e in events:
        t = float(e.get("t") or last)
        yield min(max(0.0, t - last) / max(speed, 0.1), MAX_GAP), e
        last = t
