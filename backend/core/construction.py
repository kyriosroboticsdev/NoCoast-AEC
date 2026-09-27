"""A version's parts, written to disk one construction step at a time.

Ordered by construction phase and then by level elevation, so watching it progress looks
like a build. Each step is a real IFC file compiled with the version's own GuidMap.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import config
from ifc.compile import compile_ifc
from schemas.geo import GeoModel, GeoPart
from store.db import VersionData

CONSTRUCTION_DIR = config.OUTPUT_DIR / "construction"
JOB_TTL = 1800
STEP_SECONDS = 0.2

# IFC entity → phase index. Anything unlisted is structure: it is a solid that has to go up.
PHASE = {
    "IfcFooting": 0, "IfcPile": 0, "IfcSlab": 0,
    "IfcWall": 1, "IfcColumn": 1, "IfcBeam": 1, "IfcMember": 1, "IfcStair": 1, "IfcStairFlight": 1,
    "IfcRamp": 1, "IfcRampFlight": 1, "IfcCurtainWall": 1, "IfcPlate": 1, "IfcCivilElement": 1,
    "IfcRoof": 2, "IfcCovering": 2,
    "IfcSpace": 4,
    "IfcDoor": 6, "IfcWindow": 6, "IfcRailing": 6, "IfcFurniture": 6, "IfcSanitaryTerminal": 6,
    "IfcBuildingElementProxy": 6,
}


def _phase(part: GeoPart) -> int:
    return PHASE.get(part.ifc, 1)


def build_order(geo: GeoModel) -> list[GeoPart]:
    elevations = geo.elevations()
    return sorted(geo.parts, key=lambda p: (_phase(p), elevations.get(p.level, 0.0), p.id))


def _subset(geo: GeoModel, ids: set[str]) -> GeoModel:
    parts = [p for p in geo.parts if p.id in ids]
    openings = [o for o in geo.openings if o.host in ids and (o.fill is None or o.fill in ids)]
    assemblies = []
    for asm in geo.assemblies:
        kept = [p for p in asm.parts if p in ids]
        if kept:
            assemblies.append(asm.model_copy(update={"parts": kept}))
    live = {a.id for a in assemblies}
    instances = [i for i in geo.instances if i.of in live]
    return geo.model_copy(update={"parts": parts, "openings": openings, "assemblies": assemblies, "instances": instances})


class ConstructionJob:
    def __init__(self, version: VersionData, step_seconds: float = STEP_SECONDS):
        self.id = uuid.uuid4().hex[:12]
        self.created = time.time()
        self.total = len(version.geo.parts)
        self.index = 0
        self.urls: list[str] = []
        self.done = False
        self.error: str | None = None
        self._dir = CONSTRUCTION_DIR / self.id
        self._dir.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._run, args=(version, step_seconds), daemon=True, name=f"construction-{self.id}").start()

    def _run(self, version: VersionData, step_seconds: float) -> None:
        try:
            order = build_order(version.geo)
            built: list[str] = []
            for i, part in enumerate(order):
                built.append(part.id)
                model, _ = compile_ifc(_subset(version.geo, set(built)), dict(version.guids))
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
