"""`GeoModel` → IFC. The only place that decides how a part becomes an IFC product.

The shape of the output is fixed and small:

    IfcProject
      IfcSite
        IfcBuilding                       carries the whole model as JSON (`MODEL_PSET`)
          IfcBuildingStorey  per level    Description = the level id, for the viewer's snaps
            <entity>         per part     one Body representation holding the part's solids
            IfcElementAssembly           per assembly and per instance copy
          IfcOpeningElement  per opening  voids its host, optionally filled by a part

Nothing here switches on what a part *means*: the entity name comes from the part and was
validated against the schema by `ifc/schema.py`, the geometry comes from `ifc/solids.py`, and
colour falls back along the entity's own supertype chain. Adding a kind of building needs no
change to this file.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.style
import ifcopenshell.api.unit
import ifcopenshell.geom
import numpy as np

from core.guids import GuidMap, ensure_guids, key_for_assembly, key_for_level, key_for_opening, key_for_part
from ifc.schema import IFC_SCHEMA, is_a, supertypes
from ifc.solids import box_solid, build_solid, representation_kind
from schemas.geo import GeoModel, GeoOpening, GeoPart, Placement
from schemas.geosteps import expand_instances

PART_PSET = "NoCoast_Geo"     # on every product: the part's own JSON, so our files lift losslessly
MODEL_PSET = "NoCoast_Model"  # on IfcBuilding: the whole GeoModel

CLEARANCE = 0.05  # an opening box pokes out of both host faces so the boolean cut is clean

# Colour by IFC entity. Looked up along the entity's supertype chain, so an unlisted
# `IfcPile` picks up `IfcElement`'s grey rather than needing an entry.
ENTITY_COLOURS: dict[str, tuple[tuple[float, float, float], float]] = {
    "IfcWall": ((0.90, 0.89, 0.86), 0.0),
    "IfcCurtainWall": ((0.55, 0.75, 0.90), 0.45),
    "IfcSlab": ((0.62, 0.62, 0.64), 0.0),
    "IfcRoof": ((0.40, 0.28, 0.24), 0.0),
    "IfcColumn": ((0.75, 0.75, 0.78), 0.0),
    "IfcBeam": ((0.62, 0.50, 0.38), 0.0),
    "IfcMember": ((0.58, 0.58, 0.62), 0.0),
    "IfcPlate": ((0.70, 0.72, 0.74), 0.0),
    "IfcFooting": ((0.55, 0.55, 0.56), 0.0),
    "IfcPile": ((0.50, 0.50, 0.52), 0.0),
    "IfcDoor": ((0.55, 0.38, 0.22), 0.0),
    "IfcWindow": ((0.55, 0.75, 0.90), 0.55),
    "IfcStair": ((0.78, 0.72, 0.62), 0.0),
    "IfcStairFlight": ((0.78, 0.72, 0.62), 0.0),
    "IfcRamp": ((0.72, 0.70, 0.66), 0.0),
    "IfcRampFlight": ((0.72, 0.70, 0.66), 0.0),
    "IfcRailing": ((0.35, 0.35, 0.38), 0.0),
    "IfcCovering": ((0.92, 0.91, 0.88), 0.0),
    "IfcFurniture": ((0.62, 0.45, 0.30), 0.0),
    "IfcSanitaryTerminal": ((0.95, 0.95, 0.97), 0.0),
    "IfcSpace": ((0.40, 0.70, 0.95), 0.85),
    "IfcCivilElement": ((0.66, 0.66, 0.64), 0.0),
    "IfcEarthworksElement": ((0.48, 0.40, 0.30), 0.0),
    "IfcGeographicElement": ((0.45, 0.55, 0.40), 0.0),
    "IfcDistributionElement": ((0.45, 0.46, 0.48), 0.0),
    "IfcFlowTerminal": ((0.90, 0.88, 0.80), 0.0),
    "IfcElement": ((0.72, 0.72, 0.72), 0.0),
    "IfcProduct": ((0.72, 0.72, 0.72), 0.0),
}

# Colour by free-text material / style key. Wins over the entity when the part names one.
MATERIAL_COLOURS: dict[str, tuple[tuple[float, float, float], float]] = {
    "concrete": ((0.72, 0.72, 0.72), 0.0),
    "reinforced concrete": ((0.68, 0.68, 0.69), 0.0),
    "masonry": ((0.86, 0.78, 0.70), 0.0),
    "brick": ((0.72, 0.42, 0.33), 0.0),
    "stone": ((0.60, 0.58, 0.55), 0.0),
    "granite": ((0.55, 0.54, 0.56), 0.0),
    "timber": ((0.74, 0.56, 0.36), 0.0),
    "wood": ((0.74, 0.56, 0.36), 0.0),
    "oak": ((0.66, 0.48, 0.28), 0.0),
    "steel": ((0.58, 0.60, 0.64), 0.0),
    "aluminium": ((0.78, 0.79, 0.82), 0.0),
    "copper": ((0.72, 0.45, 0.20), 0.0),
    "glass": ((0.55, 0.75, 0.90), 0.55),
    "plaster": ((0.95, 0.95, 0.93), 0.0),
    "plastic": ((0.88, 0.88, 0.86), 0.0),
    "fabric": ((0.52, 0.55, 0.62), 0.0),
    "ceramic": ((0.95, 0.95, 0.97), 0.0),
    "tile": ((0.62, 0.36, 0.28), 0.0),
    "asphalt": ((0.24, 0.24, 0.26), 0.0),
    "earth": ((0.42, 0.33, 0.24), 0.0),
    "soil": ((0.42, 0.33, 0.24), 0.0),
    "rock": ((0.48, 0.47, 0.45), 0.0),
    "water": ((0.30, 0.55, 0.75), 0.65),
    "grass": ((0.42, 0.58, 0.32), 0.0),
    "gravel": ((0.62, 0.60, 0.56), 0.0),
    "membrane": ((0.86, 0.86, 0.84), 0.2),
}


class GeometryError(ValueError):
    """The compiled model has geometry no tessellator can make sense of."""


@dataclass
class Built:
    model: ifcopenshell.file
    body: ifcopenshell.entity_instance
    geo: GeoModel
    guids: GuidMap
    storeys: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    products: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    parts: dict[str, GeoPart] = field(default_factory=dict)
    styles: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)
    materials: dict[str, ifcopenshell.entity_instance] = field(default_factory=dict)


# --- placement ---------------------------------------------------------------

def matrix_of(place: Placement, z_offset: float = 0.0) -> np.ndarray:
    """A placement as a 4x4, with `z_offset` (the level elevation) added to the origin."""
    x, y, z = place.basis()
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2] = x, y, z
    m[:3, 3] = [place.at[0], place.at[1], place.at[2] + z_offset]
    return m


# --- colour and material ------------------------------------------------------

def colour_for(part: GeoPart) -> tuple[str, tuple[float, float, float], float]:
    """(style key, rgb, transparency). A named style or material wins; otherwise the entity's
    own supertype chain is walked, which is why a brand-new entity name still gets a colour."""
    for key in (part.style, part.material):
        if key and key.strip().lower() in MATERIAL_COLOURS:
            k = key.strip().lower()
            return k, *MATERIAL_COLOURS[k]
        if key and key.strip() in ENTITY_COLOURS:
            k = key.strip()
            return k, *ENTITY_COLOURS[k]
    for name in supertypes(part.ifc):
        if name in ENTITY_COLOURS:
            return name, *ENTITY_COLOURS[name]
    return "IfcProduct", *ENTITY_COLOURS["IfcProduct"]


def _style(ctx: Built, key: str, rgb: tuple[float, float, float], transparency: float):
    if key not in ctx.styles:
        style = ifcopenshell.api.style.add_style(ctx.model, name=key)
        ifcopenshell.api.style.add_surface_style(
            ctx.model, style=style, ifc_class="IfcSurfaceStyleShading",
            attributes={"SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]},
                        "Transparency": transparency},
        )
        ctx.styles[key] = style
    return ctx.styles[key]


def _material(ctx: Built, name: str):
    key = name.strip().title()
    if key not in ctx.materials:
        ctx.materials[key] = ifcopenshell.api.material.add_material(ctx.model, name=key)
    return ctx.materials[key]


# --- the skeleton -------------------------------------------------------------

def create_project(geo: GeoModel, guids: GuidMap) -> Built:
    model = ifcopenshell.api.project.create_file(version=IFC_SCHEMA)
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name=geo.name)
    project.GlobalId = guids["project"]
    if geo.description:
        project.Description = geo.description

    units = [ifcopenshell.api.unit.add_si_unit(model, unit_type=t)
             for t in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT", "PLANEANGLEUNIT")]
    ifcopenshell.api.unit.assign_unit(model, units=units)

    model3d = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model3d
    )

    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    site.GlobalId = guids["site"]
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name=geo.name)
    building.GlobalId = guids["building"]
    if geo.description:
        building.Description = geo.description
    add_json_pset(model, building, MODEL_PSET, geo.model_dump_json())
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
    for product in (site, building):
        ifcopenshell.api.geometry.edit_object_placement(model, product=product, matrix=np.eye(4))

    ctx = Built(model=model, body=body, geo=geo, guids=guids)
    elevations = geo.elevations()
    for level in geo.ordered_levels():
        storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name=level.display)
        storey.GlobalId = guids[key_for_level(level.id)]
        storey.Elevation = elevations[level.id]
        storey.Description = level.id  # the viewer maps step events (level ids) to storeys through this
        add_json_pset(model, storey, PART_PSET, level.model_dump_json())
        ifcopenshell.api.geometry.edit_object_placement(
            model, product=storey, matrix=matrix_of(Placement(), elevations[level.id])
        )
        ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)
        ctx.storeys[level.id] = storey
    return ctx


def add_json_pset(model: ifcopenshell.file, product, name: str, payload: str) -> None:
    ps = ifcopenshell.api.pset.add_pset(model, product=product, name=name)
    ifcopenshell.api.pset.edit_pset(model, pset=ps, properties={"Json": payload})


# --- parts --------------------------------------------------------------------

def add_part(ctx: Built, part: GeoPart) -> ifcopenshell.entity_instance:
    m = ctx.model
    kwargs = {"ifc_class": part.ifc, "name": part.name or part.id}
    if part.ifc_type:
        kwargs["predefined_type"] = part.ifc_type
    element = ifcopenshell.api.root.create_entity(m, **kwargs)
    element.GlobalId = ctx.guids[key_for_part(part.id)]
    if hasattr(element, "Tag"):
        element.Tag = part.id
    # The viewer and the summary both read a space's long name; the part name is the only
    # word the model gave it ("bedroom", "pier"), so that is what shows up as a room label.
    if part.ifc == "IfcSpace" and hasattr(element, "LongName"):
        element.LongName = part.name or part.id

    items = [build_solid(m, solid, outer=copy if not copy.is_identity else None)
             for copy in part.placements() for solid in part.solids]
    rep = m.createIfcShapeRepresentation(ctx.body, "Body", representation_kind(part.solids), items)
    elevation = ctx.geo.elevations().get(part.level, 0.0)
    ifcopenshell.api.geometry.edit_object_placement(m, product=element, matrix=matrix_of(part.place, elevation))
    ifcopenshell.api.geometry.assign_representation(m, product=element, representation=rep)

    key, rgb, transparency = colour_for(part)
    try:
        ifcopenshell.api.style.assign_representation_styles(
            m, shape_representation=rep, styles=[_style(ctx, key, rgb, transparency)]
        )
    except Exception:  # noqa: BLE001 - colour is cosmetic, never a reason to fail a build
        pass
    if part.material:
        ifcopenshell.api.material.assign_material(m, products=[element], material=_material(ctx, part.material))
    if part.level in ctx.storeys:
        # IfcSpace (and any other spatial element) is aggregated into its storey. Every other
        # product is contained by it. assign_container only walks IfcElement's inverse.
        storey = ctx.storeys[part.level]
        if is_a(part.ifc, "IfcSpatialElement"):
            ifcopenshell.api.aggregate.assign_object(m, products=[element], relating_object=storey)
        else:
            ifcopenshell.api.spatial.assign_container(m, products=[element], relating_structure=storey)
    add_json_pset(m, element, PART_PSET, part.model_dump_json())
    ctx.products[part.id] = element
    ctx.parts[part.id] = part
    return element


# --- openings -----------------------------------------------------------------

def opening_solid(host: GeoPart, opening: GeoOpening):
    """The void, in the host part's own local frame."""
    if opening.solid is not None:
        return opening.solid
    lo, hi = host.local_extent()
    across = opening.depth if opening.depth is not None else (hi[1] - lo[1]) + 2 * CLEARANCE
    mid_y = (lo[1] + hi[1]) / 2
    return box_solid(float(opening.width), float(across), float(opening.height),
                     at=(float(opening.along) + float(opening.width) / 2, mid_y, lo[2] + float(opening.up or 0.0)))


