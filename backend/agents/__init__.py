"""Planner registry for the stateless /plan and /generate endpoints.

Select with the BIM_PLANNER env var (default: template). The stateful project
pipeline (core/pipeline.py) uses the LLM adapter in llm/ instead.
"""

from __future__ import annotations

import os

from agents.base import Planner, PlanResult
from agents.llm_planner import LLMPlanner
from agents.template_planner import TemplatePlanner

PLANNERS: dict[str, type] = {"template": TemplatePlanner, "llm": LLMPlanner}


def get_planner(name: str | None = None) -> Planner:
    name = name or os.environ.get("BIM_PLANNER", "template")
    if name not in PLANNERS:
        raise ValueError(f"unknown planner '{name}' (available: {', '.join(PLANNERS)})")
    return PLANNERS[name]()


__all__ = ["Planner", "PlanResult", "get_planner", "PLANNERS"]
