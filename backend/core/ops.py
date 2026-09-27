"""Apply edit ops to a GeoModel. Pure: returns a new model, never mutates the input."""

from __future__ import annotations

from difflib import get_close_matches

from pydantic import TypeAdapter, ValidationError

from schemas.geo import GeoModel, GeoPart
from schemas.geosteps import remove_id
from schemas.ops import Delete, Modify, Op, OpError, SetModel

_op_adapter = TypeAdapter(Op)


def _errors(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors())


def apply_ops(geo: GeoModel, ops: list[Op]) -> tuple[GeoModel, list[str]]:
    """Return (new model, notes). Raises OpError with a readable message."""
    model = geo.model_copy(deep=True)
    notes: list[str] = []
    for n, op in enumerate(ops, 1):
        where = f"op {n} ({op.op})"
        try:
            if isinstance(op, Delete):
                notes.append(remove_id(model, op.id))
            elif isinstance(op, SetModel):
                if "name" in op.set and op.set["name"]:
                    model.name = str(op.set["name"])
                if "description" in op.set:
                    model.description = op.set["description"]
                notes.append(f"model renamed to {model.name}" if "name" in op.set else "model updated")
            elif isinstance(op, Modify):
                notes.append(_modify(model, op, where))
        except ValidationError as exc:
            raise OpError(f"{where}: {_errors(exc)}") from exc
        except ValueError as exc:
            raise OpError(f"{where}: {exc}") from exc
    try:
        return GeoModel.model_validate(model.model_dump()), notes
    except ValidationError as exc:
        raise OpError(f"resulting model is invalid: {_errors(exc)}") from exc


def _modify(model: GeoModel, op: Modify, where: str) -> str:
    part = model.part(op.id)
    if part is None:
        ids = [p.id for p in model.parts]
        close = get_close_matches(op.id, ids, n=3, cutoff=0.5)
        hint = f"; did you mean {', '.join(close)}?" if close else ""
        raise OpError(f"{where}: part '{op.id}' does not exist{hint}")
    if not op.set:
        raise OpError(f"{where}: no fields to change for '{op.id}'")
    data = part.model_dump()
    place = dict(data["place"])
    for key, value in op.set.items():
        if key in ("name", "material", "style", "ifc", "ifc_type", "level"):
            data[key] = value
        elif key == "at":
            place["at"] = value
        elif key == "rotation":
            place["rotation"] = value
        elif key == "axis":
            place["axis"] = value
        else:
            raise OpError(f"{where}: cannot change '{key}' on a part; delete it and add it again")
    data["place"] = place
    updated = GeoPart.model_validate(data)
    model.parts = [updated if p.id == updated.id else p for p in model.parts]
    return f"updated part {updated.id}"
