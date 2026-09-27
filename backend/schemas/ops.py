"""Edit operations on a GeoModel.

The model streams GeoSteps. These ops are the escape hatch for the /ops endpoint: delete a
part, patch a few fields, rename the model. They are applied to the current GeoModel and the
result is re-validated, so an op cannot leave the model in a state the compiler cannot build.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class OpError(ValueError):
    """An op could not be applied. The message is meant to be fed back to the caller."""


class Delete(BaseModel):
    model_config = ConfigDict(extra="ignore")
    op: Literal["delete"] = "delete"
    id: str


class Modify(BaseModel):
    model_config = ConfigDict(extra="ignore")
    op: Literal["modify"] = "modify"
    id: str
    set: dict = Field(description="Fields to change: name, material, style, ifc, at, rotation")


class SetModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    op: Literal["set_model"] = "set_model"
    set: dict = Field(description="Fields of the model record: name, description")


Op = Annotated[Union[Delete, Modify, SetModel], Field(discriminator="op")]


class OpsRequest(BaseModel):
    ops: list[Op] = Field(default_factory=list)
    base_version: Optional[int] = None
