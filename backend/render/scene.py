"""A compiled IFC as triangles for the renderer: world-space triangles, a colour each, and the element
each belongs to (by its design id where the GUID map knows it, else the IFC GlobalId)."""

from __future__ import annotations

import multiprocessing
from dataclasses import dataclass

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from core.guids import GuidMap

NOT_DRAWN = ("IfcSpace", "IfcOpeningElement", "IfcVirtualElement")
DEFAULT_COLOR = (0.72, 0.72, 0.72)
CLASS_COLORS = {
    "IfcWall": (0.90, 0.88, 0.84), "IfcWallStandardCase": (0.90, 0.88, 0.84), "IfcSlab": (0.78, 0.76, 0.72),
    "IfcRoof": (0.62, 0.36, 0.30), "IfcWindow": (0.62, 0.78, 0.90), "IfcDoor": (0.60, 0.44, 0.30),
    "IfcStair": (0.74, 0.70, 0.64), "IfcColumn": (0.66, 0.66, 0.68), "IfcBeam": (0.62, 0.62, 0.66),
    "IfcRailing": (0.40, 0.40, 0.42), "IfcFurniture": (0.70, 0.56, 0.40), "IfcGeographicElement": (0.40, 0.62, 0.34),
}


@dataclass(frozen=True)
class Item:
    id: str
    ifc_class: str
    name: str
    level: str | None


@dataclass(frozen=True)
class Room:
    """An IfcSpace: not drawn, but its id labels the plan and it can be a camera target."""
    id: str
    bounds: tuple[float, float, float, float, float, float]


@dataclass
class Scene:
    tris: np.ndarray      # (n, 3, 3) world coordinates
    colors: np.ndarray    # (n, 3) in 0..1
    owner: np.ndarray     # (n,) index into items
    items: list[Item]
    rooms: list[Room]
    levels: dict[str, float]   # level id -> floor elevation

    def bounds_of(self, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        if not mask.any():
            return None
        pts = self.tris[mask].reshape(-1, 3)
        return pts.min(0), pts.max(0)

    def find(self, element_id: str) -> tuple[np.ndarray, np.ndarray] | None:
        """World box of an element or room by id (case-insensitive), or None."""
        key = element_id.lower()
        idx = [i for i, it in enumerate(self.items) if it.id.lower() == key]
        if idx:
            return self.bounds_of(np.isin(self.owner, idx))
        room = next((r for r in self.rooms if r.id.lower() == key), None)
        return (np.array(room.bounds[:3]), np.array(room.bounds[3:])) if room else None


def _names(guids: GuidMap) -> dict[str, str]:
    """GlobalId -> design id for elements and levels."""
    out = {}
    for key, guid in guids.items():
        kind, _, ident = key.partition(":")
        if kind in ("element", "level"):
            out[guid] = ident
    return out


def _color(material) -> tuple[float, float, float]:
    d = material.diffuse
    return (d.r(), d.g(), d.b())


def scene_of(model: ifcopenshell.file, guids: GuidMap | None = None, rename: dict[str, str] | None = None) -> Scene:
    """`rename` maps element ids to the ids the caller knows them by (e.g. a space to its room)."""
    rename = rename or {}
    names = {guid: rename.get(ident, ident) for guid, ident in _names(guids or {}).items()}
    levels, level_of_storey = {}, {}
    for storey in model.by_type("IfcBuildingStorey"):
        lid = names.get(storey.GlobalId, storey.Name or storey.GlobalId)
        level_of_storey[storey.id()] = lid
        levels[lid] = float(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[2][3]) if storey.ObjectPlacement else 0.0

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    tris, colors, owner, items, rooms = [], [], [], [], []
    it = ifcopenshell.geom.iterator(settings, model, multiprocessing.cpu_count())
    if it.initialize():
        while True:
            shape = it.get()
            geo = shape.geometry
            verts = np.array(geo.verts, float).reshape(-1, 3)
            faces = np.array(geo.faces, int).reshape(-1, 3)
            product = model.by_guid(shape.guid)
            ident = names.get(shape.guid, product.Name or shape.guid)
            if product.is_a("IfcSpace") and len(verts):
                rooms.append(Room(ident, tuple(float(v) for v in (*verts.min(0), *verts.max(0)))))
            elif len(faces) and not any(product.is_a(c) for c in NOT_DRAWN):
                container = ifcopenshell.util.element.get_container(product)
                items.append(Item(ident, product.is_a(), product.Name or "", level_of_storey.get(container.id()) if container else None))
                mats = [_color(m) for m in geo.materials]
                ids = np.array(geo.material_ids, int) if len(geo.material_ids) == len(faces) else np.full(len(faces), -1)
                fallback = CLASS_COLORS.get(product.is_a(), DEFAULT_COLOR)
                palette = np.array(mats + [fallback], float)
                colors.append(palette[np.where(ids >= 0, ids, len(mats))])
                tris.append(verts[faces])
                owner.append(np.full(len(faces), len(items) - 1))
            if not it.next():
                break
    if not tris:
        return Scene(np.zeros((0, 3, 3)), np.zeros((0, 3)), np.zeros(0, int), [], rooms, levels)
    return Scene(np.concatenate(tris), np.concatenate(colors), np.concatenate(owner), items, rooms, levels)
