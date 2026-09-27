"""IFC solids for the four operations `schemas/geo.py` defines.

    extrude  -> IfcExtrudedAreaSolid
    revolve  -> IfcRevolvedAreaSolid
    sweep    -> IfcFacetedBrep (faceted here, deliberately)
    mesh     -> IfcFacetedBrep

Profiles become `IfcArbitraryClosedProfileDef`, or `IfcArbitraryProfileDefWithVoids` when the
profile has inner rings.

Sweeps are faceted by us rather than emitted as `IfcFixedReferenceSweptAreaSolid` or
`IfcSweptDiskSolid`. Both of those are valid IFC4 and IfcOpenShell reads them, but the viewer
pins web-ifc 0.0.77 and a faceted brep is the one representation every consumer understands.
The price is a bigger file and no analytic curve; the arc radius is recorded in a pset
instead, the way the old curved-wall code did.

Everything here works in the coordinates of the solid's *part*: `extrude` and `revolve` carry
the solid's own frame as an `IfcAxis2Placement3D`, while a brep has nowhere to put one, so its
vertices are transformed on the way out.
"""

from __future__ import annotations

import math

import ifcopenshell

from schemas.geo import Placement, Profile, Solid
from schemas.geom2d import Pt

Vec3 = tuple[float, float, float]
WORLD_UP: Vec3 = (0.0, 0.0, 1.0)


class SolidError(ValueError):
    """A solid could not be turned into IFC geometry."""


# --- primitives --------------------------------------------------------------

def _p2(m, x: float, y: float):
    return m.createIfcCartesianPoint((float(x), float(y)))


def _p3(m, p: Vec3):
    return m.createIfcCartesianPoint((float(p[0]), float(p[1]), float(p[2])))


def _dir(m, v: Vec3):
    return m.createIfcDirection((float(v[0]), float(v[1]), float(v[2])))


def axis2placement3d(m, place: Placement):
    x, _, z = place.basis()
    return m.createIfcAxis2Placement3D(_p3(m, place.at), _dir(m, z), _dir(m, x))


def _ring(m, pts: list[Pt]):
    ifc_pts = [_p2(m, *p) for p in pts]
    return m.createIfcPolyline(ifc_pts + [ifc_pts[0]])


def profile_def(m, profile: Profile):
    outer, holes = profile.rings()
    closed = m.createIfcArbitraryClosedProfileDef("AREA", None, _ring(m, outer))
    if not holes:
        return closed
    return m.createIfcArbitraryProfileDefWithVoids("AREA", None, _ring(m, outer), [_ring(m, h) for h in holes])


# --- the four operations -----------------------------------------------------

def extruded(m, solid: Solid):
    depth = float(solid.depth or 0.0)
    # IFC wants a positive depth; a negative one is the same solid extruded the other way.
    direction: Vec3 = (0.0, 0.0, 1.0) if depth >= 0 else (0.0, 0.0, -1.0)
    return m.createIfcExtrudedAreaSolid(profile_def(m, solid.profile), axis2placement3d(m, solid.place),
                                        _dir(m, direction), abs(depth))


def revolved(m, solid: Solid):
    # `Angle` is an IfcPlaneAngleMeasure, so it is in whatever the project declares as its
    # plane-angle unit — radians when nothing is declared. We author it in radians and
    # `ifc/project.py` declares the SI radian, rather than relying on a degree conversion unit
    # that not every consumer applies. Get this wrong and a 360 becomes 360 radians: the solid
    # comes out as a ~106 degree wedge, which still tessellates and so passes every check.
    (ax, ay), (dx, dy) = solid.revolve_axis()
    axis = m.createIfcAxis1Placement(_p3(m, (ax, ay, 0.0)), _dir(m, (dx, dy, 0.0)))
    return m.createIfcRevolvedAreaSolid(profile_def(m, solid.profile), axis2placement3d(m, solid.place),
                                        axis, math.radians(float(solid.angle or 360.0)))


def _normalise(v: Vec3) -> Vec3:
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        raise SolidError("a sweep path has a zero-length segment")
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def sweep_frames(path: list[Vec3]) -> list[tuple[Vec3, Vec3, Vec3]]:
    """One (side, up, tangent) frame per path point.

    The tangent at an interior point is the bisector of its two segments, so the cross-section
    stays continuous round a corner. `up` is world up projected across the tangent, not a
    Frenet normal — a curved bridge deck must stay level, not bank into the curve."""
    if len(path) < 2:
        raise SolidError("a sweep path needs at least two points")
    tangents = [_normalise(tuple(b - a for a, b in zip(path[i], path[i + 1]))) for i in range(len(path) - 1)]  # type: ignore[misc]
    frames: list[tuple[Vec3, Vec3, Vec3]] = []
    for i in range(len(path)):
        if i == 0:
            t = tangents[0]
        elif i == len(path) - 1:
            t = tangents[-1]
        else:
            t = _normalise(tuple(a + b for a, b in zip(tangents[i - 1], tangents[i])))  # type: ignore[misc]
        reference = WORLD_UP if abs(t[2]) < 0.99 else (0.0, 1.0, 0.0)
        side = _normalise(_cross(reference, t))
        up = _cross(t, side)
        frames.append((side, up, t))
    return frames


