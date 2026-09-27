"""Tessellate a compiled model once and cache the facts the checker asks about.

One pass with the geometry iterator. Everything after that — counts, extents, whether
a deck is sitting on its piers — is arithmetic on these records, never another read of
the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ifcopenshell
import ifcopenshell.geom
import numpy as np
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import unary_union

from ifc.schema import supertypes


@dataclass
class ElementFact:
    id: str
    name: str
    ifc: str
    supertypes: tuple[str, ...]
    predefined: str | None
    level: str | None
    material: str | None
    bbox: tuple[float, float, float, float, float, float]  # xmin, ymin, zmin, xmax, ymax, zmax
    volume: float
    area: float
    footprint: object
    centroid: tuple[float, float, float]
    facets: int
    normals: int
    curved: bool
    openings: int

    @property
    def zmin(self) -> float:
        return self.bbox[2]

    @property
    def zmax(self) -> float:
        return self.bbox[5]

    def dx(self) -> float:
        return self.bbox[3] - self.bbox[0]

    def dy(self) -> float:
        return self.bbox[4] - self.bbox[1]

    def dz(self) -> float:
        return self.bbox[5] - self.bbox[2]


@dataclass
class Facts:
    elements: list[ElementFact] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)

    def storeys(self) -> int:
        return sum(1 for level in self.levels if level.startswith("L"))


def _level_of(product) -> str | None:
    for rel in getattr(product, "ContainedInStructure", None) or []:
        parent = rel.RelatingStructure
        if parent.is_a("IfcBuildingStorey"):
            return parent.Description or parent.Name
    for rel in getattr(product, "Decomposes", None) or []:
        parent = rel.RelatingObject
        if parent.is_a("IfcBuildingStorey"):
            return parent.Description or parent.Name
    return None


def _material_of(product) -> str | None:
    for rel in getattr(product, "HasAssociations", None) or []:
        if not rel.is_a("IfcRelAssociatesMaterial"):
            continue
        mat = rel.RelatingMaterial
        name = getattr(mat, "Name", None)
        if name:
            return str(name)
        for attr in ("Materials", "MaterialLayers"):
            inner = getattr(mat, attr, None) or []
            for item in inner:
                named = getattr(item, "Name", None) or getattr(getattr(item, "Material", None), "Name", None)
                if named:
                    return str(named)
    return None


def _curved(product, normals: int) -> bool:
    rep = product.Representation
    if rep is not None:
        for shape in rep.Representations or []:
            for item in shape.Items or []:
                if item.is_a() in ("IfcRevolvedAreaSolid", "IfcFacetedBrep"):
                    return True
    # A repeated, rotated extrusion (a helical stair) is still only swept solids, but its
    # normals are no longer the six of a prism.
    return normals > 10


def _mesh_facts(verts: np.ndarray, faces: np.ndarray) -> tuple[float, int, int, object, tuple]:
    """Volume, facet count, distinct normals, plan footprint, centroid.

    IfcOpenShell hands back a flat coordinate list and a flat list of vertex indices."""
    if len(faces) < 3 or len(verts) < 9:
        empty = Polygon()
        return 0.0, 0, 0, empty, (0.0, 0.0, 0.0)
    pts = verts.reshape(-1, 3)
    tri = pts[faces.reshape(-1, 3)]
    volume = float(abs(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum()) / 6.0)
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(normals, axis=1)
    ok = length > 1e-9
    unit = normals[ok] / length[ok, None]
    bins = {tuple(np.round(n, 1)) for n in unit}
    flat = np.abs(unit[:, 2]) > 0.35
    polys = []
    for a, b, c in tri[ok][flat]:
        ring = [(float(a[0]), float(a[1])), (float(b[0]), float(b[1])), (float(c[0]), float(c[1]))]
        if abs((ring[1][0] - ring[0][0]) * (ring[2][1] - ring[0][1]) - (ring[2][0] - ring[0][0]) * (ring[1][1] - ring[0][1])) < 1e-8:
            continue
        poly = Polygon(ring)
        if poly.is_valid and poly.area > 1e-6:
            polys.append(poly)
    foot = unary_union(polys) if polys else Polygon()
    if not foot.is_valid:
        foot = foot.buffer(0)
    centroid = tuple(float(v) for v in verts.reshape(-1, 3).mean(axis=0))
    return volume, int(len(tri)), len(bins), foot, centroid


def collect(model: ifcopenshell.file) -> Facts:
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    products = [p for p in model.by_type("IfcProduct") if getattr(p, "Representation", None) and not p.is_a("IfcOpeningElement")]
    meshes: dict[int, tuple] = {}
    if products:
        iterator = ifcopenshell.geom.iterator(settings, model, include=products)
        if iterator.initialize():
            while True:
                shape = iterator.get()
                verts = np.array(shape.geometry.verts, dtype=float)
                faces = np.array(shape.geometry.faces, dtype=int)
                meshes[shape.id] = (verts, faces)
                if not iterator.next():
                    break
    facts = Facts()
    for storey in sorted(model.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0):
        if storey.Description:
            facts.levels.append(storey.Description)
    for product in products:
        verts, faces = meshes.get(product.id(), (np.zeros(0), np.zeros(0, dtype=int)))
        if len(verts):
            volume, facets, normals, foot, centroid = _mesh_facts(verts, faces)
            pts = verts.reshape(-1, 3)
            bbox = (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 2].min()),
                    float(pts[:, 0].max()), float(pts[:, 1].max()), float(pts[:, 2].max()))
        else:
            volume, facets, normals, foot, centroid = 0.0, 0, 0, Polygon(), (0.0, 0.0, 0.0)
            bbox = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        predefined = getattr(product, "PredefinedType", None)
        tag = getattr(product, "Tag", None)
        if product.is_a("IfcSpace"):
            ident, label = str(product.Name or ""), str(product.LongName or product.Name or "")
        else:
            ident, label = str(tag or product.Name or product.GlobalId), str(product.Name or "")
        facts.elements.append(ElementFact(
            id=ident,
            name=label,
            ifc=product.is_a(),
            supertypes=supertypes(product.is_a()),
            predefined=str(predefined) if predefined else None,
            level=_level_of(product),
            material=_material_of(product),
            bbox=bbox,
            volume=volume,
            area=float(foot.area) if foot is not None else 0.0,
            footprint=foot,
            centroid=centroid,
            facets=facets,
            normals=normals,
            curved=_curved(product, normals),
            openings=len(getattr(product, "HasOpenings", None) or []),
        ))
    return facts


def select(facts: Facts, *, ifc: str | None = None, name: str | None = None, level: str | None = None,
           id: str | None = None) -> list[ElementFact]:
    """Elements matching a selector. An entity name matches itself and its subtypes."""
    out = facts.elements
    if ifc:
        root = ifc if ifc.startswith("Ifc") else "Ifc" + ifc
        out = [e for e in out if root in e.supertypes or e.ifc.lower() == root.lower()]
    if name:
        key = name.lower()
        out = [e for e in out if key in e.name.lower() or key in e.id.lower() or (e.predefined and key in e.predefined.lower())]
    if level:
        out = [e for e in out if e.level == level]
    if id:
        out = [e for e in out if e.id == id]
    return out


def union_bbox(elements: list[ElementFact]) -> tuple[float, float, float, float, float, float] | None:
    if not elements:
        return None
    return (min(e.bbox[0] for e in elements), min(e.bbox[1] for e in elements), min(e.bbox[2] for e in elements),
            max(e.bbox[3] for e in elements), max(e.bbox[4] for e in elements), max(e.bbox[5] for e in elements))


def union_footprint(elements: list[ElementFact]):
    polys = [e.footprint for e in elements if e.footprint is not None and not e.footprint.is_empty]
    if not polys:
        return MultiPoint([(e.centroid[0], e.centroid[1]) for e in elements]).buffer(0.05) if elements else Polygon()
    merged = unary_union(polys)
    return merged.buffer(0) if not merged.is_valid else merged
