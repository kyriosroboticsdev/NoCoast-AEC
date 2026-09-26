"""IfcStair: a straight flight as a sawtooth profile extruded across its width, plus the
opening it needs in the floor slab of the level it arrives at."""

from __future__ import annotations

import math

import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.root

from core.guids import key_for_opening
from ifc.geometry import body, extrude, profile_along_x
from ifc.project import BuildContext, finish_element, placement, translate
from schemas.bim import Slab, Stair

WELL_START = 0.3  # fraction of the run after which the floor above is cut away


def flight_profile(stair: Stair, rise: float) -> list[tuple[float, float]]:
    n = stair.steps(rise)
    r, g = rise / n, stair.going
    pts: list[tuple[float, float]] = [(0.0, 0.0)]
    for i in range(n):
        pts.append((i * g, (i + 1) * r))
        pts.append(((i + 1) * g, (i + 1) * r))
    run = n * g
    pts.append((run, rise - min(0.25, rise / 2)))  # underside, kept below the step corners
    pts.append((min(0.25, run / 4), 0.0))
    return pts


def footprint(stair: Stair, rise: float) -> list[tuple[float, float]]:
    """Plan rectangle of the flight in world coordinates."""
    run = stair.run(rise)
    a = math.radians(stair.direction)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy * stair.width / 2, dx * stair.width / 2
    x, y = stair.position
    return [(x + nx, y + ny), (x + run * dx + nx, y + run * dy + ny), (x + run * dx - nx, y + run * dy - ny), (x - nx, y - ny)]


def well(stair: Stair, rise: float, margin: float = 0.05) -> list[tuple[float, float]]:
    """Plan rectangle of the slab opening above the upper part of the flight."""
    run = stair.run(rise)
    a = math.radians(stair.direction)
    dx, dy = math.cos(a), math.sin(a)
    half = stair.width / 2 + margin
    nx, ny = -dy * half, dx * half
    x0, y0 = stair.position[0] + run * WELL_START * dx, stair.position[1] + run * WELL_START * dy
    x1, y1 = stair.position[0] + (run + margin) * dx, stair.position[1] + (run + margin) * dy
    return [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]


def add_stair(ctx: BuildContext, stair: Stair) -> None:
    m = ctx.model
    level = ctx.level(stair.level)
    rise = stair.rise or level.height
    element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcStair", predefined_type="STRAIGHT_RUN_STAIR", name=stair.name or stair.id)
    rep = body(ctx, [profile_along_x(m, flight_profile(stair, rise), stair.width / 2, stair.width)])
    frame = placement(stair.position[0], stair.position[1], level.elevation, math.radians(stair.direction))
    finish_element(ctx, element, rep, frame, "Stair", stair.level, pset=("Pset_StairCommon", {"NumberOfRiser": stair.steps(rise), "RiserHeight": rise / stair.steps(rise), "TreadLength": stair.going}), item=stair)


def add_stair_wells(ctx: BuildContext) -> None:
    """Cut each stair's well into the slab(s) of the level it arrives at. Runs after slabs and stairs exist."""
    m = ctx.model
    for stair in [e for e in ctx.spec.elements if isinstance(e, Stair) and e.to_level]:
        level = ctx.level(stair.level)
        rise = stair.rise or level.height
        hole = well(stair, rise)
        cx, cy = sum(p[0] for p in hole) / 4, sum(p[1] for p in hole) / 4
        for slab in [e for e in ctx.spec.elements if isinstance(e, Slab) and e.level == stair.to_level]:
            if not _inside(slab.outline, (cx, cy)):
                continue
            upper = ctx.level(slab.level)
            opening = ifcopenshell.api.root.create_entity(m, ifc_class="IfcOpeningElement", name=f"{stair.id} well")
            opening.GlobalId = ctx.guids[key_for_opening(stair.id)]
            solid = extrude(m, hole, slab.thickness + 0.2, origin=(0, 0, upper.elevation - slab.thickness - 0.1))
            ifcopenshell.api.geometry.edit_object_placement(m, product=opening, matrix=translate())
            ifcopenshell.api.geometry.assign_representation(m, product=opening, representation=body(ctx, [solid]))
            ifcopenshell.api.feature.add_feature(m, feature=opening, element=ctx.slabs[slab.id])


def _inside(outline, p) -> bool:
    x, y = p
    inside = False
    n = len(outline)
    for i in range(n):
        (x0, y0), (x1, y1) = outline[i], outline[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside
