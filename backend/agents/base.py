"""Planner interface: natural language → structured BIM instructions.

Any planner (rule-based, local LLM, cloud LLM) implements `plan`. The API and the
IFC builder only ever see a `PlanResult`, so planners are swappable.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from schemas.bim import BuildingSpec


class PlanResult(BaseModel):
    spec: BuildingSpec
    planner: str
    notes: list[str] = []  # how the prompt was interpreted — shown to the user


class Planner(Protocol):
    name: str

    def plan(self, prompt: str) -> PlanResult: ...
