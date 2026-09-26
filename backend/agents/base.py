"""Planner interface: natural language → Program → BuildingSpec.

Any planner (rule-based, local LLM, cloud LLM) implements `plan`. The API and the
IFC builder only ever see a `PlanResult`, so planners are swappable.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from agents.progress import NO_PROGRESS, Progress
from schemas.bim import BuildingSpec
from schemas.program import Program


class PlanResult(BaseModel):
    spec: BuildingSpec
    planner: str
    program: Program | None = None
    notes: list[str] = []  # how the prompt was interpreted — shown to the user


class Planner(Protocol):
    name: str

    def plan(self, prompt: str, progress: Progress = NO_PROGRESS) -> PlanResult:
        """Report steps on `progress` as you go; the UI shows them live."""
        ...
