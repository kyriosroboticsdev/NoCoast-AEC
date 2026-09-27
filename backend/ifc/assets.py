"""Placed library bricks (schemas.bim.Asset) → IFC: whatever element class the brick names, drawn from
its evaluated parts, with a NoCoast_Brick property set saying which brick it is, its discipline,
construction phase, service ports and parameter values."""

from __future__ import annotations

import json
import math

import ifcopenshell.api.pset
import ifcopenshell.api.root

from ifc.fixtures import part_solids
from ifc.geometry import body
from ifc.project import BuildContext, finish_element, placement
from schemas.bim import Asset

BRICK_PSET = "NoCoast_Brick"


def add_asset(ctx: BuildContext, asset: Asset) -> None:
    m = ctx.model
    level = ctx.level(asset.level)
    element = ifcopenshell.api.root.create_entity(m, ifc_class=asset.ifc_class, predefined_type=asset.predefined_type,
                                                  name=asset.name or asset.id)
    if asset.predefined_type == "USERDEFINED" and hasattr(element, "ObjectType"):
        element.ObjectType = asset.brick
    frame = placement(asset.position[0], asset.position[1], level.elevation + asset.elevation, math.radians(asset.rotation))
    finish_element(ctx, element, body(ctx, part_solids(m, asset.parts)), frame, f"Asset:{asset.finish}", asset.level, item=asset)
    ps = ifcopenshell.api.pset.add_pset(m, product=element, name=BRICK_PSET)
    ifcopenshell.api.pset.edit_pset(m, pset=ps, properties={
        "Brick": asset.brick, "Discipline": asset.discipline, "Phase": asset.phase, "Host": asset.host,
        "Ports": ", ".join(asset.ports), "Params": json.dumps(asset.params, sort_keys=True),
    })
