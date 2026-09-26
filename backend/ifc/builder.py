"""Deterministic BuildingSpec → IFC. This is the only place that decides IFC representation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom

from agents.progress import NO_PROGRESS, Progress
from core.guids import GuidMap, ensure_guids
from ifc.openings import add_opening
from ifc.project import create_project
from ifc.roofs import add_roof
from ifc.slabs import add_column, add_slab, add_space
from ifc.walls import add_wall
from schemas.bim import BuildingSpec, Column, Door, Roof, Slab, Space, Wall, Window

BUILDERS = [  # order matters: openings need their host walls
    (Wall, add_wall, ("wall", "walls")),
    (Slab, add_slab, ("slab", "slabs")),
    (Space, add_space, ("room", "rooms")),
    (Column, add_column, ("column", "columns")),
    (Roof, add_roof, ("roof", "roofs")),
    ((Door, Window), add_opening, ("door/window", "doors & windows")),
]


def build_ifc(spec: BuildingSpec, guids: GuidMap | None = None, progress: Progress = NO_PROGRESS) -> ifcopenshell.file:
    with progress.step("Setting up the IFC project", phase="build") as s:
        ctx = create_project(spec, guids)
        s.detail = f"IfcProject → IfcSite → IfcBuilding · {len(spec.levels)} storeys · metres · IFC4"

    # Build storey by storey so the model grows the way a building does. Doors and windows
    # belong to their host wall's storey; roofs form their own final layer.
    wall_level = {e.id: e.level for e in spec.elements if isinstance(e, Wall)}

    def layer_of(el) -> str:
        if isinstance(el, Roof):
            return "roof"
        return wall_level[el.wall] if isinstance(el, (Door, Window)) else el.level

    layers = [(lv.id, lv.name, f"elevation {lv.elevation:g} m · {lv.height:g} m tall") for lv in spec.levels]
    layers.append(("roof", "Roof", "on top of the storeys below"))
    for layer_id, name, detail in layers:
        items = [e for e in spec.elements if layer_of(e) == layer_id]
        if not items:
            continue
        with progress.step(f"Building {name}", phase="build", detail=detail, layer=True) as lay:
            for kinds, build, label in BUILDERS:
                group = [e for e in items if isinstance(e, kinds)]
                if not group:
                    continue
                with progress.step(f"{len(group)} {label[len(group) != 1]}", phase="build", parent=lay):
                    for el in group:
                        build(ctx, el)
            lay.detail = f"{detail} · {len(items)} elements"
    return ctx.model


def check_geometry(model: ifcopenshell.file, on_progress=None) -> list[str]:
    """Tessellate every product; return the ones that fail. Catches bad geometry before the viewer does."""
    settings = ifcopenshell.geom.settings()
    failures = []
    products = [p for p in model.by_type("IfcProduct") if p.Representation and not p.is_a("IfcOpeningElement")]
    for i, product in enumerate(products):
        if on_progress and i % 10 == 0:
            on_progress(i, len(products))
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


def compile_ifc(spec: BuildingSpec, guids: GuidMap | None = None,
                progress: Progress = NO_PROGRESS) -> tuple[ifcopenshell.file, GuidMap]:
    """Build and geometry-check. Returns the model and the (possibly extended) guid map."""
    guids = ensure_guids(spec, guids)
    model = build_ifc(spec, guids, progress)
    with progress.step("Checking geometry", phase="build", detail="tessellating every element with IfcOpenShell") as s:
        failures = check_geometry(model, lambda i, n: s.update(f"tessellating {i}/{n} elements"))
        if failures:
            raise GeometryError("geometry check failed: " + "; ".join(failures[:10]))
        n = sum(1 for p in model.by_type("IfcProduct") if p.Representation and not p.is_a("IfcOpeningElement"))
        s.detail = f"{n} elements tessellated, no failures"
    return model, guids


def write_ifc(spec: BuildingSpec, path: Path, guids: GuidMap | None = None) -> dict:
    model, _ = compile_ifc(spec, guids)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return summarize(model)
