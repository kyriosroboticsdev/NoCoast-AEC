"""Stateless LLM planner for /plan and /generate: prompt → checklist → GeoSteps → model."""

from __future__ import annotations

from agents.base import PlanResult


class LLMPlanner:
    name = "llm"

    def plan(self, prompt: str) -> PlanResult:
        from core.pipeline import build_round, checklist_lines, request_requirements
        from llm import get_llm
        from schemas.geo import GeoModel

        llm = get_llm()
        reqs = request_requirements(llm, prompt)
        stream = build_round(llm, prompt, GeoModel(), checklist_lines(reqs.requirements), lambda *a: None,
                             guids={}, first_index=0)
        notes = list(stream.geo.notes) + [f"rejected: {e}" for _, _, e in stream.rejected]
        return PlanResult(model=stream.geo, planner=f"{self.name}:{llm.name}", notes=notes)
