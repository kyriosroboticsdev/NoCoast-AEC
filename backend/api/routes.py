"""HTTP API.

Stateful (what the UI uses):
    POST /projects                                 create a project
    GET  /projects, /projects/{id}                 list / inspect (head version + history)
    POST /projects/{id}/prompt        (SSE)        natural-language design or edit → new version
    POST /projects/{id}/ops           (SSE)        apply raw ops without an LLM → new version
    POST /projects/{id}/revert/{n}    (SSE)        undo: new version equal to version n
    POST /projects/{id}/import        (SSE)        lift a NoCoast-generated IFC file into the project
    GET  /projects/{id}/versions/{n}/{ifc|spec|context|slices|gcode}
    POST /projects/{id}/versions/{n}/construction                     start a live-build simulation job
    GET  /projects/{id}/versions/{n}/construction/{job_id}            poll it

Stateless (kept for scripts and tests): POST /plan, /build, /generate.
`/build` still accepts a legacy BuildingSpec and migrates it. `/plan` retrieves recipe cards;
it does not expand a house template.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from pathlib import Path

import ifcopenshell
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ValidationError

import config
from agents import PLANNERS, PlanResult, get_planner
from core import construction, pipeline
from core.context import describe_model
from core.migrate import from_spec
from ifc.compile import write_ifc
from ifc.lifter import LiftError, lift
from llm import PROVIDERS, get_llm
from schemas.bim import BuildingSpec
from schemas.ops import Op
from slicer.gcode import to_gcode
from slicer.slice import slice_model
from store.db import Project, Store, Version

from api.sse import sse_response

OUTPUT_DIR = config.OUTPUT_DIR
router = APIRouter()
store = Store(config.DB_PATH, OUTPUT_DIR / "projects")


class PromptRequest(BaseModel):
    prompt: str
    planner: str | None = None
    base_version: int | None = None
    focus: str | None = None


class OpsRequest(BaseModel):
    ops: list[Op]
    base_version: int | None = None


class BuildRequest(BaseModel):
    spec: BuildingSpec


class BuildResult(BaseModel):
    id: str
    ifc_url: str
    summary: dict
    seconds: float


class GenerateResult(BuildResult):
    plan: PlanResult


class ProjectCreate(BaseModel):
    name: str = "Untitled"


def _project(project_id: str) -> Project:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, f"project '{project_id}' not found")
    return project


def _with_url(v: Version) -> dict:
    return v.model_dump() | {"ifc_url": v.ifc_url}


@router.get("/health")
def health() -> dict:
    config.reload()
    return {"ok": True, "planners": list(PLANNERS), "llm": {"provider": config.LLM_PROVIDER, "model": config.LLM_MODEL or None,
                                                             "providers": list(PROVIDERS)}}


@router.post("/projects")
def create_project(req: ProjectCreate) -> Project:
    return store.create_project(req.name)


@router.get("/projects")
def list_projects() -> list[Project]:
    return store.list_projects()


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    project = _project(project_id)
    head = store.head(project_id)
    return {"project": project.model_dump(), "head": _with_url(head.as_version()) if head else None,
            "versions": [_with_url(v) for v in store.list_versions(project_id)]}


@router.post("/projects/{project_id}/prompt")
def prompt_project(project_id: str, req: PromptRequest):
    _project(project_id)
    llm = get_llm(req.planner) if req.planner in PROVIDERS else get_llm()
    return sse_response(lambda emit: pipeline.run_prompt(store, llm, project_id, req.prompt, req.base_version, emit, req.focus))


@router.post("/projects/{project_id}/ops")
def ops_project(project_id: str, req: OpsRequest):
    _project(project_id)
    return sse_response(lambda emit: pipeline.run_ops(store, project_id, req.ops, req.base_version, emit))


@router.post("/projects/{project_id}/revert/{number}")
def revert_project(project_id: str, number: int):
    _project(project_id)
    return sse_response(lambda emit: pipeline.revert(store, project_id, number, emit))


@router.post("/projects/{project_id}/import")
async def import_ifc(project_id: str, file: UploadFile):
    _project(project_id)
    tmp = Path(tempfile.mkdtemp()) / (file.filename or "upload.ifc")
    with tmp.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    try:
        geo, guids = lift(tmp)
    except (LiftError, ValueError, ValidationError) as exc:
        raise HTTPException(422, f"cannot lift IFC: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - IfcOpenShell raises its own error types on unparseable files
        raise HTTPException(422, f"cannot read IFC: {exc}") from exc
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    notes = [f"imported {file.filename}: {len(geo.parts)} parts, {len(geo.levels)} levels"]
    return sse_response(lambda emit: pipeline.import_model(store, project_id, geo, guids, notes, emit))


def _version(project_id: str, number: int):
    _project(project_id)
    v = store.get_version(project_id, number)
    if v is None:
        raise HTTPException(404, f"version {number} not found")
    return v


@router.get("/projects/{project_id}/versions/{number}/ifc")
def version_ifc(project_id: str, number: int):
    v = _version(project_id, number)
    return FileResponse(v.ifc_path, media_type="application/x-step", filename=f"{project_id}-v{number}.ifc")


@router.get("/projects/{project_id}/versions/{number}/spec")
def version_spec(project_id: str, number: int) -> dict:
    """`design` is always null: the room record is gone. The model is under `model`.

    `spec` is null too, so the existing spec viewer stringifies nothing and the design-facts
    inspector (which only runs when `design` is an object) does not throw.
    """
    v = _version(project_id, number)
    return {"version": _with_url(v.as_version()), "spec": None, "design": None,
            "model": v.geo.model_dump(mode="json"), "guids": v.guids}


@router.get("/projects/{project_id}/versions/{number}/context", response_class=PlainTextResponse)
def version_context(project_id: str, number: int) -> str:
    v = _version(project_id, number)
    return describe_model(v.geo)


@router.get("/projects/{project_id}/versions/{number}/slices")
def version_slices(project_id: str, number: int, layer_height: float = 0.2) -> dict:
    v = _version(project_id, number)
    model = ifcopenshell.open(v.ifc_path)
    layers = slice_model(model, layer_height)
    return {"layer_height": layer_height, "layers": [{"phase": l.phase, "z": l.z, "segments": l.segments} for l in layers]}


@router.get("/projects/{project_id}/versions/{number}/gcode", response_class=PlainTextResponse)
def version_gcode(project_id: str, number: int, layer_height: float = 0.2) -> str:
    v = _version(project_id, number)
    model = ifcopenshell.open(v.ifc_path)
    return to_gcode(slice_model(model, layer_height))


@router.post("/projects/{project_id}/versions/{number}/construction")
def start_construction(project_id: str, number: int) -> dict:
    job = construction.start(_version(project_id, number))
    return job.status()


@router.get("/projects/{project_id}/versions/{number}/construction/{job_id}")
def construction_status(project_id: str, number: int, job_id: str) -> dict:
    _version(project_id, number)
    job = construction.get(job_id)
    if job is None:
        raise HTTPException(404, f"construction job '{job_id}' not found")
    return job.status()


def _plan(req: PromptRequest) -> PlanResult:
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    try:
        return get_planner(req.planner).plan(req.prompt)
    except (ValueError, pipeline.PipelineError) as exc:
        raise HTTPException(422, f"planning failed: {exc}") from exc


def _build(spec: BuildingSpec) -> BuildResult:
    t0 = time.perf_counter()
    model_id = uuid.uuid4().hex[:12]
    try:
        summary = write_ifc(from_spec(spec), OUTPUT_DIR / f"{model_id}.ifc")
    except ValueError as exc:
        raise HTTPException(422, f"IFC build failed: {exc}") from exc
    return BuildResult(id=model_id, ifc_url=f"/models/{model_id}.ifc", summary=summary,
                       seconds=round(time.perf_counter() - t0, 3))


@router.post("/plan")
def plan(req: PromptRequest) -> PlanResult:
    return _plan(req)


@router.post("/build")
def build(req: BuildRequest) -> BuildResult:
    return _build(req.spec)


@router.post("/generate")
def generate(req: PromptRequest) -> GenerateResult:
    planned = _plan(req)
    t0 = time.perf_counter()
    model_id = uuid.uuid4().hex[:12]
    try:
        summary = write_ifc(planned.model, OUTPUT_DIR / f"{model_id}.ifc")
    except ValueError as exc:
        raise HTTPException(422, f"IFC build failed: {exc}") from exc
    return GenerateResult(plan=planned, id=model_id, ifc_url=f"/models/{model_id}.ifc", summary=summary,
                          seconds=round(time.perf_counter() - t0, 3))
