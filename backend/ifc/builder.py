"""Deterministic BuildingSpec → IFC. This is the only place that decides IFC representation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom

from core.guids import GuidMap, ensure_guids
from ifc.fixtures import add_beam, add_fixture, add_railing
from ifc.mep import add_light, add_outlet, add_panel, add_pipe, add_wire
from ifc.openings import add_opening
from ifc.project import BuildContext, create_project
from ifc.roofs import add_roof
from ifc.slabs import add_column, add_slab, add_space
from ifc.stairs import add_stair, add_stair_wells
from ifc.walls import add_wall
from schemas.bim import (Beam, BuildingSpec, Column, Door, Fixture, LightFixture, Outlet, Panel, Pipe, Railing,
                         Roof, Slab, Space, Stair, Wall, Window, Wire)

BUILDERS = [  # construction order: foundation/floors, structure, roof, plumbing+electrical
    (Slab, add_slab),                  # rough-in, spaces, electrical trim, then fixtures/openings last
    (Wall, add_wall),                  # (openings need their host walls already built - Wall precedes them)
    (Column, add_column),
    (Beam, add_beam),
    (Roof, add_roof),
    (Pipe, add_pipe),
    (Space, add_space),
    (Outlet, add_outlet),
    (Panel, add_panel),
    (Wire, add_wire),
    ((Door, Window), add_opening),
    (Stair, add_stair),
    (Fixture, add_fixture),
    (LightFixture, add_light),
    (Railing, add_railing),
]


def build_ifc(spec: BuildingSpec, guids: GuidMap | None = None, design_json: str | None = None) -> BuildContext:
    ctx = create_project(spec, guids, design_json)
    for kinds, build in BUILDERS:
        for el in spec.elements:
            if isinstance(el, kinds):
                build(ctx, el)
    add_stair_wells(ctx)
    return ctx


def check_geometry(model: ifcopenshell.file, only: set[str] | None = None, products=None) -> list[str]:
    """Tessellate products; return the ones that fail. Catches bad geometry before the viewer does.
    `only` restricts the check to those element ids (previews re-check just what changed)."""
    settings = ifcopenshell.geom.settings()
    failures = []
    candidates = model.by_type("IfcProduct") if only is None else [p for i, p in (products or {}).items() if i in only]
    for product in candidates:
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


class GeometryError(ValueError):
    pass


def compile_ifc(spec: BuildingSpec, guids: GuidMap | None = None, design_json: str | None = None,
                check: set[str] | None = None) -> tuple[ifcopenshell.file, GuidMap]:
    """Build and geometry-check. Returns the model and the (possibly extended) guid map.
    `check` limits the geometry check to those element ids (None = everything)."""
    guids = ensure_guids(spec, guids)
    ctx = build_ifc(spec, guids, design_json)
    failures = check_geometry(ctx.model, check, ctx.products)
    if failures:
        raise GeometryError("geometry check failed: " + "; ".join(failures[:10]))
    return ctx.model, guids


def write_ifc(spec: BuildingSpec, path: Path, guids: GuidMap | None = None, design_json: str | None = None) -> dict:
    model, _ = compile_ifc(spec, guids, design_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return summarize(model)
