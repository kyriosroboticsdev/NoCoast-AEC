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

from core.guids import GuidMap, ensure_guids, key_for_element, key_for_level
from schemas.bim import BuildingSpec

SPEC_PSET = "NoCoast_Spec"      # carries the element's spec JSON so our own files can be lifted back losslessly
DESIGN_PSET = "NoCoast_Design"  # on IfcBuilding: the semantic design the spec was derived from

# style name -> (rgb 0..1, transparency 0..1)
STYLES = {
    "Wall": ((0.90, 0.89, 0.86), 0.0),
    "Wall:masonry": ((0.86, 0.78, 0.70), 0.0),
    "Wall:concrete": ((0.72, 0.72, 0.72), 0.0),
    "Wall:timber": ((0.74, 0.56, 0.36), 0.0),
    "Wall:plaster": ((0.95, 0.95, 0.93), 0.0),
    "Wall:stone": ((0.60, 0.58, 0.55), 0.0),
    "Wall:glass": ((0.55, 0.75, 0.90), 0.5),
    "Slab": ((0.62, 0.62, 0.64), 0.0),
    "Roof": ((0.30, 0.32, 0.36), 0.0),
    "Roof:pitched": ((0.48, 0.26, 0.20), 0.0),
    "Door": ((0.55, 0.38, 0.22), 0.0),
    "Window": ((0.55, 0.75, 0.90), 0.55),
    "Column": ((0.75, 0.75, 0.78), 0.0),
    "Beam": ((0.55, 0.40, 0.28), 0.0),
    "Space": ((0.40, 0.70, 0.95), 0.85),
    "Stair": ((0.78, 0.72, 0.62), 0.0),
    "Railing": ((0.35, 0.35, 0.38), 0.0),
    "Fixture:wood": ((0.62, 0.45, 0.30), 0.0),
    "Fixture:soft": ((0.52, 0.55, 0.62), 0.0),
    "Fixture:sanitary": ((0.95, 0.95, 0.97), 0.0),
    "Fixture:appliance": ((0.82, 0.82, 0.84), 0.0),
    "Fixture:car": ((0.70, 0.15, 0.15), 0.0),
    "Fixture:fire": ((0.45, 0.35, 0.32), 0.0),
    "Pipe:water": ((0.55, 0.56, 0.58), 0.0),
    "Pipe:electrical": ((0.30, 0.30, 0.32), 0.0),
    "Outlet": ((0.94, 0.93, 0.88), 0.0),
    "Light": ((1.00, 0.97, 0.80), 0.0),
    "Panel": ((0.28, 0.29, 0.31), 0.0),
    "Wire": ((0.85, 0.65, 0.13), 0.0),
    "Asset:wood": ((0.62, 0.45, 0.30), 0.0),
    "Asset:soft": ((0.52, 0.55, 0.62), 0.0),
    "Asset:sanitary": ((0.95, 0.95, 0.97), 0.0),
    "Asset:appliance": ((0.82, 0.82, 0.84), 0.0),
    "Asset:metal": ((0.58, 0.60, 0.63), 0.0),
    "Asset:glass": ((0.55, 0.75, 0.90), 0.5),
    "Asset:concrete": ((0.72, 0.72, 0.72), 0.0),
    "Asset:plant": ((0.30, 0.55, 0.28), 0.0),
    "Asset:water": ((0.35, 0.62, 0.85), 0.35),
    "Asset:stone": ((0.60, 0.58, 0.55), 0.0),
    "Asset:device": ((0.90, 0.90, 0.88), 0.0),
    "Asset:duct": ((0.70, 0.73, 0.76), 0.0),
    "Asset:solar": ((0.12, 0.16, 0.30), 0.0),
    "Asset:fire": ((0.80, 0.12, 0.12), 0.0),
    "Asset:car": ((0.70, 0.15, 0.15), 0.0),
}
MATERIALS = {"Wall": "Masonry", "Wall:masonry": "Masonry", "Wall:concrete": "Concrete", "Wall:timber": "Timber",
             "Wall:plaster": "Plaster", "Wall:stone": "Stone", "Wall:glass": "Glass", "Slab": "Concrete",
             "Roof": "Concrete", "Roof:pitched": "Roof tiles", "Door": "Timber", "Window": "Glass", "Column": "Concrete",
             "Beam": "Timber", "Stair": "Timber", "Railing": "Steel", "Fixture:wood": "Timber", "Fixture:soft": "Fabric",
             "Fixture:sanitary": "Ceramic", "Fixture:appliance": "Steel", "Fixture:car": "Steel", "Fixture:fire": "Stone",
             "Pipe:water": "Copper", "Pipe:electrical": "Steel", "Outlet": "Plastic", "Light": "Plastic",
             "Panel": "Steel", "Wire": "Plastic", "Asset:wood": "Timber", "Asset:soft": "Fabric", "Asset:sanitary": "Ceramic",
             "Asset:appliance": "Steel", "Asset:metal": "Steel", "Asset:glass": "Glass", "Asset:concrete": "Concrete",
             "Asset:plant": "Vegetation", "Asset:water": "Water", "Asset:stone": "Stone", "Asset:device": "Plastic",
             "Asset:duct": "Galvanised steel", "Asset:solar": "Glass", "Asset:fire": "Steel", "Asset:car": "Steel"}


