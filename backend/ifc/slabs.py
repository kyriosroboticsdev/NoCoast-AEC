"""IfcSlab (floors), IfcSpace (rooms) and IfcColumn — all simple extrusions."""

from __future__ import annotations

import ifcopenshell.api.aggregate
import ifcopenshell.api.geometry
import ifcopenshell.api.root

from ifc.project import BuildContext, finish_element, translate
from schemas.bim import Column, Slab, Space


def add_slab(ctx: BuildContext, slab: Slab) -> None:
    level = ctx.level(slab.level)
    element = ifcopenshell.api.root.create_entity(ctx.model, ifc_class="IfcSlab", predefined_type="FLOOR", name=slab.name or slab.id)
    rep = ifcopenshell.api.geometry.add_slab_representation(
        ctx.model, context=ctx.body, depth=slab.thickness, polyline=list(slab.outline)
    )
    # Top of the slab sits at the storey elevation.
    finish_element(ctx, element, rep, translate(z=level.elevation + slab.elevation - slab.thickness), "Slab", slab.level,
                   pset=("Pset_SlabCommon", {"IsExternal": False}), item=slab)
    ctx.slabs[slab.id] = element


def add_space(ctx: BuildContext, space: Space) -> None:
    level = ctx.level(space.level)
    # IFC convention: Name is the room number/id, LongName the human-readable room name.
    element = ifcopenshell.api.root.create_entity(ctx.model, ifc_class="IfcSpace", name=space.id)
    element.LongName = space.name or space.id
    rep = ifcopenshell.api.geometry.add_slab_representation(
        ctx.model, context=ctx.body, depth=space.height or level.height, polyline=list(space.outline)
    )
    finish_element(ctx, element, rep, translate(z=level.elevation), "Space", item=space)
    # Spaces are decomposed from the storey rather than contained in it.
    ifcopenshell.api.aggregate.assign_object(ctx.model, products=[element], relating_object=ctx.storeys[space.level])


def add_column(ctx: BuildContext, column: Column) -> None:
    level = ctx.level(column.level)
    element = ifcopenshell.api.root.create_entity(ctx.model, ifc_class="IfcColumn", name=column.name or column.id)
    rep = ifcopenshell.api.geometry.add_wall_representation(
        ctx.model, context=ctx.body, length=column.width, height=column.height or level.height,
        thickness=column.depth, offset=-column.depth / 2,
    )
    x, y = column.position
    finish_element(ctx, element, rep, translate(x - column.width / 2, y, level.elevation + column.elevation), "Column", column.level, item=column)
