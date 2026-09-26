"""Edit operations — the delta format the LLM emits when iterating on a design.

Two layers:

* **Typed ops** (`Op`): a discriminated union used internally, by the /ops endpoint and by
  `core/ops.py`. Precise, but as a JSON schema it is a union of seven op types each containing
  a union of seven element types — too large a grammar for constrained decoders.
* **Flat ops** (`FlatOp`): a one-object-per-op form that constrained decoders can handle. One object with an
  `op` enum and optional `id` / `element` / `level` / `set`; the element is a single object with a
  `type` enum and every field optional; the patch is one object covering every patchable field.
  `FlatOp.typed()` converts to a typed op and raises `OpError` with a model-readable message when a
  required part is missing or a field doesn't apply to the target.

The language model no longer emits ops directly (it emits design steps, schemas/steps.py); ops remain
the escape hatch for element-level edits from the UI or scripts and are stored as design overrides.

Ops are applied to the current BuildingSpec and the result is re-validated as a whole, so an op
can never leave the model in a state the IFC builder can't compile. Element ids are the stable
handles: they survive edits and map 1:1 to IFC GlobalIds (core/guids.py).
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from schemas.bim import Element, Level, Point

ElementKind = Literal["wall", "slab", "roof", "door", "window", "column", "space"]
OpKind = Literal["add_element", "modify_element", "delete_element", "add_level", "modify_level", "delete_level", "set_building"]


class OpError(ValueError):
    """An op could not be applied. The message is meant to be fed back to the LLM."""


# --- typed layer ------------------------------------------------------------

class AddElement(BaseModel):
    op: Literal["add_element"] = "add_element"
    element: Element


class ModifyElement(BaseModel):
    op: Literal["modify_element"] = "modify_element"
    id: str
    set: dict = Field(description="Fields to change, e.g. {\"end\": [12, 0]}; 'type' and 'id' cannot change")


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

_element_adapter = TypeAdapter(Element)
op_adapter = TypeAdapter(Op)


# --- flat layer (what the LLM emits) ------------------------------------------

class FlatElement(BaseModel):
    """Any element; set only the fields that apply to `type` (see the element conventions in the prompt)."""

    model_config = ConfigDict(extra="forbid")
    type: ElementKind
    id: str = Field(description="New unique id, e.g. 'L1-win-S3'")
    name: Optional[str] = None
    level: Optional[str] = Field(None, description="wall/slab/roof/space/column: storey id")
    start: Optional[Point] = Field(None, description="wall")
    end: Optional[Point] = Field(None, description="wall")
    height: Optional[float] = Field(None, description="wall/door/window/column/space")
    thickness: Optional[float] = Field(None, description="wall/slab/roof")
    external: Optional[bool] = Field(None, description="wall")
    outline: Optional[list[Point]] = Field(None, description="slab/roof/space: closed polygon")
    wall: Optional[str] = Field(None, description="door/window: host wall id")
    offset: Optional[float] = Field(None, description="door/window: along the wall from its start")
    width: Optional[float] = Field(None, description="door/window/column")
    sill_height: Optional[float] = Field(None, description="window")
    position: Optional[Point] = Field(None, description="column")
    depth: Optional[float] = Field(None, description="column")


class Patch(BaseModel):
    """Fields to change on an element, a level or the building. null = unchanged."""

    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    description: Optional[str] = Field(None, description="building only")
    level: Optional[str] = None
    start: Optional[Point] = None
    end: Optional[Point] = None
    height: Optional[float] = None
    thickness: Optional[float] = None
    external: Optional[bool] = None
    outline: Optional[list[Point]] = None
    wall: Optional[str] = None
    offset: Optional[float] = None
    width: Optional[float] = None
    sill_height: Optional[float] = None
    position: Optional[Point] = None
    depth: Optional[float] = None
    elevation: Optional[float] = Field(None, description="level only; leave null to keep levels stacked")

    def changes(self) -> dict:
        return self.model_dump(exclude_none=True)


LEVEL_FIELDS = {"name", "height", "elevation"}
BUILDING_FIELDS = {"name", "description"}


class FlatOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: OpKind
    id: Optional[str] = Field(None, description="modify_*/delete_*: the existing id")
    element: Optional[FlatElement] = Field(None, description="add_element only")
    level: Optional[Level] = Field(None, description="add_level only")
    set: Optional[Patch] = Field(None, description="modify_element / modify_level / set_building")

    def typed(self) -> Op:
        n = self.op
        try:
            if n == "add_element":
                if self.element is None:
                    raise OpError("add_element needs `element`")
                data = self.element.model_dump(exclude_none=True)
                return AddElement(element=_element_adapter.validate_python(data))
            if n == "add_level":
                if self.level is None:
                    raise OpError("add_level needs `level`")
                return AddLevel(level=self.level)
            if n in ("delete_element", "delete_level"):
                if not self.id:
                    raise OpError(f"{n} needs `id`")
                return DeleteElement(id=self.id) if n == "delete_element" else DeleteLevel(id=self.id)
            changes = self.set.changes() if self.set else {}
            if not changes:
                raise OpError(f"{n} needs at least one non-null field in `set`")
            if n == "modify_element":
                if not self.id:
                    raise OpError("modify_element needs `id`")
                bad = changes.keys() & {"elevation", "description"}
                if bad:
                    raise OpError(f"modify_element: {sorted(bad)} are not element fields")
                return ModifyElement(id=self.id, set=changes)
            if n == "modify_level":
                if not self.id:
                    raise OpError("modify_level needs `id`")
                bad = changes.keys() - LEVEL_FIELDS
                if bad:
                    raise OpError(f"modify_level: {sorted(bad)} are not level fields (use name, height, elevation)")
                return ModifyLevel(id=self.id, set=changes)
            bad = changes.keys() - BUILDING_FIELDS
            if bad:
                raise OpError(f"set_building: {sorted(bad)} are not building fields (use name, description)")
            return SetBuilding(set=changes)
        except ValidationError as exc:
            msgs = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors())
            raise OpError(f"{n}: {msgs}") from exc


class OpsResponse(BaseModel):
    """A raw op batch (the /ops endpoint and stored overrides)."""

    ops: list[FlatOp] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("notes", "ops", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        return [v] if isinstance(v, (str, dict)) else v

    def typed_ops(self) -> list[Op]:
        out = []
        for i, op in enumerate(self.ops, 1):
            try:
                out.append(op.typed())
            except OpError as exc:
                raise OpError(f"op {i}: {exc}") from exc
        return out
