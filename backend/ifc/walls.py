"""IfcWall: straight walls extruded from a rectangle centred on the start→end axis, and faceted
(curved) walls extruded from the buffered chord polyline."""

from __future__ import annotations

import math

import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
from shapely.geometry import LineString

from ifc.geometry import body, extrude
from ifc.project import BuildContext, finish_element, placement
from schemas.bim import Wall


def wall_matrix(ctx: BuildContext, wall: Wall, at: float | None = None):
    """Local frame: origin on the wall axis (`at` metres from the start, default the start), +X along
    the wall there, +Y across it, z at the storey. Straight walls have one frame; a faceted wall's frame
    follows the chord under `at`, which is what an opening cut into it needs."""
    if wall.path and at is not None:
        (x, y), angle = wall.frame_at(at)
    elif wall.path:
        (x, y), angle = wall.frame_at(0.0)
    else:
        x, y = wall.start
        angle = math.atan2(wall.end[1] - wall.start[1], wall.end[0] - wall.start[0])
        if at:
            x, y = x + math.cos(angle) * at, y + math.sin(angle) * at
    return placement(x, y, ctx.level(wall.level).elevation + wall.elevation, angle)


def add_wall(ctx: BuildContext, wall: Wall) -> None:
    height = wall.height or ctx.level(wall.level).height
    element = ifcopenshell.api.root.create_entity(ctx.model, ifc_class="IfcWall", name=wall.name or wall.id)
    if wall.path:
        # One solid: the chord polyline buffered by half the thickness (flat ends, mitred joints).
        profile = LineString(wall.path).buffer(wall.thickness / 2, cap_style="flat", join_style="mitre")
        pts = [(round(x, 4), round(y, 4)) for x, y in profile.exterior.coords[:-1]]
        rep = body(ctx, [extrude(ctx.model, pts, height)])
        matrix = placement(0, 0, ctx.level(wall.level).elevation + wall.elevation, 0)
    else:
        rep = ifcopenshell.api.geometry.add_wall_representation(
            ctx.model, context=ctx.body, length=wall.length, height=height,
            thickness=wall.thickness, offset=-wall.thickness / 2,
        )
        matrix = wall_matrix(ctx, wall)
    style = f"Wall:{wall.material}" if wall.material else "Wall"
    props = {"IsExternal": wall.external, "LoadBearing": wall.external}
    finish_element(ctx, element, rep, matrix, style, wall.level, pset=("Pset_WallCommon", props), item=wall)
    if wall.radius:
        ifcopenshell.api.pset.edit_pset(ctx.model, pset=ifcopenshell.api.pset.add_pset(ctx.model, product=element, name="NoCoast_Curve"),
                                        properties={"Radius": float(wall.radius), "Facets": len(wall.path) - 1})
    ctx.walls[wall.id] = element