def add_opening(ctx: Built, opening: GeoOpening) -> None:
    m = ctx.model
    host = ctx.products.get(opening.host)
    part = ctx.parts.get(opening.host)
    if host is None or part is None:
        return
    void = ifcopenshell.api.root.create_entity(m, ifc_class="IfcOpeningElement", name=f"{opening.id} opening")
    void.GlobalId = ctx.guids[key_for_opening(opening.id)]
    solid = opening_solid(part, opening)
    rep = m.createIfcShapeRepresentation(ctx.body, "Body", representation_kind([solid]), [build_solid(m, solid)])
    elevation = ctx.geo.elevations().get(part.level, 0.0)
    ifcopenshell.api.geometry.edit_object_placement(m, product=void, matrix=matrix_of(part.place, elevation))
    ifcopenshell.api.geometry.assign_representation(m, product=void, representation=rep)
    ifcopenshell.api.feature.add_feature(m, feature=void, element=host)
    if opening.fill and opening.fill in ctx.products:
        ifcopenshell.api.feature.add_filling(m, opening=void, element=ctx.products[opening.fill])


# --- assemblies ---------------------------------------------------------------

def add_assembly(ctx: Built, key: str, name: str, part_ids: list[str], level: str | None) -> None:
    members = [ctx.products[p] for p in part_ids if p in ctx.products]
    if not members:
        return
    m = ctx.model
    asm = ifcopenshell.api.root.create_entity(m, ifc_class="IfcElementAssembly", name=name)
    asm.GlobalId = ctx.guids[key]
    elevation = ctx.geo.elevations().get(level or "", 0.0)
    ifcopenshell.api.geometry.edit_object_placement(m, product=asm, matrix=matrix_of(Placement(), elevation))
    # The members stay in their storey as well. An assembly is a grouping here, not a
    # replacement for spatial containment: the viewer walks the spatial tree to build its
    # storey list and would silently lose every assembled part otherwise.
    if level and level in ctx.storeys:
        ifcopenshell.api.spatial.assign_container(m, products=[asm], relating_structure=ctx.storeys[level])
    ifcopenshell.api.aggregate.assign_object(m, products=members, relating_object=asm)


