"""Requirements — the checklist extracted from a prompt before anything is built.

Kinds are geometric. A requirement points at elements with a selector (`ifc`, `name`,
`level`, `id`) and asks a question the checker can answer from the compiled model.
`supported=false` is how the model records a wish the geometry cannot express.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

RequirementKind = Literal[
    "count",       # how many elements match; value is the minimum (default 1)
    "entity",      # at least `value` of an IFC entity, subtypes included
    "extent",      # bounding size along axis (x|y|z|longest|shortest) ≈ value
    "elevation",   # base or top (which) ≈ value
    "span",        # largest gap between supports under the selection ≈ value
    "clearance",   # free height under the selection ≥ value
    "enclosed",    # fraction of the footprint closed by other solids ≥ value
    "connects",    # two selections touch; the second is ifc2/name2
    "supported",   # every selected element has something beneath it, or sits on the ground
    "opening",     # voids cut into the selection ≥ value
    "volume",      # total solid volume ≈ value
    "area",        # total plan footprint ≈ value
    "curved",      # the selection is revolved, swept or faceted rather than a prism
    "levels",      # number of above-ground storeys == value
    "material",    # a selection's material name contains item
    "style",       # not checkable
    "other",       # not checkable
]


class Requirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(description="The requirement in the user's words, one atomic statement")
    kind: RequirementKind
    ifc: Optional[str] = Field(None, description="IFC entity; subtypes match (IfcWall matches IfcWallStandardCase)")
    name: Optional[str] = Field(None, description="Substring of the element's name")
    level: Optional[str] = Field(None, description="Level id: L1, L2, B1")
    id: Optional[str] = Field(None, description="Exact part id")
    ifc2: Optional[str] = Field(None, description="connects: entity of the second selection")
    name2: Optional[str] = Field(None, description="connects: name substring of the second selection")
    value: Optional[float] = Field(None, description="Count, metres, square metres, cubic metres, or a fraction")
    value2: Optional[float] = Field(None, description="extent: the other plan dimension")
    axis: Optional[str] = Field(None, description="extent: x, y, z, longest or shortest")
    which: Optional[str] = Field(None, description="elevation: base or top")
    item: Optional[str] = Field(None, description="material: the material name to look for")
    supported: bool = Field(True, description="false when the request cannot be checked or built")

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v):
        if v is None:
            return None
        if isinstance(v, int) and not isinstance(v, bool):
            return f"L{v}"
        s = str(v).strip()
        low = s.lower()
        words = {"ground": "L1", "first": "L1", "downstairs": "L1", "upstairs": "L2", "second": "L2", "third": "L3"}
        if low in words:
            return words[low]
        import re
        b = re.match(r"^\s*(?:b|basement\s*(?:level\s*)?|cellar\s*)(\d*)\s*$", s, re.IGNORECASE)
        if b:
            return f"B{int(b.group(1) or 1)}"
        m = re.match(r"^\s*(?:l|level\s*|floor\s*|storey\s*)?(\d+)\s*$", s, re.IGNORECASE)
        return f"L{int(m.group(1))}" if m else s.upper() if len(s) <= 3 else s

    @field_validator("axis", "which", mode="before")
    @classmethod
    def _lower(cls, v):
        return None if v is None else str(v).strip().lower()


class RequirementsResponse(BaseModel):
    summary: Optional[str] = Field(None, description="One sentence: what is being designed")
    requirements: list[Requirement] = Field(default_factory=list)

    @field_validator("requirements", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        return [v] if isinstance(v, dict) else v
