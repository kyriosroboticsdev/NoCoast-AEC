"""A version's elements, written to disk one construction step at a time — a live build, not a
snapshot. Ordered the same way `ifc/builder.py::BUILDERS` compiles (foundation, structure, roof,
spaces, fixtures last), bottom to top within each phase, so watching it progress looks like a real
build sequence. Each step is a real, valid IFC file compiled with the version's own GuidMap, so a
GlobalId a viewer already resolved keeps meaning the same element as more of the building appears.

Distinct from `slicer/slice.py` (a client-side clip-plane sweep over the *finished* model, cut
purely by height): this runs as a background job and writes one full file per step at a deliberate
pace, so a client polling for "whatever's been built so far" every ~300ms has something to catch.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import config
from ifc.builder import compile_ifc
from schemas.bim import (Beam, BuildingSpec, Column, Component, CustomFixture, Door, Element, Fixture, LightFixture, Outlet,
                          Panel, Pipe, Railing, Roof, Slab, Space, Stair, Wall, Window, Wire)
from store.db import VersionData

CONSTRUCTION_DIR = config.OUTPUT_DIR / "construction"  # served by the /models static mount
JOB_TTL = 1800           # seconds before a finished job's files and status are dropped
STEP_SECONDS = 0.2       # backend pace between steps; independent of how often a client polls

# Construction phases, in build order — mirrors ifc/builder.py's BUILDERS.
PHASES: list[tuple[str, tuple[type, ...]]] = [
    ("foundation", (Slab,)),
    ("structure", (Wall, Column, Beam, Stair)),
    ("roof", (Roof,)),
    ("plumbing", (Pipe,)),
    ("spaces", (Space,)),
    ("electrical", (Outlet, Panel, Wire)),
    ("details", (Door, Window, Railing, Fixture, CustomFixture, Component, LightFixture)),
]


def _elevation(spec: BuildingSpec, el: Element) -> float:
    """Sort key: an element's own level, its host wall's for a door/window, or a riser's bottom for a pipe."""
    if isinstance(el, Pipe):
        level_id = el.bottom_level
    elif hasattr(el, "level"):
        level_id = el.level
    else:
        level_id = next(w.level for w in spec.elements if isinstance(w, Wall) and w.id == el.wall)
    return next(l.elevation for l in spec.levels if l.id == level_id)


def build_order(spec: BuildingSpec) -> list[Element]:
    """Elements in the order they'd really go up: by construction phase, bottom to top within it."""
    ordered: list[Element] = []
    for _, kinds in PHASES:
        step = [el for el in spec.elements if isinstance(el, kinds)]
        step.sort(key=lambda el: _elevation(spec, el))
        ordered += step
    return ordered


class ConstructionJob:
    def __init__(self, version: VersionData, step_seconds: float = STEP_SECONDS):
        self.id = uuid.uuid4().hex[:12]
        self.created = time.time()
        self.total = len(version.spec.elements)
        self.index = 0
        self.urls: list[str] = []
        self.done = False
        self.error: str | None = None
        self._dir = CONSTRUCTION_DIR / self.id
        self._dir.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._run, args=(version, step_seconds), daemon=True, name=f"construction-{self.id}").start()

    def _run(self, version: VersionData, step_seconds: float) -> None:
        try:
            order = build_order(version.spec)
            built: list[Element] = []
            for i, el in enumerate(order):
                built.append(el)
                sub_spec = version.spec.model_copy(update={"elements": list(built)})
                model, _ = compile_ifc(sub_spec, dict(version.guids), version.design.model_dump_json() if version.design else None)
                name = f"step-{i:04d}.ifc"
                model.write(str(self._dir / name))
                self.urls.append(f"/models/construction/{self.id}/{name}")
                self.index = i + 1
                time.sleep(step_seconds)
        except Exception as exc:  # noqa: BLE001 - reported to the poller, not fatal to the server
            self.error = str(exc)
        finally:
            self.done = True

    def status(self) -> dict:
        return {"job_id": self.id, "done": self.done, "error": self.error, "index": self.index,
                "total": self.total, "ifc_url": self.urls[-1] if self.urls else None}


_JOBS: dict[str, ConstructionJob] = {}
_LOCK = threading.Lock()


def start(version: VersionData) -> ConstructionJob:
    prune()
    job = ConstructionJob(version)
    with _LOCK:
        _JOBS[job.id] = job
    return job


def get(job_id: str) -> ConstructionJob | None:
    with _LOCK:
        return _JOBS.get(job_id)


def prune() -> None:
    """Drop finished jobs (and their files) older than JOB_TTL, same idea as preview.py's partials."""
    cutoff = time.time() - JOB_TTL
    with _LOCK:
        stale = [jid for jid, job in _JOBS.items() if job.done and job.created < cutoff]
        for jid in stale:
            del _JOBS[jid]
    for jid in stale:
        _rmtree(CONSTRUCTION_DIR / jid)


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    for f in path.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass
