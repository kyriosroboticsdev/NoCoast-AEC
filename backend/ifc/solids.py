"""Evaluated brick solids (bricks/geometry.py) → IFC geometry items.

Each kind maps to its IFC counterpart, kept parametric where IFC has one: extrusions become
IfcExtrudedAreaSolid (polygon, polygon with holes, circle or hollow circle profiles), revolutions
IfcRevolvedAreaSolid about the local z axis, pipes IfcSweptDiskSolid, meshes IfcPolygonalFaceSet.
Cuts become IfcBooleanResult DIFFERENCE chains. Items are styled one by one, so a single element can
carry several materials.
"""

from __future__ import annotations

from typing import assert_never

import ifcopenshell
import ifcopenshell.api.style
import numpy as np

from bricks.geometry import CircleProfile, Extrusion, MeshSolid, Pipe, PolygonProfile, Revolution
from bricks.model import Material


def _f(v) -> float:
    return float(round(float(v), 6))


def _pt2(m, p):
    return m.createIfcCartesianPoint((_f(p[0]), _f(p[1])))


def _pt3(m, p):
    return m.createIfcCartesianPoint((_f(p[0]), _f(p[1]), _f(p[2])))


def _dir(m, v):
    return m.createIfcDirection(tuple(_f(c) for c in v))


def _ring(m, pts):
    ifc = [_pt2(m, p) for p in pts]
    return m.createIfcPolyline(ifc + [ifc[0]])


def _position(m, matrix: np.ndarray):
    return m.createIfcAxis2Placement3D(_pt3(m, matrix[:3, 3]), _dir(m, matrix[:3, 2]), _dir(m, matrix[:3, 0]))


def profile(m, p: PolygonProfile | CircleProfile):
    match p:
        case PolygonProfile(outer=outer, holes=holes) if holes:
            return m.createIfcArbitraryProfileDefWithVoids("AREA", None, _ring(m, outer), [_ring(m, h) for h in holes])
        case PolygonProfile(outer=outer):
            return m.createIfcArbitraryClosedProfileDef("AREA", None, _ring(m, outer))
        case CircleProfile(center=c, radius=r, inner=inner):
            at = m.createIfcAxis2Placement2D(_pt2(m, c), None)
            if inner:
                return m.createIfcCircleHollowProfileDef("AREA", None, at, _f(r), _f(r - inner))
            return m.createIfcCircleProfileDef("AREA", None, at, _f(r))
    raise TypeError(f"unknown profile {p!r}")


def item(m, solid):
    """One IFC geometry item for a solid, its cuts subtracted."""
    base = _plain(m, solid)
    for cut in solid.cuts:
        base = m.createIfcBooleanResult("DIFFERENCE", base, _plain(m, cut))
    return base


def _plain(m, solid):
    mat = solid.m
    match solid:
        case Extrusion():
            return m.createIfcExtrudedAreaSolid(profile(m, solid.profile), _position(m, mat), _dir(m, (0, 0, 1)), _f(solid.height))
        case Revolution():
            # The profile is drawn in (r, z): its plane's x is the solid's x, its y the solid's z.
            plane = mat @ np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float)
            axis = m.createIfcAxis1Placement(_pt3(m, (0, 0, 0)), _dir(m, (0, 1, 0)))
            return m.createIfcRevolvedAreaSolid(profile(m, solid.profile), _position(m, plane), axis, _f(solid.angle))
        case Pipe():
            pts = [_pt3(m, mat[:3, :3] @ p + mat[:3, 3]) for p in solid.path]
            return m.createIfcSweptDiskSolid(m.createIfcPolyline(pts), _f(solid.radius), _f(solid.inner) if solid.inner else None, None, None)
        case MeshSolid():
            verts = [tuple(_f(c) for c in mat[:3, :3] @ v + mat[:3, 3]) for v in solid.vertices]
            faces = [m.createIfcIndexedPolygonalFace([i + 1 for i in f]) for f in solid.faces]
            return m.createIfcPolygonalFaceSet(m.createIfcCartesianPointList3D(verts), True, faces, None)
        case _:
            assert_never(solid)


def representation_type(solids: list) -> str:
    if any(s.cuts for s in solids):
        return "CSG" if all(s.cuts for s in solids) else "SolidModel"
    kinds = {s.kind for s in solids}
    if kinds == {"mesh"}:
        return "Tessellation"
    if "mesh" in kinds:
        return "SolidModel"
    return "SweptSolid"


def items(m, solids: list) -> list:
    """Geometry items for a representation of `representation_type(solids)`: in a mixed SolidModel,
    boolean results are wrapped as CSG solids."""
    kind = representation_type(solids)
    out = []
    for s in solids:
        it = item(m, s)
        if kind == "SolidModel" and it.is_a("IfcBooleanResult"):
            it = m.createIfcCsgSolid(it)
        out.append(it)
    return out


class Styles:
    """Surface styles for brick materials, one per distinct colour/opacity/name."""

    def __init__(self, model: ifcopenshell.file):
        self.model = model
        self._cache: dict[tuple, ifcopenshell.entity_instance] = {}

    def get(self, key: str, mat: Material):
        cache_key = (mat.name or key, mat.color, mat.opacity)
        style = self._cache.get(cache_key)
        if style is None:
            style = ifcopenshell.api.style.add_style(self.model, name=mat.name or key)
            r, g, b = mat.color
            ifcopenshell.api.style.add_surface_style(
                self.model, style=style, ifc_class="IfcSurfaceStyleShading",
                attributes={"SurfaceColour": {"Name": None, "Red": r, "Green": g, "Blue": b}, "Transparency": round(1 - mat.opacity, 4)},
            )
            self._cache[cache_key] = style
        return style
