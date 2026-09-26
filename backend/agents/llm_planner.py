"""Stateless LLM planner for /plan and /generate: prompt → Program (via the LLM adapter) → solver."""

from __future__ import annotations

from agents.base import PlanResult
from solver.layout import solve


class LLMPlanner:
    name = "llm"

    def plan(self, prompt: str) -> PlanResult:
        # Imported here: llm.mock depends on agents, so a module-level import would be circular.
        from core.pipeline import request_program
        from llm import get_llm

        llm = get_llm()
        program = request_program(llm, prompt)
        return PlanResult(spec=solve(program), planner=f"{self.name}:{llm.name}", program=program, notes=program.notes)
