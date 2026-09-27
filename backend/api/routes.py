"""HTTP API.

Stateful (what the UI uses):
    POST /projects                                 create a project
    GET  /projects, /projects/{id}                 list / inspect (head version + history)
    POST /projects/{id}/prompt        (SSE)        natural-language design or edit → new version
    POST /projects/{id}/ops           (SSE)        apply raw ops without an LLM → new version
    POST /projects/{id}/revert/{n}    (SSE)        undo: new version equal to version n
    POST /projects/{id}/import        (SSE)        lift a NoCoast-generated IFC file into the project
    GET  /projects/{id}/versions/{n}/{ifc|spec|context|slices|gcode}
    GET  /projects/{id}/versions/{n}/render?azimuth=&elevation=&target=&level=…   a screenshot (PNG) from any view
    GET  /projects/{id}/versions/{n}/export?format=  zip bundle (default) or one artefact; format=validation checks
                                                     the IFC, format=stamped writes author=, organization=,
                                                     project_name= and the prompt history into a copy of it
    GET  /projects/{id}/export                       the head version as a bundle
    GET  /projects/{id}/shots/{name}                                 a screenshot the model was shown while checking its work
    GET  /projects/{id}/attachments/{file}                           an image the user attached to one of its prompts
    POST /projects/{id}/versions/{n}/construction                     start a live-build simulation job
    GET  /projects/{id}/versions/{n}/construction/{job_id}            poll it

Library (read-only; the same tools the model calls while researching):
    GET  /bricks?q=&tag=&limit=          search the brick library (no q: list, optionally one tag)
    GET  /bricks/{id}                    one brick: its full definition and the card the model reads
    GET  /skills, /skills/{name}         playbooks on writing and assembling assets

Stateless (kept for scripts and tests): POST /plan, /build, /generate.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import ifcopenshell
from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, ValidationError

import config
from agents import PLANNERS, PlanResult, get_planner
from bricks import library
from core import construction, export, pipeline
from core.stamp import ExportMeta
from core.context import describe_design, describe_spec
from core.derive import DesignError, analyze, space_id
from ifc.builder import write_ifc
from ifc.lifter import LiftError, lift
from llm import PROVIDERS, get_llm
from render import ViewError, render, scene_of
from schemas.attachments import MAX_IMAGES, STORED_NAME, ImageAttachment, media_type_for
from schemas.bim import BuildingSpec
from schemas.look import View
from schemas.ops import Op
from slicer.gcode import to_gcode
from skills import skillbook
from slicer.slice import slice_model
from store.db import Project, Store, Version

from api.sse import sse_response

OUTPUT_DIR = config.OUTPUT_DIR
SHOT_NAME = re.compile(r"^[0-9a-f]{12}\.png$")
MAX_RENDER = 2048
router = APIRouter()
store = Store(config.DB_PATH, OUTPUT_DIR / "projects")


# --- request/response models -----------------------------------------------

class PromptRequest(BaseModel):
    prompt: str
    planner: str | None = None
    base_version: int | None = None
    focus: str | None = None  # spec element id selected in the viewer (e.g. "L1-wall-hall-W"); described to the model
    # Images attached to this prompt (a sketched plan, a photo): base64 or a data: URL, validated in schemas/attachments.py.
    images: list[ImageAttachment] = Field(default_factory=list, max_length=MAX_IMAGES)


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


class ProjectDetail(BaseModel):
    project: Project
    head: Version | None
    versions: list[Version]


# --- helpers -----------------------------------------------------------------

def _project(project_id: str) -> Project:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, f"project '{project_id}' not found")
    return project


def _with_url(v: Version) -> dict:
    return v.model_dump() | {"ifc_url": v.ifc_url, "export_url": v.export_url}


# --- stateful ---------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    config.reload()
    return {"ok": True, "planners": list(PLANNERS), "llm": {"provider": config.LLM_PROVIDER, "model": config.LLM_MODEL or None,
                                                             "providers": list(PROVIDERS)}}


@router.get("/bricks")
def list_bricks(q: str | None = None, tag: str | None = None, limit: int = 20) -> dict:
    lib = library()
    if q:
        hits = lib.search(q, tag, limit)
    else:
        hits = [(b, 0.0) for b in sorted(lib.bricks.values(), key=lambda b: b.id) if not tag or tag in b.tags][:limit]
    return {"total": len(lib), "tags": dict(lib.tags().most_common()),
            "bricks": [{"id": b.id, "name": b.name, "tags": b.tags, "mount": b.mount, "ifc_class": b.ifc_class,
                        "line": b.line(), "score": score} for b, score in hits]}


@router.get("/bricks/{brick_id}")
def get_brick(brick_id: str) -> dict:
    brick = library().get(brick_id)
    if brick is None:
        raise HTTPException(404, f"no brick '{brick_id}'; closest: {', '.join(library().suggest(brick_id.replace('_', ' ')))}")
    return brick.model_dump() | {"card": brick.card()}


@router.get("/skills")
def list_skills() -> list[dict]:
    return [{"name": s.name, "title": s.title, "tags": s.tags, "bricks": s.bricks} for s in skillbook().all()]


@router.get("/skills/{name}")
def get_skill(name: str) -> dict:
    skill = skillbook().get(name)
    if skill is None:
        raise HTTPException(404, f"no skill '{name}'")
    return {"name": skill.name, "title": skill.title, "tags": skill.tags, "triggers": skill.triggers,
            "bricks": skill.bricks, "body": skill.body}


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
    return sse_response(lambda emit: pipeline.run_prompt(store, llm, project_id, req.prompt, req.base_version, emit, req.focus,
                                                         req.images))


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
        spec, design, guids = lift(tmp)
    except (LiftError, ValueError) as exc:
        raise HTTPException(422, f"cannot lift IFC: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - IfcOpenShell raises its own error types on unparseable files
        raise HTTPException(422, f"cannot read IFC: {exc}") from exc
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    notes = [f"imported {file.filename}: {len(spec.elements)} elements, {len(spec.levels)} levels"
             + ("" if design else " (no design record: only raw element edits are possible)")]
    return sse_response(lambda emit: pipeline.import_spec(store, project_id, spec, design, guids, notes, emit))


def _version(project_id: str, number: int):
    _project(project_id)
    v = store.get_version(project_id, number)
    if v is None:
        raise HTTPException(404, f"version {number} not found")
    return v


@router.get("/projects/{project_id}/versions/{number}/ifc")
def version_ifc(project_id: str, number: int):
    v = _version(project_id, number)
    return FileResponse(v.ifc_path, media_type="application/x-step", filename=export.filename(v, "ifc"),
                        headers={"Content-Disposition": f'attachment; filename="{export.filename(v, "ifc")}"'})


@router.get("/projects/{project_id}/versions/{number}/export")
def version_export(project_id: str, number: int, format: str = "zip", thorough: bool = False,
                   author: str | None = Query(None, max_length=200), organization: str | None = Query(None, max_length=200),
                   project_name: str | None = Query(None, max_length=200)):
    """Download a version as a deliverable. `format=zip` (default) is the whole bundle — IFC, the
    spec and design JSON, the editing context, the requirement checks, a take-off schedule, a
    validation report and a README. The other formats hand out a single file (see core/export.FORMATS).
    `validation` and `stamped` take `thorough=true` to include the schema's WHERE rules (a few seconds)."""
    v = _version(project_id, number)
    if format not in export.FORMATS:
        raise HTTPException(400, f"unknown export format '{format}' (known: {', '.join(export.FORMATS)})")
    name = export.filename(v, format)
    meta = ExportMeta(author=author, organization=organization, project_name=project_name)
    try:
        body = export.artifact(v, format, meta=meta, lineage=_lineage(v) if format == "stamped" else None, thorough=thorough)
    except export.StampError as exc:
        raise HTTPException(500, str(exc)) from exc
    return Response(body, media_type=export.MEDIA[format], headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _lineage(version) -> list:
    """This version and its ancestors, oldest first: the prompts that led to it."""
    out, seen = [version], {version.number}
    while out[-1].parent is not None and out[-1].parent not in seen:
        parent = store.get_version(version.project_id, out[-1].parent)
        if parent is None:
            break
        seen.add(parent.number)
        out.append(parent)
    return out[::-1]


@router.get("/projects/{project_id}/export")
def project_export(project_id: str):
    """The project's head version as a bundle — the URL to share when someone asks for "the model"."""
    _project(project_id)
    head = store.head(project_id)
    if head is None:
        raise HTTPException(404, f"project '{project_id}' has no versions yet")
    name = export.filename(head, "zip")
    return Response(export.bundle(head), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/projects/{project_id}/versions/{number}/spec")
def version_spec(project_id: str, number: int) -> dict:
    v = _version(project_id, number)
    return {"version": _with_url(v.as_version()), "spec": v.spec.model_dump(mode="json"),
            "design": v.design.model_dump(mode="json") if v.design else None, "guids": v.guids}


@router.get("/projects/{project_id}/versions/{number}/context", response_class=PlainTextResponse)
def version_context(project_id: str, number: int) -> str:
    """Exactly what the LLM sees as CURRENT DESIGN when editing this version (element listing if no design)."""
    v = _version(project_id, number)
    if v.design is None:
        return describe_spec(v.spec)
    try:
        return describe_design(v.design, analyze(v.design))
    except DesignError:
        return describe_design(v.design)


@router.get("/projects/{project_id}/versions/{number}/slices")
def version_slices(project_id: str, number: int, layer_height: float = 0.2) -> dict:
    """Layer-by-layer construction walkthrough, slicer-preview style (see slicer/slice.py)."""
    v = _version(project_id, number)
    model = ifcopenshell.open(v.ifc_path)
    layers = slice_model(model, layer_height)
    return {"layer_height": layer_height, "layers": [{"phase": l.phase, "z": l.z, "segments": l.segments} for l in layers]}


@router.get("/projects/{project_id}/versions/{number}/gcode", response_class=PlainTextResponse)
def version_gcode(project_id: str, number: int, layer_height: float = 0.2) -> str:
    v = _version(project_id, number)
    model = ifcopenshell.open(v.ifc_path)
    return to_gcode(slice_model(model, layer_height))


def _numbers(text: str | None) -> list[float] | None:
    if not text:
        return None
    try:
        return [float(n) for n in text.split(",")]
    except ValueError as exc:
        raise HTTPException(400, f"expected comma-separated numbers, got {text!r}") from exc


@router.get("/projects/{project_id}/versions/{number}/render")
def version_render(project_id: str, number: int, target: str | None = None, look_at: str | None = None, position: str | None = None,
                   azimuth: float = 225, elevation: float = 30, distance: float | None = None, level: str | None = None,
                   cut: float | None = None, hide: str | None = None, ortho: bool | None = None, fov: float = 50,
                   width: int = 1024, height: int = 768) -> Response:
    """The same screenshots the model takes when it checks its work (render/), from any view."""
    v = _version(project_id, number)
    if not (16 <= width <= MAX_RENDER and 16 <= height <= MAX_RENDER):
        raise HTTPException(400, f"width and height must be 16..{MAX_RENDER}")
    try:
        view = View(target=target, look_at=_numbers(look_at), position=_numbers(position), azimuth=azimuth, elevation=elevation,
                    distance=distance, level=level, cut=cut, hide=[h for h in (hide or "").split(",") if h], ortho=ortho, fov=fov)
    except ValidationError as exc:
        raise HTTPException(400, "; ".join(e["msg"] for e in exc.errors())) from exc
    rename = {space_id(r.level, r.id): r.id for r in v.design.rooms} if v.design else {}
    try:
        shot = render(scene_of(ifcopenshell.open(v.ifc_path), v.guids, rename), view, width, height)
    except ViewError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(shot.png, media_type="image/png", headers={"X-Visible": ",".join(i for i, _ in shot.visible)})


@router.get("/projects/{project_id}/shots/{name}")
def project_shot(project_id: str, name: str):
    _project(project_id)
    path = store.shot_path(project_id, name)
    if not SHOT_NAME.match(name) or not path.is_file():
        raise HTTPException(404, f"no screenshot '{name}'")
    return FileResponse(path, media_type="image/png")


@router.get("/projects/{project_id}/attachments/{name}")
def project_attachment(project_id: str, name: str):
    """An image attached to one of this project's prompts, by its content-addressed name (see `Version.images`)."""
    _project(project_id)
    path = store.attachment_path(project_id, name)
    if not STORED_NAME.match(name) or not path.is_file():
        raise HTTPException(404, f"no attachment '{name}'")
    return FileResponse(path, media_type=media_type_for(name))


@router.post("/projects/{project_id}/versions/{number}/construction")
def start_construction(project_id: str, number: int) -> dict:
    """Kick off a live build simulation: writes this version's elements to disk one construction
    step at a time (see core/construction.py). Poll the returned job with the GET below."""
    job = construction.start(_version(project_id, number))
    return job.status()


@router.get("/projects/{project_id}/versions/{number}/construction/{job_id}")
def construction_status(project_id: str, number: int, job_id: str) -> dict:
    _version(project_id, number)
    job = construction.get(job_id)
    if job is None:
        raise HTTPException(404, f"construction job '{job_id}' not found")
    return job.status()


# --- stateless -----------------------------------------------------------------

def _plan(req: PromptRequest) -> PlanResult:
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    try:
        return get_planner(req.planner).plan(req.prompt)
    except (ValueError, pipeline.PipelineError) as exc:  # includes spec validation errors
        raise HTTPException(422, f"planning failed: {exc}") from exc


def _build(spec: BuildingSpec) -> BuildResult:
    t0 = time.perf_counter()
    model_id = uuid.uuid4().hex[:12]
    try:
        summary = write_ifc(spec, OUTPUT_DIR / f"{model_id}.ifc")
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
    plan = _plan(req)
    return GenerateResult(plan=plan, **_build(plan.spec).model_dump())
