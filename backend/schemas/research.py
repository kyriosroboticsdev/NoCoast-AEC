"""Research turns — the model looking things up before it builds.

Between the checklist and the build steps the model gets a few turns to call tools: search the
brick library, read a brick's card (its parameters, ranges and rules), list and read skills (how to
assemble bricks correctly), and check the current design. Each turn is one JSON object; the results
are shown on the next turn and everything it found goes into the build prompt.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ToolName = Literal["search_bricks", "get_brick", "list_skills", "get_skill", "check_design", "structure_report"]
MAX_CALLS = 8


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool: ToolName
    query: Optional[str] = Field(None, description="search_bricks: what you are looking for, in plain words")
    discipline: Optional[str] = Field(None, description="search_bricks: limit to one discipline (hvac, plumbing, structure …)")
    id: Optional[str] = Field(None, description="get_brick: brick id; get_skill: skill name")


class ResearchTurn(BaseModel):
    calls: list[ToolCall] = Field(default_factory=list, description=f"Up to {MAX_CALLS} tool calls, run in order")
    done: bool = Field(False, description="true when you know enough to build")

    @field_validator("calls", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        v = [v] if isinstance(v, dict) else v
        return v[:MAX_CALLS]