def swept_faces(solid: Solid) -> list[list[Vec3]]:
    """A closed shell for a `sweep`: the cross-section carried along the path.

    Side faces are triangles, because a quad spanning two frames that differ at a kink is not
    planar and `IfcFacetedBrep` faces must be. Caps are single polygons, with the profile's
    inner rings reversed into them as face bounds by the caller."""
    outer, holes = solid.profile.rings()  # type: ignore[union-attr]
    path = list(solid.path or [])
    frames = sweep_frames(path)
    faces: list[list[Vec3]] = []

    def at(i: int, p: Pt) -> Vec3:
        side, up, _ = frames[i]
        base = path[i]
        return (base[0] + p[0] * side[0] + p[1] * up[0],
                base[1] + p[0] * side[1] + p[1] * up[1],
                base[2] + p[0] * side[2] + p[1] * up[2])

    for ring in [outer] + holes:
        n = len(ring)
        for i in range(len(path) - 1):
            for j in range(n):
                a, b = ring[j], ring[(j + 1) % n]
                pa, pb = at(i, a), at(i, b)
                qa, qb = at(i + 1, a), at(i + 1, b)
                # Outward normal of a side face is e x tangent for a counter-clockwise ring,
                # which this winding gives; an inner ring is clockwise, so the same winding
                # points its normal into the void, as a closed shell needs.
                faces.append([pa, pb, qb])
                faces.append([pa, qb, qa])
    return faces


def sweep_caps(solid: Solid) -> tuple[tuple[list[Vec3], list[list[Vec3]]], tuple[list[Vec3], list[list[Vec3]]]]:
    """((start outer loop, start inner loops), (end outer loop, end inner loops)).

    The start cap faces backwards along the path, so its outer loop is reversed."""
    outer, holes = solid.profile.rings()  # type: ignore[union-attr]
    path = list(solid.path or [])
    frames = sweep_frames(path)

    def project(i: int, ring: list[Pt]) -> list[Vec3]:
        side, up, _ = frames[i]
        base = path[i]
        return [(base[0] + p[0] * side[0] + p[1] * up[0],
                 base[1] + p[0] * side[1] + p[1] * up[1],
                 base[2] + p[0] * side[2] + p[1] * up[2]) for p in ring]

    start = (project(0, outer)[::-1], [project(0, h)[::-1] for h in holes])
    end = (project(len(path) - 1, outer), [project(len(path) - 1, h) for h in holes])
    return start, end


def faceted_brep(m, faces: list[list[Vec3]], bounded: list[tuple[list[Vec3], list[list[Vec3]]]] | None = None):
    """Closed shell from simple loops plus, optionally, faces that carry inner bounds."""
    ifc_faces = []
    for loop in faces:
        poly = m.createIfcPolyLoop([_p3(m, p) for p in loop])
        ifc_faces.append(m.createIfcFace([m.createIfcFaceOuterBound(poly, True)]))
    for loop, inner in bounded or []:
        bounds = [m.createIfcFaceOuterBound(m.createIfcPolyLoop([_p3(m, p) for p in loop]), True)]
        for ring in inner:
            bounds.append(m.createIfcFaceBound(m.createIfcPolyLoop([_p3(m, p) for p in ring]), True))
        ifc_faces.append(m.createIfcFace(bounds))
    if len(ifc_faces) < 4:
        raise SolidError("a faceted solid needs at least four faces to close a shell")
    return m.createIfcFacetedBrep(m.createIfcClosedShell(ifc_faces))


# --- dispatch ----------------------------------------------------------------

def build_solid(m, solid: Solid, outer: Placement | None = None):
    """One IFC solid item. `outer` is an extra frame applied on top of the solid's own — that
    is how a repeat copy is placed without touching the authored solid."""
    place = solid.place if outer is None else _compose(outer, solid.place)
    if solid.op == "extrude":
        return extruded(m, solid.model_copy(update={"place": place}))
    if solid.op == "revolve":
        return revolved(m, solid.model_copy(update={"place": place}))
    if solid.op == "sweep":
        moved = solid.model_copy(update={"place": Placement()})
        faces = swept_faces(moved)
        start, end = sweep_caps(moved)
        faces = [[place.apply(p) for p in loop] for loop in faces]
        bounded = [([place.apply(p) for p in loop], [[place.apply(p) for p in ring] for ring in inner])
                   for loop, inner in (start, end)]
        return faceted_brep(m, faces, bounded)
    if solid.op == "mesh":
        return faceted_brep(m, [[place.apply(p) for p in loop] for loop in (solid.faces or [])])
    raise SolidError(f"unknown solid op '{solid.op}'")


def representation_kind(solids: list[Solid]) -> str:
    """The `RepresentationType` for a body holding these solids."""
    ops = {s.op for s in solids}
    if ops <= {"extrude", "revolve"}:
        return "SweptSolid"
    if ops <= {"sweep", "mesh"}:
        return "Brep"
    return "SolidModel"


def _compose(outer: Placement, inner: Placement) -> Placement:
    """`inner` expressed in the frame `outer` sits in. Only used for repeat copies, which are
    rigid plan transforms of upright solids."""
    from schemas.geosteps import _compose as compose_placements

    return compose_placements(outer, inner)


def box_solid(w: float, d: float, h: float, at: Vec3 = (0.0, 0.0, 0.0)) -> Solid:
    """An axis-aligned box centred in plan on `at`, rising `h` from it. Used by the migration
    and by openings, which both need a plain box without going through the step layer."""
    return Solid(op="extrude", place=Placement(at=at), profile=Profile(rect=(w, d)), depth=h)
