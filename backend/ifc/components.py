"""Compile a placed IFC component: copy its products from the uploaded (normalised) file.

The component's products keep their own geometry, materials, styles and property sets
(`ifcopenshell.api.project.append_asset`); only their placement changes. The whole group is moved so
its footprint centre lands on `Component.position` at the level's elevation, rotated about its own
vertical axis.

Identity: the first product carries the component's spec (`NoCoast_Spec`) and its stable GlobalId from
the project's guid map; every other copied element (further top-level products and their aggregated
parts) gets a GlobalId derived deterministically from that one and the source GlobalId, plus a
`NoCoast_ComponentPart` marker the lifter skips. So a component keeps the same ids across versions.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.spatial
import ifcopenshell.guid
import ifcopenshell.util.placement as placement_util

import config
from core.guids import key_for_element
from ifc.project import BuildContext, add_json_pset, add_spec_pset, placement, translate
from schemas.bim import Component

PART_PSET = "NoCoast_ComponentPart"
_CACHE_SIZE = 8

_cache: OrderedDict[tuple[str, float], ifcopenshell.file] = OrderedDict()
_lock = threading.Lock()


class ComponentSourceError(RuntimeError):
    """The uploaded file behind a component cannot be read (deleted, moved or corrupt)."""


def source_path(source: str) -> Path:
    path = (config.OUTPUT_DIR / source).resolve()
    if config.OUTPUT_DIR.resolve() not in path.parents:
        raise ComponentSourceError(f"component source outside the output directory: {source}")
    return path


def _library(source: str) -> ifcopenshell.file:
    """Open the normalised component file, cached (previews recompile many times a second)."""
    path = source_path(source)
    try:
        key = (str(path), path.stat().st_mtime)
    except FileNotFoundError as exc:
        raise ComponentSourceError(f"component file is missing: {source}") from exc
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    lib = ifcopenshell.open(str(path))
    with _lock:
        _cache[key] = lib
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return lib


def derived_guid(base: str, source_guid: str) -> str:
    """A GlobalId that is stable for (component instance, source element) across compiles."""
    return ifcopenshell.guid.compress(hashlib.md5(f"{base}/{source_guid}".encode()).hexdigest())


def add_component(ctx: BuildContext, c: Component) -> None:
    m = ctx.model
    level = ctx.level(c.level)
    lib = _library(c.source)
    ox, oy, oz = c.origin
    # Source coordinates → footprint centre at the local origin → rotate → put on the level.
    frame = (placement(c.position[0], c.position[1], level.elevation, math.radians(c.rotation))
             @ translate(-(ox + c.width / 2), -(oy + c.depth / 2), -oz))
    head_guid = ctx.guids[key_for_element(c.id)]
    before = {e.id() for e in m.by_type("IfcElement")}
    reuse: dict = {}  # shared materials/styles/types are appended once per component
    head = None
    for index, gid in enumerate(c.products):
        try:
            src = lib.by_guid(gid)
        except RuntimeError as exc:
            raise ComponentSourceError(f"component '{c.id}': element {gid} is not in {c.source}") from exc
        src_matrix = placement_util.get_local_placement(src.ObjectPlacement) if src.ObjectPlacement else np.eye(4)
        copied = ifcopenshell.api.project.append_asset(m, library=lib, element=src, reuse_identities=reuse)
        ifcopenshell.api.geometry.edit_object_placement(m, product=copied, matrix=frame @ src_matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(m, products=[copied], relating_structure=ctx.storeys[c.level])
        if head is None:
            head = copied
            copied.GlobalId = head_guid
            copied.Tag = c.id
            add_spec_pset(m, copied, c.model_dump_json())
            ctx.products[c.id] = copied
        else:
            copied.GlobalId = derived_guid(head_guid, gid)
            copied.Tag = f"{c.id}#{index}"
            add_json_pset(m, copied, PART_PSET, c.id)
    # Aggregated parts (a stair's flights, a unit's panels) came along with their parents.
    for el in m.by_type("IfcElement"):
        if el.id() in before or el == head or el.Tag and str(el.Tag).startswith(f"{c.id}#"):
            continue
        source_guid = el.GlobalId
        el.GlobalId = derived_guid(head_guid, source_guid)
        if hasattr(el, "Tag"):
            el.Tag = f"{c.id}#part"
        add_json_pset(m, el, PART_PSET, c.id)
