"""Stateless planner: retrieve the closest recipe card and apply its exemplar.

This is the whole of `/plan`. A card is a worked example, so the result is that example —
not a house laid out from the prompt. Prompts that match nothing are rejected rather than
filled in with a default building.
"""

from __future__ import annotations

from agents.base import PlanResult
from blocks import retrieve
from schemas.geo import GeoModel
from schemas.geosteps import GeoStep, apply_step


class CardsPlanner:
    name = "cards"

    def plan(self, prompt: str) -> PlanResult:
        found = retrieve(prompt, k=1)
        if not found:
            raise ValueError("no recipe card matches this prompt")
        card = found[0]
        model = GeoModel(name=card.title)
        for raw in card.steps:
            model, _ = apply_step(model, GeoStep.model_validate(raw))
        note = card.summary
        if card.ifc4x3:
            note += f" IFC4 types this as {card.ifc}; IFC4X3 would use {card.ifc4x3}."
        return PlanResult(model=model, planner=self.name, notes=[note])