@dataclass
class BuildContext:
    model: ifcopenshell.file
    body: ifcopenshell.entity_instance
    spec: BuildingSpec
    guids: GuidMap
    storeys: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    walls: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    slabs: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    products: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)  # element id -> product
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


def add_json_pset(model: ifcopenshell.file, product, name: str, payload: str) -> None:
    ps = ifcopenshell.api.pset.add_pset(model, product=product, name=name)
    ifcopenshell.api.pset.edit_pset(model, pset=ps, properties={"Json": payload})


def add_spec_pset(model: ifcopenshell.file, product, payload: str) -> None:
    add_json_pset(model, product, SPEC_PSET, payload)


def create_project(spec: BuildingSpec, guids: GuidMap | None = None, design_json: str | None = None) -> BuildContext:
    guids = ensure_guids(spec, guids)
    model = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name=spec.building.name)
    project.GlobalId = guids["project"]

    length = ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT")
    area = ifcopenshell.api.unit.add_si_unit(model, unit_type="AREAUNIT")
    volume = ifcopenshell.api.unit.add_si_unit(model, unit_type="VOLUMEUNIT")
    ifcopenshell.api.unit.assign_unit(model, units=[length, area, volume])

    model3d = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model3d
    )

    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    site.GlobalId = guids["site"]
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name=spec.building.name)
    building.GlobalId = guids["building"]
    if spec.building.description:
        building.Description = spec.building.description
    add_spec_pset(model, building, spec.building.model_dump_json())
    if design_json:
        add_json_pset(model, building, DESIGN_PSET, design_json)
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
    for product in (site, building):
        ifcopenshell.api.geometry.edit_object_placement(model, product=product, matrix=placement())

    ctx = BuildContext(model=model, body=body, spec=spec, guids=guids)

    for level in spec.levels:
        storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name=level.name)
        storey.GlobalId = guids[key_for_level(level.id)]
        storey.Elevation = level.elevation
        storey.Description = level.id  # the viewer maps step events (level ids) to storeys through this
        add_spec_pset(model, storey, level.model_dump_json())
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
    item=None,
) -> None:
    """Attach geometry, placement, style, material, container, the stable GlobalId,
    the spec pset and an optional standard property set."""
    m = ctx.model
    if item is not None:
        element.GlobalId = ctx.guids[key_for_element(item.id)]
        if hasattr(element, "Tag"):  # IfcSpace has no Tag; its Name already carries the id
            element.Tag = item.id
        add_spec_pset(m, element, item.model_dump_json())
        ctx.products[item.id] = element
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
