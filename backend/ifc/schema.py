"""The IFC schema, asked rather than hard-coded.

This is the only module in the tree that knows anything about which IFC entities exist, and
it knows them by introspecting the schema with IfcOpenShell — there is no list of entity
names anywhere. A `GeoPart` names its entity as a plain string (`"IfcWall"`,
`"IfcCivilElement"`, `"IfcTendon"`) and this module answers three questions about it: does it
exist, is it instantiable, is it a product. `PredefinedType` values come from the same place.

`IFC_SCHEMA` is the single named constant that decides the version. It is overridable with
`BIM_IFC_SCHEMA`, so moving the whole backend to IFC4X3 is one value — plus a viewer
decision, which is why it is IFC4 today: the bundled viewer pins web-ifc 0.0.77 and its 4X3
support cannot be assumed. Where a civil concept only exists in 4X3, the recipe cards in
`blocks/` say which 4X3 entity they would prefer and which IFC4 entity they use instead.
"""

from __future__ import annotations

import functools
import os
from difflib import get_close_matches

import ifcopenshell
import ifcopenshell.ifcopenshell_wrapper as wrapper

#: The schema every compiled model and every entity-name check is resolved against.
IFC_SCHEMA = os.environ.get("BIM_IFC_SCHEMA", "IFC4")

#: Every element a `GeoPart` may be must be one of these (a spatial-structure element is
#: reachable too, because an IfcSpace is a perfectly good part).
PRODUCT_ROOT = "IfcProduct"


class SchemaError(ValueError):
    """An entity name or predefined type the configured schema does not accept. The message
    is written for the language model."""


@functools.lru_cache(maxsize=None)
def schema(name: str | None = None):
    return wrapper.schema_by_name(name or IFC_SCHEMA)


@functools.lru_cache(maxsize=None)
def _declaration(name: str, schema_name: str):
    try:
        return schema(schema_name).declaration_by_name(name)
    except Exception:  # noqa: BLE001 - IfcOpenShell raises a bare RuntimeError for unknown names
        return None


@functools.lru_cache(maxsize=None)
def supertypes(name: str, schema_name: str | None = None) -> tuple[str, ...]:
    """`name` and every entity it inherits from, most derived first. Empty when unknown."""
    decl = _declaration(name, schema_name or IFC_SCHEMA)
    if decl is None or not isinstance(decl, wrapper.entity):
        return ()
    out: list[str] = []
    while decl is not None:
        out.append(decl.name())
        decl = decl.supertype()
    return tuple(out)


@functools.lru_cache(maxsize=None)
def product_entities(schema_name: str | None = None) -> tuple[str, ...]:
    """Every instantiable product entity in the schema, sorted. Used only for error messages
    and for the `blocks`/prompt docs — never as an allow-list."""
    s = schema(schema_name)
    out = []
    for decl in s.declarations():
        if not isinstance(decl, wrapper.entity) or decl.is_abstract():
            continue
        if PRODUCT_ROOT in supertypes(decl.name(), schema_name or IFC_SCHEMA):
            out.append(decl.name())
    return tuple(sorted(out))


def normalise(name: str) -> str:
    """`ifcwall`, `IFCWALL`, `wall` → `IfcWall` when that names something in the schema."""
    raw = str(name or "").strip()
    if not raw:
        return raw
    lowered = raw.lower()
    if not lowered.startswith("ifc"):
        lowered = "ifc" + lowered
    for candidate in product_entities():
        if candidate.lower() == lowered:
            return candidate
    return raw


def check_entity(name: str) -> str:
    """Return the canonical entity name, or raise SchemaError explaining what is wrong."""
    canonical = normalise(name)
    decl = _declaration(canonical, IFC_SCHEMA)
    if decl is None or not isinstance(decl, wrapper.entity):
        close = get_close_matches(canonical, product_entities(), n=4, cutoff=0.6)
        hint = f"; did you mean {', '.join(close)}?" if close else ""
        raise SchemaError(f"'{name}' is not an entity in {IFC_SCHEMA}{hint}")
    if decl.is_abstract():
        subs = sorted(d.name() for d in decl.subtypes() or []) if hasattr(decl, "subtypes") else []
        hint = f"; use one of its subtypes, e.g. {', '.join(subs[:5])}" if subs else ""
        raise SchemaError(f"{canonical} is abstract in {IFC_SCHEMA} and cannot be created{hint}")
    if PRODUCT_ROOT not in supertypes(canonical):
        raise SchemaError(f"{canonical} is not an {PRODUCT_ROOT} and cannot carry geometry or a placement")
    return canonical


@functools.lru_cache(maxsize=None)
def predefined_types(entity: str) -> tuple[str, ...]:
    """The values `PredefinedType` accepts on this entity, or () when it has no such attribute."""
    decl = _declaration(entity, IFC_SCHEMA)
    if decl is None or not isinstance(decl, wrapper.entity):
        return ()
    for attr in decl.all_attributes():
        if attr.name() != "PredefinedType":
            continue
        t = attr.type_of_attribute()
        # The attribute is usually optional, so unwrap the named/aggregation wrappers until an
        # enumeration declaration appears.
        for _ in range(6):
            if isinstance(t, wrapper.enumeration_type):
                return tuple(t.enumeration_items())
            declared = getattr(t, "declared_type", None)
            t = declared() if callable(declared) else declared
            if t is None:
                break
        return ()
    return ()


def check_predefined_type(entity: str, value: str | None) -> str | None:
    """Canonical PredefinedType (upper case, underscores kept), or raise SchemaError."""
    if value is None or str(value).strip() == "":
        return None
    allowed = predefined_types(entity)
    want = str(value).strip().upper().replace(" ", "").replace("-", "")
    if not allowed:
        raise SchemaError(f"{entity} has no PredefinedType in {IFC_SCHEMA}; leave ifc_type out")
    for candidate in allowed:
        if candidate.replace("_", "") == want.replace("_", ""):
            return candidate
    close = get_close_matches(want, allowed, n=4, cutoff=0.5)
    hint = f"; did you mean {', '.join(close)}?" if close else f" (allowed: {', '.join(allowed)})"
    raise SchemaError(f"'{value}' is not a PredefinedType of {entity} in {IFC_SCHEMA}{hint}")


def is_a(entity: str, root: str) -> bool:
    """Entity-name subtype test that does not need a model instance."""
    return normalise(root) in supertypes(normalise(entity))


def schema_version() -> str:
    """What `ifcopenshell.api.project.create_file(version=…)` should be given."""
    return IFC_SCHEMA


def describe() -> dict:
    return {"schema": IFC_SCHEMA, "products": len(product_entities()),
            "ifcopenshell": ifcopenshell.version}
