"""Deterministic BuildingSpec → IFC. This is the only place that decides IFC representation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom

from ifc.openings import add_opening
from ifc.project import create_project
from ifc.roofs import add_roof
from ifc.slabs import add_column, add_slab, add_space
from ifc.walls import add_wall
from schemas.bim import BuildingSpec, Column, Door, Roof, Slab, Space, Wall, Window

BUILDERS = [  # order matters: openings need their host walls
    (Wall, add_wall),
    (Slab, add_slab),
    (Space, add_space),
    (Column, add_column),
    (Roof, add_roof),
    ((Door, Window), add_opening),
]


def build_ifc(spec: BuildingSpec) -> ifcopenshell.file:
    ctx = create_project(spec)
    for kinds, build in BUILDERS:
        for el in spec.elements:
            if isinstance(el, kinds):
                build(ctx, el)
    return ctx.model


def check_geometry(model: ifcopenshell.file) -> list[str]:
    """Tessellate every product; return the ones that fail. Catches bad geometry before the viewer does."""
    settings = ifcopenshell.geom.settings()
    failures = []
    for product in model.by_type("IfcProduct"):
        if not product.Representation or product.is_a("IfcOpeningElement"):
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, product)
            if not shape.geometry.verts:
                failures.append(f"{product.is_a()} {product.Name}: empty geometry")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{product.is_a()} {product.Name}: {exc}")
    return failures


def summarize(model: ifcopenshell.file) -> dict:
    products = model.by_type("IfcElement") + model.by_type("IfcSpace")
    counts = Counter(p.is_a() for p in products if not p.is_a("IfcOpeningElement"))
    return {
        "schema": model.schema,
        "storeys": [s.Name for s in model.by_type("IfcBuildingStorey")],
        "spaces": [s.LongName or s.Name for s in model.by_type("IfcSpace")],
        "elements": sum(counts.values()),
        "counts": dict(sorted(counts.items())),
    }


def write_ifc(spec: BuildingSpec, path: Path) -> dict:
    model = build_ifc(spec)
    failures = check_geometry(model)
    if failures:
        raise ValueError("geometry check failed: " + "; ".join(failures[:10]))
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return summarize(model)
