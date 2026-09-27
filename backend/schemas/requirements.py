"""Requirements — the checklist extracted from a prompt before anything is built.

The model turns the request into a flat list of atomic requirements, each tagged with
a `kind` the checker (core/checks.py) knows how to verify against the finished
design. Requirements the system cannot honour are flagged `supported=false` and
surfaced to the user instead of being silently dropped. The same format is used by
the evaluation set (tests/evals) so accuracy can be measured.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

RequirementKind = Literal[
    "storeys",      # value = number of storeys
    "room",         # room (name or kind keyword) exists; value = how many (default 1); level optional
    "room_level",   # room is on level
    "area",         # room has about value m² (±25 %)
    "adjacent",     # room and room2 share a wall
    "orientation",  # room has an exterior wall on side
    "window",       # room has >= value windows (on side if given)
    "door",         # a door connects room and room2 ('outside' allowed)
    "stair",        # a stair exists (in room if given)
    "furniture",    # item (furniture kind) exists (in room if given), value = count
    "asset",        # item (a library brick id, or words naming one) is placed (in room if given), value = count
    "structure",    # the structure works: no unsupported spans or overhangs (core/structure.py)
    "roof",         # roof kind == item
    "feature",      # item in: garage, porch, balcony, open_plan
    "dimension",    # footprint about value x value2 metres
    "material",     # exterior walls use item
    "style",        # not checkable (aesthetics, mood) — reported as informational
    "other",        # anything else that cannot be verified automatically
]


class Requirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(description="The requirement in the user's words, one atomic statement")
    kind: RequirementKind
    room: Optional[str] = Field(None, description="Room name or kind keyword ('bedroom', 'Master Bedroom')")
    room2: Optional[str] = Field(None, description="adjacent/door: the other room, or 'outside'")
    level: Optional[str] = Field(None, description="'L1', 'L2' … when the requirement names a storey")
    side: Optional[str] = Field(None, description="N|S|E|W when the requirement names a side")
    item: Optional[str] = Field(None, description="furniture kind, brick id, roof kind, feature name or material")
    value: Optional[float] = Field(None, description="count, area, storeys or width")
    value2: Optional[float] = Field(None, description="dimension: depth")
    supported: bool = Field(True, description="false when the system cannot honour it")

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v):
        if v is None:
            return None
        if isinstance(v, int) and not isinstance(v, bool):
            return f"L{v}"
        s = str(v).strip()
        low = s.lower()
        words = {"ground": "L1", "first": "L1", "downstairs": "L1", "upstairs": "L2", "second": "L2", "third": "L3", "top": None}
        if low in words:
            return words[low]
        import re
        b = re.match(r"^\s*(?:b|basement\s*(?:level\s*)?|cellar\s*)(\d*)\s*$", s, re.IGNORECASE)
        if b:
            return f"B{int(b.group(1) or 1)}"
        m = re.match(r"^\s*(?:l|level\s*|floor\s*|storey\s*)?(\d+)\s*$", s, re.IGNORECASE)
        return f"L{int(m.group(1))}" if m else s

    @field_validator("side", mode="before")
    @classmethod
    def _side(cls, v):
        if v is None:
            return None
        s = str(v).strip().lower()
        return {"n": "N", "north": "N", "s": "S", "south": "S", "e": "E", "east": "E", "w": "W", "west": "W"}.get(s, str(v).upper())


class RequirementsResponse(BaseModel):
    summary: Optional[str] = Field(None, description="One sentence: what is being designed")
    requirements: list[Requirement] = Field(default_factory=list)

    @field_validator("requirements", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        return [v] if isinstance(v, dict) else v
