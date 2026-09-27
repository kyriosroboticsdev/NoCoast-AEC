import time

import ifcopenshell

from core.construction import ConstructionJob, build_order
from core.guids import ensure_guids
from ifc.compile import compile_ifc
from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, apply_step
from store.db import VersionData


def _geo() -> GeoModel:
    geo = GeoModel()
    for raw in (
        {"step": "part", "id": "slab", "name": "floor", "ifc": "IfcSlab", "ifc_type": "FLOOR",
         "solid": {"box": [6, 4, 0.2]}},
        {"step": "part", "id": "wall", "name": "wall", "ifc": "IfcWall", "ifc_type": "SOLIDWALL",
         "solid": {"wall": [[0, 0], [6, 0]], "thickness": 0.2, "height": 3}},
        {"step": "part", "id": "roof", "name": "roof", "ifc": "IfcRoof", "ifc_type": "FLAT_ROOF", "at": [0, 0, 3],
         "solid": {"box": [6, 4, 0.2]}},
        {"step": "part", "id": "door", "name": "door", "ifc": "IfcDoor", "ifc_type": "DOOR",
         "solid": {"box": [0.9, 0.05, 2.1]}},
    ):
        geo, _ = apply_step(geo, GeoStep.model_validate(raw))
    return geo


def _version(geo, guids) -> VersionData:
    return VersionData(
        project_id="p", number=1, parent=None, prompt=None, mode="design", llm=None, notes=[],
        summary={}, ops=[], ifc_path="", created=0.0, geo=geo, guids=guids,
    )


def test_build_order_is_phase_grouped():
    order = build_order(_geo())
    phases = [p.ifc for p in order]
    assert phases.index("IfcSlab") < phases.index("IfcWall") < phases.index("IfcRoof") < phases.index("IfcDoor")


def test_construction_job_writes_one_valid_ifc_per_part():
    geo = _geo()
    guids = ensure_guids(geo, {})
    compile_ifc(geo, guids)
    job = ConstructionJob(_version(geo, guids), step_seconds=0.0)
    deadline = time.perf_counter() + 30
    while not job.done and time.perf_counter() < deadline:
        time.sleep(0.05)
    assert job.done and job.error is None, job.error
    assert job.index == len(geo.parts) == len(job.urls)
    last = ifcopenshell.open(str(job._dir / f"step-{job.index - 1:04d}.ifc"))
    assert len(last.by_type("IfcWall")) == 1 and len(last.by_type("IfcDoor")) == 1
