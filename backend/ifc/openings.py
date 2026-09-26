"""IfcDoor / IfcWindow: each cuts an IfcOpeningElement into its host wall and fills it."""

from __future__ import annotations

import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.root

from core.guids import key_for_opening
from ifc.project import BuildContext, finish_element, translate
from ifc.walls import wall_matrix
from schemas.bim import Door, Wall, Window

CLEARANCE = 0.05  # opening box pokes out of both wall faces so the boolean cut is clean


def add_opening(ctx: BuildContext, item: Door | Window) -> None:
    m = ctx.model
    wall: Wall = next(el for el in ctx.spec.elements if isinstance(el, Wall) and el.id == item.wall)
    host = ctx.walls[wall.id]
    level = wall.level
    sill = item.sill_height if isinstance(item, Window) else 0.0
    t = wall.thickness
    frame = wall_matrix(ctx, wall)

    opening = ifcopenshell.api.root.create_entity(m, ifc_class="IfcOpeningElement", name=f"{item.id} opening")
    opening.GlobalId = ctx.guids[key_for_opening(item.id)]
    opening_rep = ifcopenshell.api.geometry.add_wall_representation(
        m, context=ctx.body, length=item.width, height=item.height, thickness=t + 2 * CLEARANCE
    )
    ifcopenshell.api.geometry.edit_object_placement(
        m, product=opening, matrix=frame @ translate(item.offset, -t / 2 - CLEARANCE, sill)
    )
    ifcopenshell.api.geometry.assign_representation(m, product=opening, representation=opening_rep)
    ifcopenshell.api.feature.add_feature(m, feature=opening, element=host)

    if isinstance(item, Door):
        element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcDoor", predefined_type="DOOR", name=item.name or item.id)
        element.OverallWidth, element.OverallHeight = item.width, item.height
        rep = ifcopenshell.api.geometry.add_door_representation(
            m, context=ctx.body, overall_width=item.width, overall_height=item.height,
            lining_properties={"LiningDepth": t, "LiningThickness": 0.05}, unit_scale=1.0,
        )
        kind, pset = "Door", ("Pset_DoorCommon", {"IsExternal": wall.external})
    else:
        element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcWindow", predefined_type="WINDOW", name=item.name or item.id)
        element.OverallWidth, element.OverallHeight = item.width, item.height
        rep = ifcopenshell.api.geometry.add_window_representation(
            m, context=ctx.body, overall_width=item.width, overall_height=item.height,
            lining_properties={"LiningDepth": t, "LiningThickness": 0.05}, unit_scale=1.0,
        )
        kind, pset = "Window", ("Pset_WindowCommon", {"IsExternal": wall.external})

    finish_element(ctx, element, rep, frame @ translate(item.offset, -t / 2, sill), kind, level, pset=pset, item=item)
    ifcopenshell.api.feature.add_filling(m, opening=opening, element=element)
