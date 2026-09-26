"""IfcRoof: flat roofs, extruded from the outline and placed on top of their level."""

from __future__ import annotations

import ifcopenshell.api.geometry
import ifcopenshell.api.root

from ifc.project import BuildContext, finish_element, translate
from schemas.bim import Roof


def add_roof(ctx: BuildContext, roof: Roof) -> None:
    level = ctx.level(roof.level)
    element = ifcopenshell.api.root.create_entity(ctx.model, ifc_class="IfcRoof", predefined_type="FLAT_ROOF", name=roof.name or roof.id)
    element.Tag = roof.id
    rep = ifcopenshell.api.geometry.add_slab_representation(
        ctx.model, context=ctx.body, depth=roof.thickness, polyline=list(roof.outline)
    )
    finish_element(ctx, element, rep, translate(z=level.elevation + level.height), "Roof", roof.level,
                   pset=("Pset_RoofCommon", {"IsExternal": True}))
