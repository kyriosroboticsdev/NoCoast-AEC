"""HTTP API. The frontend only knows: prompt → spec → IFC URL."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents import PLANNERS, PlanResult, get_planner
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


def _plan(req: PromptRequest) -> PlanResult:
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    try:
        return get_planner(req.planner).plan(req.prompt)
    except ValueError as exc:  # includes spec validation errors
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
