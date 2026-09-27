"""Planner interface: natural language → GeoModel.

`/plan` and `/generate` see a PlanResult. There is no house template and no Design.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from schemas.geo import GeoModel


class PlanResult(BaseModel):
    model: GeoModel
    planner: str
    notes: list[str] = []


class Planner(Protocol):
    name: str

    def plan(self, prompt: str) -> PlanResult: ...
