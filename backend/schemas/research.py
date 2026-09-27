"""Research turns — the model looking things up before it builds.

Between the checklist and the build steps the model gets a few turns to call tools: search the
brick library, read a brick's card (its parameters, ranges, mount and connectors), try out an asset
definition it is writing, list and read skills, and check the current design. Each turn is one JSON object; the results
are shown on the next turn and everything it found goes into the build prompt.
"""

from __future__ import annotations

import json
from typing import Literal, Optional, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

ToolName = Literal["search_bricks", "get_brick", "check_asset", "list_skills", "get_skill", "check_design", "structure_report"]
MAX_CALLS = 8

# How each tool is called and what it returns, as the research prompt lists them.
TOOL_HELP: dict[ToolName, str] = {
    "search_bricks": '{"tool":"search_bricks","query":"<plain words>","tag":<optional>}   find bricks ("fresh air", "hot water")',
    "get_brick": '{"tool":"get_brick","id":"<brick id>"}   its card: parameters with ranges, mount, connectors it needs/supplies',
    "check_asset": '{"tool":"check_asset","definition":"<asset JSON>"}   validate an asset you are writing: its card, or what is wrong',
    "list_skills": '{"tool":"list_skills"}   every skill with its title',
    "get_skill": '{"tool":"get_skill","id":"<skill name>"}   one skill: how to write or assemble a kind of thing',
    "check_design": '{"tool":"check_design"}   clashes, blocked doors, intersecting elements, bad hosts (floating, partly buried, wrong wall/roof/slab, wrong orientation), missing services and structure issues',
    "structure_report": '{"tool":"structure_report"}   spans and overhangs only',
}
assert set(TOOL_HELP) == set(get_args(ToolName)), "every tool needs a TOOL_HELP line"


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool: ToolName
    query: Optional[str] = Field(None, description="search_bricks: what you are looking for, in plain words")
    tag: Optional[str] = Field(None, description="search_bricks: only bricks with this tag")
    id: Optional[str] = Field(None, description="get_brick: brick id; get_skill: skill name")
    definition: Optional[str] = Field(None, description="check_asset: a complete asset definition as a JSON string")

    @field_validator("definition", mode="before")
    @classmethod
    def _definition(cls, v):
        return json.dumps(v) if isinstance(v, dict) else v


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
