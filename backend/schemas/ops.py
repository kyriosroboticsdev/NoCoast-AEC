"""Edit operations — the delta format the LLM emits when iterating on a design.

Ops are applied to the current BuildingSpec (core/ops.py) and the result is
re-validated as a whole, so an op can never leave the model in a state the IFC
builder can't compile. Element ids are the stable handles: they survive edits and
map 1:1 to IFC GlobalIds (core/guids.py).
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from schemas.bim import Element, Level
from schemas.program import Program


class AddElement(BaseModel):
    op: Literal["add_element"] = "add_element"
    element: Element


class ModifyElement(BaseModel):
    op: Literal["modify_element"] = "modify_element"
    id: str
    set: dict = Field(description="Fields to change, e.g. {\"end\": [12, 0]} or {\"width\": 1.5}. 'type' cannot change.")


class DeleteElement(BaseModel):
    op: Literal["delete_element"] = "delete_element"
    id: str


class AddLevel(BaseModel):
    op: Literal["add_level"] = "add_level"
    level: Level


class ModifyLevel(BaseModel):
    op: Literal["modify_level"] = "modify_level"
    id: str
    set: dict


class DeleteLevel(BaseModel):
    op: Literal["delete_level"] = "delete_level"
    id: str


class SetBuilding(BaseModel):
    op: Literal["set_building"] = "set_building"
    set: dict = Field(description="Fields of the building record: name, description")


Op = Annotated[
    Union[AddElement, ModifyElement, DeleteElement, AddLevel, ModifyLevel, DeleteLevel, SetBuilding],
    Field(discriminator="op"),
]


class EditResponse(BaseModel):
    """What the LLM returns for an edit prompt.

    mode="ops": a minimal list of ops against the current spec.
    mode="redesign": the change touches rooms/storeys/footprint, so a new Program
    is produced and the layout solver regenerates the spec (ids that still exist
    keep their GlobalIds).
    """

    mode: Literal["ops", "redesign"]
    ops: list[Op] = Field(default_factory=list)
    program: Program | None = None
    notes: list[str] = Field(default_factory=list, description="What was changed and why, for the user")
