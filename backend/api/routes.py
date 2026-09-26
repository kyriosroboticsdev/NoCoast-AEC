"""HTTP API. The frontend only knows: prompt → spec → IFC URL."""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents import PLANNERS, PlanResult, get_planner
from agents.progress import NO_PROGRESS, Progress
from ifc.builder import write_ifc
from schemas.bim import BuildingSpec

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
router = APIRouter()


class PromptRequest(BaseModel):
    prompt: str
    planner: str | None = None


class BuildRequest(BaseModel):
    spec: BuildingSpec


class BuildResult(BaseModel):
    id: str
    ifc_url: str
    summary: dict
    seconds: float


class GenerateResult(BuildResult):
    plan: PlanResult


def _plan(req: PromptRequest, progress: Progress = NO_PROGRESS) -> PlanResult:
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    try:
        return get_planner(req.planner).plan(req.prompt, progress)
    except ValueError as exc:  # includes spec validation errors
        raise HTTPException(422, f"planning failed: {exc}") from exc


def _build(spec: BuildingSpec, progress: Progress = NO_PROGRESS) -> BuildResult:
    t0 = time.perf_counter()
    model_id = uuid.uuid4().hex[:12]
    try:
        summary = write_ifc(spec, OUTPUT_DIR / f"{model_id}.ifc", progress)
    except ValueError as exc:
        raise HTTPException(422, f"IFC build failed: {exc}") from exc
    return BuildResult(id=model_id, ifc_url=f"/models/{model_id}.ifc", summary=summary,
                       seconds=round(time.perf_counter() - t0, 3))


@router.get("/health")
def health() -> dict:
    return {"ok": True, "planners": list(PLANNERS)}


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


@router.post("/generate/stream")
def generate_stream(req: PromptRequest) -> StreamingResponse:
    """Same as /generate, narrated live as Server-Sent Events.

    event: step   {id, parent, phase, title, detail, status: running|done|error, ms?, layer}
    event: plan   {plan}      once the structured instructions exist
    event: build  {build}     once the IFC is written
    event: error  {message}
    """
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    events: queue.Queue = queue.Queue()

    def run() -> None:
        progress = Progress(events.put)
        try:
            plan = _plan(req, progress)
            events.put({"type": "plan", "plan": plan.model_dump(mode="json")})
            with progress.step("Validating the structured instructions", phase="validate",
                               detail="levels, ids, host walls, opening sizes") as s:
                spec = BuildingSpec.model_validate(plan.spec.model_dump())
                kinds = sorted({e.type for e in spec.elements})
                s.detail = f"{len(spec.elements)} elements OK · {', '.join(kinds)}"
            events.put({"type": "build", "build": _build(spec, progress).model_dump()})
        except HTTPException as exc:
            events.put({"type": "error", "message": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001 — report anything to the client instead of dropping the stream
            events.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
