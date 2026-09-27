"""Placed bricks (schemas.bim.Asset) → IFC: whatever element class the brick names, drawn from its
evaluated solids (ifc/solids.py), each styled with its own material. A NoCoast_Brick property set says
which brick it is, its tags, connectors and parameter values; the brick's own properties go into a
NoCoast_Properties set."""

from __future__ import annotations

import json

import ifcopenshell.api.material
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.style

from bricks.geometry import transform
from ifc.project import BuildContext, finish_element
from ifc.solids import items, representation_type
from schemas.bim import Asset

BRICK_PSET = "NoCoast_Brick"
PROPERTIES_PSET = "NoCoast_Properties"


def add_asset(ctx: BuildContext, asset: Asset) -> None:
    m = ctx.model
    level = ctx.level(asset.level)
    element = ifcopenshell.api.root.create_entity(m, ifc_class=asset.ifc_class, predefined_type=asset.predefined_type,
                                                  name=asset.name or asset.id)
    if asset.predefined_type == "USERDEFINED" and hasattr(element, "ObjectType"):
        element.ObjectType = asset.brick
    geometry = items(m, asset.solids)
    rep = m.createIfcShapeRepresentation(ctx.body, "Body", representation_type(asset.solids), geometry)
    frame = transform((asset.position[0], asset.position[1], level.elevation + asset.elevation), (0.0, -asset.pitch, asset.rotation))
    finish_element(ctx, element, rep, frame, "Asset", asset.level, item=asset)
    default = next(iter(asset.materials), None)
    for solid, geom in zip(asset.solids, geometry):
        key = solid.material or default
        if key in asset.materials:
            ifcopenshell.api.style.assign_item_style(m, item=geom, style=ctx.brick_styles.get(key, asset.materials[key]))
    if default is not None:
        name = asset.materials[default].name or default.replace("_", " ").title()
        if name not in ctx.materials:
            ctx.materials[name] = ifcopenshell.api.material.add_material(m, name=name)
        ifcopenshell.api.material.assign_material(m, products=[element], material=ctx.materials[name])
    ps = ifcopenshell.api.pset.add_pset(m, product=element, name=BRICK_PSET)
    ifcopenshell.api.pset.edit_pset(m, pset=ps, properties={
        "Brick": asset.brick, "Tags": ", ".join(asset.tags), "Connectors": ", ".join(c.label for c in asset.connectors),
        "Params": json.dumps(asset.params, sort_keys=True),
    })
    if asset.properties:
        ps = ifcopenshell.api.pset.add_pset(m, product=element, name=PROPERTIES_PSET)
        ifcopenshell.api.pset.edit_pset(m, pset=ps, properties=dict(asset.properties))
