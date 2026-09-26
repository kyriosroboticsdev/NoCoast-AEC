"""Normalise and measure an uploaded IFC component.

A component is every building element in the file, treated as one rigid object. Its local frame
is the minimum corner of its footprint at its lowest point, so placing it at (x, y) on a level puts
that corner there. Everything is converted to IFC4 in metres on upload (ifcpatch Migrate and
ConvertLengthUnit), because `append_asset` must not mix schemas or units.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as element_util
import ifcopenshell.util.unit as unit_util

MAX_BYTES = 50 * 1024 * 1024
MAX_PRODUCTS = 2000  # a component is a part, not a building
_SKIP = ("IfcOpeningElement", "IfcVirtualElement", "IfcFeatureElement")


class ComponentError(ValueError):
    """The upload cannot be used as a component; the message says why, in words a user can act on."""


@dataclass
class ComponentInfo:
    name: str
    schema_in: str
    unit_in: str
    size: tuple[float, float, float]  # width (x), depth (y), height (z) in metres
    origin: tuple[float, float, float]  # the file's min corner, subtracted when placing
    products: list[str]  # GlobalIds of the top-level elements that make up the component
    counts: dict[str, int] = field(default_factory=dict)


def _quiet_patch(args: dict) -> ifcopenshell.file:
    """ifcpatch recipes print every entity they touch; keep the server log readable."""
    import ifcpatch

    logger = logging.getLogger("ifcpatch.quiet")
    logger.setLevel(logging.ERROR)
    with contextlib.redirect_stdout(io.StringIO()):
        return ifcpatch.execute({**args, "log": None, "logger": logger})


def normalise(model: ifcopenshell.file, source: str = "upload") -> tuple[ifcopenshell.file, str, str]:
    """Return (IFC4-in-metres model, original schema, original length unit name)."""
    schema_in = model.schema
    if schema_in not in ("IFC2X3", "IFC4", "IFC4X3", "IFC4X3_ADD2"):
        raise ComponentError(f"unsupported IFC schema {schema_in}")
    if schema_in != "IFC4":
        try:
            model = _quiet_patch({"input": source, "file": model, "recipe": "Migrate", "arguments": ["IFC4"]})
        except Exception as exc:  # noqa: BLE001 - ifcpatch raises assorted errors
            raise ComponentError(f"could not convert {schema_in} to IFC4: {exc}") from exc
    scale = unit_util.calculate_unit_scale(model)
    unit_in = "metre" if abs(scale - 1) < 1e-9 else {0.001: "millimetre", 0.01: "centimetre", 0.3048: "foot",
                                                     0.0254: "inch"}.get(round(scale, 4), f"{scale} m")
    if abs(scale - 1) > 1e-9:
        try:
            model = _quiet_patch({"input": source, "file": model, "recipe": "ConvertLengthUnit", "arguments": ["METER"]})
        except Exception as exc:  # noqa: BLE001
            raise ComponentError(f"could not convert {unit_in}s to metres: {exc}") from exc
    return model, schema_in, unit_in


def _top_level(model: ifcopenshell.file) -> list[ifcopenshell.entity_instance]:
    """Elements with geometry that are not parts of another element (a stair, not its flights)."""
    out = []
    for el in model.by_type("IfcElement"):
        if any(el.is_a(s) for s in _SKIP):
            continue
        if element_util.get_aggregate(el) is not None and element_util.get_aggregate(el).is_a("IfcElement"):
            continue  # copied along with its parent
        if el.Representation or element_util.get_parts(el):
            out.append(el)
    return out


def measure(model: ifcopenshell.file, elements: list) -> tuple[np.ndarray, np.ndarray]:
    """World-space bounding box (min, max) of the elements' tessellated geometry, parts included."""
    targets = list(elements)
    for el in elements:
        targets += [p for p in element_util.get_decomposition(el) if p.is_a("IfcElement")]
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    iterator = ifcopenshell.geom.iterator(settings, model, include=targets)
    if iterator.initialize():
        while True:
            verts = np.asarray(iterator.get().geometry.verts).reshape(-1, 3)
            if len(verts):
                lo, hi = np.minimum(lo, verts.min(0)), np.maximum(hi, verts.max(0))
            if not iterator.next():
                break
    if not np.isfinite(lo).all():
        raise ComponentError("the file has no geometry that can be tessellated")
    return lo, hi


def _name(model: ifcopenshell.file, elements: list, filename: str) -> str:
    stem = re.sub(r"\.ifc$", "", filename, flags=re.I).replace("_", " ").strip()
    project = (model.by_type("IfcProject") or [None])[0]
    candidates = [getattr(project, "Name", None)] + ([elements[0].Name] if len(elements) == 1 else [])
    for c in candidates:
        if c and c.strip() and c.strip().lower() not in ("project", "default project", "untitled"):
            return c.strip()[:80]
    return stem[:80] or "Component"


def analyse(model: ifcopenshell.file, filename: str) -> tuple[ifcopenshell.file, ComponentInfo]:
    """Normalise and describe an uploaded model. Raises ComponentError with a user-facing reason."""
    model, schema_in, unit_in = normalise(model, filename)
    elements = _top_level(model)
    if not elements:
        raise ComponentError("the file has no building elements to place (only spatial structure or annotations)")
    if len(elements) > MAX_PRODUCTS:
        raise ComponentError(f"the file has {len(elements)} elements; a component should be one object, "
                             f"not a whole building (limit {MAX_PRODUCTS})")
    lo, hi = measure(model, elements)
    size = tuple(round(float(v), 3) for v in hi - lo)
    if max(size) > 60:
        raise ComponentError(f"the file is {size[0]} × {size[1]} × {size[2]} m; that is a site, not a component")
    counts = dict(sorted(Counter(e.is_a() for e in elements).items()))
    return model, ComponentInfo(
        name=_name(model, elements, filename), schema_in=schema_in, unit_in=unit_in,
        size=size, origin=tuple(round(float(v), 4) for v in lo),
        products=[e.GlobalId for e in elements], counts=counts,
    )