# --- build --------------------------------------------------------------------

def build_ifc(geo: GeoModel, guids: GuidMap | None = None) -> Built:
    guids = ensure_guids(geo, guids)
    ctx = create_project(geo, guids)
    for part in expand_instances(geo):
        add_part(ctx, part)
    for opening in geo.openings:
        add_opening(ctx, opening)
    for asm in geo.assemblies:
        add_assembly(ctx, key_for_assembly(asm.id), asm.name or asm.id, asm.parts, asm.level)
    for inst in geo.instances:
        source = geo.assembly(inst.of)
        if source is None:
            continue
        for i in range(inst.copies):
            tag = inst.id if inst.copies == 1 else f"{inst.id}-{i + 1}"
            ids = [f"{inst.id}-{p}" if inst.copies == 1 else f"{inst.id}-{i + 1}-{p}" for p in source.parts]
            add_assembly(ctx, key_for_assembly(tag), tag, ids, inst.level or source.level)
    return ctx


def check_geometry(model: ifcopenshell.file, only: set[str] | None = None, products=None) -> list[str]:
    """Tessellate products and report the ones that fail, so bad geometry is caught here rather
    than in the viewer. `only` restricts the check to those part ids (previews re-check just
    what changed)."""
    settings = ifcopenshell.geom.settings()
    failures: list[str] = []
    if only is None:
        candidates = model.by_type("IfcProduct")
    else:
        candidates = [p for i, p in (products or {}).items() if i in only]
    for product in candidates:
        if not getattr(product, "Representation", None) or product.is_a("IfcOpeningElement"):
            continue
        label = f"{product.is_a()} {product.Name or product.GlobalId}"
        try:
            shape = ifcopenshell.geom.create_shape(settings, product)
            if not shape.geometry.verts:
                failures.append(f"{label}: empty geometry")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label}: {exc}")
    return failures


def summarize(model: ifcopenshell.file) -> dict:
    """The shape the API has always returned: schema, storey names, space names, counts."""
    products = [p for p in model.by_type("IfcElement") if not p.is_a("IfcOpeningElement")]
    products += model.by_type("IfcSpace")
    counts = Counter(p.is_a() for p in products)
    storeys = sorted(model.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0)
    return {
        "schema": model.schema,
        "storeys": [s.Name for s in storeys],
        "spaces": [s.LongName or s.Name for s in model.by_type("IfcSpace")],
        "elements": sum(counts.values()),
        "counts": dict(sorted(counts.items())),
    }


def compile_ifc(geo: GeoModel, guids: GuidMap | None = None,
                check: set[str] | None = None) -> tuple[ifcopenshell.file, GuidMap]:
    guids = ensure_guids(geo, guids)
    ctx = build_ifc(geo, guids)
    failures = check_geometry(ctx.model, check, ctx.products)
    if failures:
        raise GeometryError("geometry check failed: " + "; ".join(failures[:10]))
    return ctx.model, guids


def write_ifc(geo: GeoModel, path: Path, guids: GuidMap | None = None) -> dict:
    model, _ = compile_ifc(geo, guids)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    return summarize(model)
