"""IfcWall: straight walls, extruded from a rectangle centred on the start→end axis."""

from __future__ import annotations

import math

import ifcopenshell.api.geometry
import ifcopenshell.api.root

from ifc.project import BuildContext, finish_element, placement
from schemas.bim import Wall


def wall_matrix(ctx: BuildContext, wall: Wall):
    """Local frame: origin at wall start, +X along the wall, +Y across it, z at the storey."""
    angle = math.atan2(wall.end[1] - wall.start[1], wall.end[0] - wall.start[0])
    return placement(wall.start[0], wall.start[1], ctx.level(wall.level).elevation, angle)


def add_wall(ctx: BuildContext, wall: Wall) -> None:
    height = wall.height or ctx.level(wall.level).height
    element = ifcopenshell.api.root.create_entity(ctx.model, ifc_class="IfcWall", name=wall.name or wall.id)
    rep = ifcopenshell.api.geometry.add_wall_representation(
        ctx.model, context=ctx.body, length=wall.length, height=height,
        thickness=wall.thickness, offset=-wall.thickness / 2,
    )
    finish_element(
        ctx, element, rep, wall_matrix(ctx, wall), "Wall", wall.level,
        pset=("Pset_WallCommon", {"IsExternal": wall.external, "LoadBearing": wall.external}), item=wall,
    )
    ctx.walls[wall.id] = element
