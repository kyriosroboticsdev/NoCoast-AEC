"""Project skeleton: IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey, plus shared helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.style
import ifcopenshell.api.unit

from schemas.bim import BuildingSpec

# name -> (rgb 0..1, transparency 0..1)
STYLES = {
    "Wall": ((0.90, 0.89, 0.86), 0.0),
    "Slab": ((0.62, 0.62, 0.64), 0.0),
    "Roof": ((0.30, 0.32, 0.36), 0.0),
    "Door": ((0.55, 0.38, 0.22), 0.0),
    "Window": ((0.55, 0.75, 0.90), 0.55),
    "Column": ((0.75, 0.75, 0.78), 0.0),
    "Space": ((0.40, 0.70, 0.95), 0.85),
}
MATERIALS = {"Wall": "Masonry", "Slab": "Concrete", "Roof": "Concrete", "Door": "Timber", "Window": "Glass", "Column": "Concrete"}


@dataclass
class BuildContext:
    model: ifcopenshell.file
    body: ifcopenshell.entity_instance
    spec: BuildingSpec
    storeys: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    walls: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    styles: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    materials: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)

    def level(self, level_id: str):
        return next(l for l in self.spec.levels if l.id == level_id)


def placement(x: float = 0, y: float = 0, z: float = 0, angle: float = 0) -> np.ndarray:
    """4x4 matrix: rotate `angle` radians about Z, then translate."""
    c, s = math.cos(angle), math.sin(angle)
    m = np.eye(4)
    m[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    m[:3, 3] = [x, y, z]
    return m


def translate(x: float = 0, y: float = 0, z: float = 0) -> np.ndarray:
    return placement(x, y, z)


def create_project(spec: BuildingSpec) -> BuildContext:
    model = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name=spec.building.name)

    length = ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT")
    area = ifcopenshell.api.unit.add_si_unit(model, unit_type="AREAUNIT")
    volume = ifcopenshell.api.unit.add_si_unit(model, unit_type="VOLUMEUNIT")
    ifcopenshell.api.unit.assign_unit(model, units=[length, area, volume])

    model3d = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model3d
    )

    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name=spec.building.name)
    if spec.building.description:
        building.Description = spec.building.description
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
    for product in (site, building):
        ifcopenshell.api.geometry.edit_object_placement(model, product=product, matrix=placement())

    ctx = BuildContext(model=model, body=body, spec=spec)

    for level in spec.levels:
        storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name=level.name)
        storey.Elevation = level.elevation
        ifcopenshell.api.geometry.edit_object_placement(model, product=storey, matrix=translate(z=level.elevation))
        ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)
        ctx.storeys[level.id] = storey

    for name, (rgb, transparency) in STYLES.items():
        style = ifcopenshell.api.style.add_style(model, name=name)
        colour = {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]}
        ifcopenshell.api.style.add_surface_style(
            model, style=style, ifc_class="IfcSurfaceStyleShading",
            attributes={"SurfaceColour": colour, "Transparency": transparency},
        )
        ctx.styles[name] = style
    for name in set(MATERIALS.values()):
        ctx.materials[name] = ifcopenshell.api.material.add_material(model, name=name)

    return ctx


def finish_element(
    ctx: BuildContext,
    element: ifcopenshell.entity_instance,
    representation: ifcopenshell.entity_instance,
    matrix: np.ndarray,
    kind: str,
    level_id: str | None = None,
    pset: tuple[str, dict] | None = None,
) -> None:
    """Attach geometry, placement, style, material, container and an optional property set."""
    m = ctx.model
    ifcopenshell.api.geometry.edit_object_placement(m, product=element, matrix=matrix)
    ifcopenshell.api.geometry.assign_representation(m, product=element, representation=representation)
    if kind in ctx.styles:
        try:
            ifcopenshell.api.style.assign_representation_styles(m, shape_representation=representation, styles=[ctx.styles[kind]])
        except Exception:
            pass  # parametric door/window reps can use mapped items; colour is cosmetic
    if kind in MATERIALS:
        ifcopenshell.api.material.assign_material(m, products=[element], material=ctx.materials[MATERIALS[kind]])
    if level_id is not None:
        ifcopenshell.api.spatial.assign_container(m, products=[element], relating_structure=ctx.storeys[level_id])
    if pset:
        ps = ifcopenshell.api.pset.add_pset(m, product=element, name=pset[0])
        ifcopenshell.api.pset.edit_pset(m, pset=ps, properties=pset[1])
