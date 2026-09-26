"""Stateless LLM planner for /plan and /generate: prompt → checklist → build steps → spec."""

from __future__ import annotations

from agents.base import PlanResult
from core.derive import derive
from schemas.design import Design


class LLMPlanner:
    name = "llm"

    def plan(self, prompt: str) -> PlanResult:
        # Imported here: llm.mock depends on agents, so a module-level import would be circular.
        from core.pipeline import build_round, checklist_lines, request_requirements
        from llm import get_llm

        llm = get_llm()
        reqs = request_requirements(llm, prompt)
        stream = build_round(llm, prompt, Design(), checklist_lines(reqs.requirements), lambda *a: None, guids={}, first_index=0)
        spec, notes = derive(stream.design)
        return PlanResult(spec=spec, planner=f"{self.name}:{llm.name}", design=stream.design,
                          notes=stream.design.notes + notes + [f"rejected: {e}" for _, _, e in stream.rejected])
