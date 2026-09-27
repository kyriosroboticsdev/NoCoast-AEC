"""Planner registry for the stateless /plan and /generate endpoints.

Select with the BIM_PLANNER env var (default: cards). The stateful project pipeline
(core/pipeline.py) uses the LLM adapter in llm/ instead. Neither path expands a house template.
"""

from __future__ import annotations

import os

from agents.base import Planner, PlanResult
from agents.cards import CardsPlanner
from agents.llm_planner import LLMPlanner

PLANNERS: dict[str, type] = {"cards": CardsPlanner, "llm": LLMPlanner}


def get_planner(name: str | None = None) -> Planner:
    name = name or os.environ.get("BIM_PLANNER", "cards")
    if name not in PLANNERS:
        raise ValueError(f"unknown planner '{name}' (available: {', '.join(PLANNERS)})")
    return PLANNERS[name]()


__all__ = ["Planner", "PlanResult", "get_planner", "PLANNERS"]
