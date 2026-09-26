"""Apply edit ops to a BuildingSpec. Pure: returns a new spec, never mutates the input."""

from __future__ import annotations

from difflib import get_close_matches

from pydantic import TypeAdapter, ValidationError

from schemas.bim import BuildingSpec, Door, Element, Level, Window
from schemas.ops import (AddElement, AddLevel, DeleteElement, DeleteLevel, ModifyElement, ModifyLevel, Op,
                         SetBuilding)

_element_adapter = TypeAdapter(Element)


class OpError(ValueError):
    """An op could not be applied. The message is meant to be fed back to the LLM."""


def _errors(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"] for e in exc.errors())


def apply_ops(spec: BuildingSpec, ops: list[Op]) -> tuple[BuildingSpec, list[str]]:
    """Return (new spec, cascade notes). Raises OpError with an LLM-readable message."""
    data = spec.model_dump(mode="json")
    elements: list[dict] = data["elements"]
    levels: list[dict] = data["levels"]
    notes: list[str] = []
    cascaded: set[str] = set()       # ids removed as a side effect; an explicit delete of them is not an error
    explicit_elevation: set[str] = set()  # levels whose elevation an op set on purpose

    def find(items: list[dict], id_: str, what: str) -> int:
        for i, item in enumerate(items):
            if item["id"] == id_:
                return i
        ids = [i["id"] for i in items]
        close = get_close_matches(id_, ids, n=3, cutoff=0.5)
        # Models like to prefix ids with the type ("wall-L1-wall-S"); catch that explicitly.
        close += [i for i in ids if id_.endswith(i) and i not in close]
        hint = f"; did you mean {', '.join(repr(c) for c in close)}?" if close else ""
        known = ", ".join(ids[:40])
        raise OpError(f"{what} '{id_}' does not exist{hint} (ids are exactly as listed after id=; known: {known}{', ...' if len(ids) > 40 else ''})")

    def delete_element(id_: str, reason: str | None = None) -> None:
        if id_ in cascaded and reason is None:
            return
        i = find(elements, id_, "element")
        removed = elements.pop(i)
        if reason:
            cascaded.add(id_)
            notes.append(f"deleted {removed['type']} '{id_}' ({reason})")
        if removed["type"] == "wall":
            for opening in [e for e in elements if e["type"] in ("door", "window") and e["wall"] == id_]:
                delete_element(opening["id"], f"hosted by deleted wall '{id_}'")

    for n, op in enumerate(ops, 1):
        where = f"op {n} ({op.op})"
        try:
            if isinstance(op, AddElement):
                el = op.element.model_dump(mode="json")
                if el["id"] and any(e["id"] == el["id"] for e in elements):
                    raise OpError(f"{where}: element id '{el['id']}' already exists; use modify_element")
                elements.append(el)
            elif isinstance(op, ModifyElement):
                i = find(elements, op.id, "element")
                if "type" in op.set and op.set["type"] != elements[i]["type"]:
                    raise OpError(f"{where}: cannot change the type of '{op.id}'; delete it and add a new element")
                if "id" in op.set and op.set["id"] != op.id:
                    raise OpError(f"{where}: element ids are immutable")
                merged = {**elements[i], **op.set}
                elements[i] = _element_adapter.validate_python(merged).model_dump(mode="json")
            elif isinstance(op, DeleteElement):
                delete_element(op.id)
            elif isinstance(op, AddLevel):
                lvl = op.level.model_dump(mode="json")
                if any(l["id"] == lvl["id"] for l in levels):
                    raise OpError(f"{where}: level id '{lvl['id']}' already exists")
                levels.append(lvl)
                if op.level.elevation is not None:
                    explicit_elevation.add(lvl["id"])
            elif isinstance(op, ModifyLevel):
                i = find(levels, op.id, "level")
                if "id" in op.set and op.set["id"] != op.id:
                    raise OpError(f"{where}: level ids are immutable")
                levels[i] = Level.model_validate({**levels[i], **op.set}).model_dump(mode="json")
                if "elevation" in op.set:
                    explicit_elevation.add(op.id)
            elif isinstance(op, DeleteLevel):
                i = find(levels, op.id, "level")
                levels.pop(i)
                for el in [e for e in elements if e.get("level") == op.id]:
                    delete_element(el["id"], f"on deleted level '{op.id}'")
            elif isinstance(op, SetBuilding):
                data["building"] = {**data["building"], **op.set}
        except ValidationError as exc:
            raise OpError(f"{where}: {_errors(exc)}") from exc

    # Elevations are re-stacked from level heights unless an op set one explicitly.
    for lvl in levels:
        if lvl["id"] not in explicit_elevation:
            lvl["elevation"] = None
    try:
        new_spec = BuildingSpec.model_validate(data)
    except ValidationError as exc:
        raise OpError(f"resulting model is invalid: {_errors(exc)}") from exc
    return new_spec, notes


def restack_levels(spec: BuildingSpec) -> BuildingSpec:
    """Recompute elevations after a level height changes (elevation=None means 'stack')."""
    data = spec.model_dump(mode="json")
    for lvl in data["levels"]:
        lvl["elevation"] = None
    return BuildingSpec.model_validate(data)


def hosted_openings(spec: BuildingSpec, wall_id: str) -> list[Door | Window]:
    return [e for e in spec.elements if isinstance(e, (Door, Window)) and e.wall == wall_id]
