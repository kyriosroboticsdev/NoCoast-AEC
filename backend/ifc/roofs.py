"""IfcRoof: flat (extruded outline), gable (chevron profile + gable-end infill) and hip (faceted brep).
Pitched shapes need a rectangular outline; the derive step falls back to flat otherwise."""

from __future__ import annotations

import math

import ifcopenshell.api.geometry
import ifcopenshell.api.root

from ifc.geometry import body, faceted_brep, profile_along_x, profile_along_y
from ifc.project import BuildContext, finish_element, translate
from schemas.bim import Roof

GABLE_END_T = 0.3  # thickness of the triangular wall that closes a gable end


def _rect(outline) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    return min(xs), min(ys), max(xs), max(ys)


def _gable_items(m, roof: Roof):
    x0, y0, x1, y1 = _rect(roof.outline)
    w, d = x1 - x0, y1 - y0
    ridge = roof.ridge or ("x" if w >= d else "y")
    t = roof.thickness / math.cos(math.radians(roof.pitch))  # vertical thickness of the sloped slab
    if ridge == "x":  # profile in the YZ plane, extruded along +x
        half = d / 2
        h = half * math.tan(math.radians(roof.pitch))
        mid = (y0 + y1) / 2
        chevron = [(y0, 0), (mid, h), (y1, 0), (y1, t), (mid, h + t), (y0, t)]
        tri = [(y0, 0), (mid, h), (y1, 0)]
        return [profile_along_y(m, chevron, x0, w),
                profile_along_y(m, tri, x0, GABLE_END_T), profile_along_y(m, tri, x1 - GABLE_END_T, GABLE_END_T)]
    half = w / 2
    h = half * math.tan(math.radians(roof.pitch))
    mid = (x0 + x1) / 2
    chevron = [(x0, 0), (mid, h), (x1, 0), (x1, t), (mid, h + t), (x0, t)]
    tri = [(x0, 0), (mid, h), (x1, 0)]
    return [profile_along_x(m, chevron, y1, d),
            profile_along_x(m, tri, y1, GABLE_END_T), profile_along_x(m, tri, y0 + GABLE_END_T, GABLE_END_T)]


def _hip_brep(m, roof: Roof):
    x0, y0, x1, y1 = _rect(roof.outline)
    w, d = x1 - x0, y1 - y0
    half = min(w, d) / 2
    h = half * math.tan(math.radians(roof.pitch))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if abs(w - d) < 1e-6:  # pyramid
        apex = (cx, cy, h)
        base = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
        faces = [list(reversed(base))]
        for i in range(4):
            faces.append([base[i], base[(i + 1) % 4], apex])
        return faceted_brep(m, faces)
    if w > d:
        r0, r1 = (cx - (w - d) / 2, cy, h), (cx + (w - d) / 2, cy, h)
        a, b, c, e = (x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)
        faces = [[e, c, b, a], [a, b, r1, r0], [b, c, r1], [c, e, r0, r1], [e, a, r0]]
    else:
        r0, r1 = (cx, cy - (d - w) / 2, h), (cx, cy + (d - w) / 2, h)
        a, b, c, e = (x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)
        faces = [[e, c, b, a], [a, b, r0], [b, c, r1, r0], [c, e, r1], [e, a, r0, r1]]
    return faceted_brep(m, faces)


def add_roof(ctx: BuildContext, roof: Roof) -> None:
    level = ctx.level(roof.level)
    m = ctx.model
    if roof.shape == "flat":
        element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcRoof", predefined_type="FLAT_ROOF", name=roof.name or roof.id)
        rep = ifcopenshell.api.geometry.add_slab_representation(m, context=ctx.body, depth=roof.thickness, polyline=list(roof.outline))
        style = "Roof"
    elif roof.shape == "gable":
        element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcRoof", predefined_type="GABLE_ROOF", name=roof.name or roof.id)
        rep = body(ctx, _gable_items(m, roof))
        style = "Roof:pitched"
    else:
        element = ifcopenshell.api.root.create_entity(m, ifc_class="IfcRoof", predefined_type="HIP_ROOF", name=roof.name or roof.id)
        rep = body(ctx, [_hip_brep(m, roof)], "Brep")
        style = "Roof:pitched"
    finish_element(ctx, element, rep, translate(z=level.elevation + level.height + roof.elevation), style, roof.level,
                   pset=("Pset_RoofCommon", {"IsExternal": True}), item=roof)
