"""Low-level solids for the builders that IfcOpenShell's high-level API does not cover:
boxes, arbitrary extruded profiles in any plane, and faceted breps."""

from __future__ import annotations

import math

import ifcopenshell

from schemas.bim import Point


def _pt2(m, x: float, y: float):
    return m.createIfcCartesianPoint((float(x), float(y)))


def _pt3(m, x: float, y: float, z: float):
    return m.createIfcCartesianPoint((float(x), float(y), float(z)))


def _dir(m, x: float, y: float, z: float):
    return m.createIfcDirection((float(x), float(y), float(z)))


def placement3d(m, origin=(0, 0, 0), axis=(0, 0, 1), ref=(1, 0, 0)):
    return m.createIfcAxis2Placement3D(_pt3(m, *origin), _dir(m, *axis), _dir(m, *ref))


def polygon_profile(m, points: list[Point]):
    pts = [_pt2(m, *p) for p in points]
    pts.append(pts[0])
    return m.createIfcArbitraryClosedProfileDef("AREA", None, m.createIfcPolyline(pts))


def extrude(m, points: list[Point], depth: float, origin=(0, 0, 0), axis=(0, 0, 1), ref=(1, 0, 0)):
    """Extrude a closed polygon (in the profile plane) by `depth` along the plane normal `axis`.
    The profile plane's X is `ref`; its Y is axis × ref."""
    return m.createIfcExtrudedAreaSolid(polygon_profile(m, points), placement3d(m, origin, axis, ref), _dir(m, 0, 0, 1), float(depth))


def box(m, x: float, y: float, z: float, w: float, d: float, h: float):
    """Axis-aligned box whose min corner is (x, y, z)."""
    return extrude(m, [(x, y), (x + w, y), (x + w, y + d), (x, y + d)], h, origin=(0, 0, z))


def oriented_box(m, start: Point, end: Point, thickness: float, z: float, h: float):
    """Box of `thickness` centred on the start→end segment, from z up by h."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    nx, ny = -dy / length * thickness / 2, dx / length * thickness / 2
    pts = [(start[0] + nx, start[1] + ny), (end[0] + nx, end[1] + ny), (end[0] - nx, end[1] - ny), (start[0] - nx, start[1] - ny)]
    return extrude(m, pts, h, origin=(0, 0, z))


def profile_along_x(m, points_xz: list[Point], y_front: float, width: float):
    """A profile drawn in the XZ plane (x along, z up), extruded across the Y axis from
    `y_front` towards -y by `width`. Used for stairs and gables whose ridge runs along y."""
    # axis=(0,-1,0), ref=(1,0,0) → profile Y = axis × ref = +Z, extrusion towards -Y.
    return extrude(m, points_xz, width, origin=(0, y_front, 0), axis=(0, -1, 0), ref=(1, 0, 0))


def profile_along_y(m, points_yz: list[Point], x_start: float, length: float):
    """A profile drawn in the YZ plane (y along, z up), extruded along +X from `x_start`."""
    # axis=(1,0,0), ref=(0,1,0) → profile Y = +Z, extrusion along +X.
    return extrude(m, points_yz, length, origin=(x_start, 0, 0), axis=(1, 0, 0), ref=(0, 1, 0))


def faceted_brep(m, faces: list[list[tuple[float, float, float]]]):
    """Closed shell from a list of planar faces (outward-facing vertex loops)."""
    ifc_faces = []
    for loop in faces:
        poly = m.createIfcPolyLoop([_pt3(m, *p) for p in loop])
        ifc_faces.append(m.createIfcFace([m.createIfcFaceOuterBound(poly, True)]))
    return m.createIfcFacetedBrep(m.createIfcClosedShell(ifc_faces))


def body(ctx, items: list, kind: str = "SweptSolid"):
    """One Body representation holding several solids."""
    return ctx.model.createIfcShapeRepresentation(ctx.body, "Body", kind, items)
