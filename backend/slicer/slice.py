"""Compiled IFC → horizontal layers, like a 3D-print slicer preview — but sequenced like a real
build: foundation/floors, then structure, then roof, then spaces, then fixtures last (the same
construction order `ifc/builder.py::BUILDERS` compiles in). Within each phase, cuts every matching
product's tessellated mesh with a plane every `layer_height`, keeping the segments where a triangle
crosses it — generic over element type because it works on the same geometry
`ifc/builder.py::check_geometry` already tessellates, no per-element-type slicing rules to keep in
sync with the compiler.

Visualization only (see README §7): no toolpath stitching, feed rates, or extrusion width.
`gcode.py` turns a slice into travel/draw moves for a preview, not a printer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import ifcopenshell
import ifcopenshell.geom

Point3 = tuple[float, float, float]
Segment = tuple[float, float, float, float]  # x1, y1, x2, y2

# Construction phases, in build order — mirrors ifc/builder.py's BUILDERS.
PHASES: list[tuple[str, tuple[str, ...]]] = [
    ("foundation", ("IfcSlab",)),
    ("structure", ("IfcWall", "IfcColumn")),
    ("roof", ("IfcRoof",)),
    ("spaces", ("IfcSpace",)),
    ("details", ("IfcDoor", "IfcWindow")),
]


@dataclass
class LayerSlice:
    phase: str
    z: float
    segments: list[Segment]


def _phase_of(product: ifcopenshell.entity_instance) -> str | None:
    for label, classes in PHASES:
        if any(product.is_a(cls) for cls in classes):
            return label
    return None


def _triangles_by_phase(model: ifcopenshell.file) -> dict[str, list[tuple[Point3, Point3, Point3]]]:
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    buckets: dict[str, list] = {label: [] for label, _ in PHASES}
    for product in model.by_type("IfcProduct"):
        if not product.Representation or product.is_a("IfcOpeningElement"):
            continue
        label = _phase_of(product)
        if label is None:  # not a NoCoast-compiled class (foreign import); not part of any build phase
            continue
        shape = ifcopenshell.geom.create_shape(settings, product)
        verts, faces = shape.geometry.verts, shape.geometry.faces
        tris = buckets[label]
        for i in range(0, len(faces), 3):
            tris.append(tuple(_vertex(verts, faces[i + k]) for k in range(3)))
    return buckets


def _vertex(verts: list[float], index: int) -> Point3:
    return (verts[3 * index], verts[3 * index + 1], verts[3 * index + 2])


def _edge_crossing(p0: Point3, p1: Point3, z: float) -> tuple[float, float] | None:
    z0, z1 = p0[2], p1[2]
    if z0 == z1 or (z0 - z) * (z1 - z) > 0:
        return None
    t = (z - z0) / (z1 - z0)
    return (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))


def _slice_triangles(triangles: list[tuple[Point3, Point3, Point3]], layer_height: float) -> list[tuple[float, list[Segment]]]:
    """One (z, segments) pair per `layer_height` step across this triangle set's own height range.
    Each plane sits mid-layer so it never lands exactly on a face (a flat top, a phase boundary),
    which would otherwise make a triangle's crossing ambiguous."""
    zs = [p[2] for tri in triangles for p in tri]
    zmin, zmax = min(zs), max(zs)
    count = max(1, math.ceil((zmax - zmin) / layer_height))
    out = []
    for i in range(count):
        z = zmin + (i + 0.5) * layer_height
        segments = []
        for a, b, c in triangles:
            pts = [pt for pt in (_edge_crossing(a, b, z), _edge_crossing(b, c, z), _edge_crossing(c, a, z)) if pt]
            if len(pts) == 2:
                segments.append((*pts[0], *pts[1]))
        out.append((z, segments))
    return out


def slice_model(model: ifcopenshell.file, layer_height: float = 0.2) -> list[LayerSlice]:
    """Layers in build order: every foundation slice, then every structural slice, then roof,
    spaces, and details — each phase swept bottom to top over its own height range."""
    buckets = _triangles_by_phase(model)
    layers: list[LayerSlice] = []
    for label, _ in PHASES:
        triangles = buckets[label]
        if not triangles:
            continue
        for z, segments in _slice_triangles(triangles, layer_height):
            layers.append(LayerSlice(phase=label, z=z, segments=segments))
    return layers
