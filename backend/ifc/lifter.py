"""IFC → (GeoModel, GuidMap).

A file this compiler wrote carries the whole GeoModel as `NoCoast_Model` on the building and
each part's id as its Tag, so lifting is lossless. A file the previous room-centric compiler
wrote carries `NoCoast_Spec` fragments; those are reassembled into a BuildingSpec and migrated.
"""

from __future__ import annotations

import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element

from core.guids import GuidMap, key_for_assembly, key_for_level, key_for_opening, key_for_part
from ifc.compile import MODEL_PSET, PART_PSET
from schemas.geo import GeoModel

SPEC_PSET = "NoCoast_Spec"  # the room-centric compiler's per-element payload


class LiftError(ValueError):
    pass


def _json_pset(entity, name: str) -> dict | None:
    psets = ifcopenshell.util.element.get_psets(entity)
    payload = psets.get(name, {}).get("Json")
    return json.loads(payload) if payload else None


def _fixed(model, guids: GuidMap) -> None:
    projects, sites, buildings = model.by_type("IfcProject"), model.by_type("IfcSite"), model.by_type("IfcBuilding")
    if len(projects) != 1 or len(sites) != 1 or len(buildings) != 1:
        raise LiftError("expected exactly one IfcProject, IfcSite and IfcBuilding")
    guids["project"] = projects[0].GlobalId
    guids["site"] = sites[0].GlobalId
    guids["building"] = buildings[0].GlobalId


def _from_model_pset(model) -> tuple[GeoModel, GuidMap]:
    guids: GuidMap = {}
    _fixed(model, guids)
    building = model.by_type("IfcBuilding")[0]
    payload = _json_pset(building, MODEL_PSET)
    if payload is None:
        raise LiftError(f"IfcBuilding has no {MODEL_PSET} pset")
    geo = GeoModel.model_validate(payload)
    for storey in model.by_type("IfcBuildingStorey"):
        if storey.Description:
            guids[key_for_level(storey.Description)] = storey.GlobalId
    for product in model.by_type("IfcProduct"):
        tag = getattr(product, "Tag", None)
        if not tag and product.is_a("IfcSpace"):
            tag = product.Name
        if not tag:
            continue
        if product.is_a("IfcOpeningElement"):
            guids[key_for_opening(tag)] = product.GlobalId
        elif product.is_a("IfcElementAssembly"):
            guids[key_for_assembly(tag)] = product.GlobalId
        else:
            guids[key_for_part(tag)] = product.GlobalId
    return geo, guids


def _from_legacy(model) -> tuple[GeoModel, GuidMap]:
    """A room-centric file: reassemble the BuildingSpec, then migrate it."""
    from core.migrate import from_spec
    from schemas.bim import ELEMENT_ORDER, BuildingSpec

    guids: GuidMap = {}
    _fixed(model, guids)
    building = model.by_type("IfcBuilding")[0]
    building_data = _json_pset(building, SPEC_PSET)
    if building_data is None:
        raise LiftError(f"not a NoCoast file: IfcBuilding has no {MODEL_PSET} or {SPEC_PSET} pset")
    levels = []
    for storey in sorted(model.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0):
        data = _json_pset(storey, SPEC_PSET)
        if data is None:
            raise LiftError(f"storey '{storey.Name}' has no {SPEC_PSET} pset")
        levels.append(data)
        guids[key_for_level(data["id"])] = storey.GlobalId
    elements = []
    for product in model.by_type("IfcElement") + model.by_type("IfcSpace"):
        if product.is_a("IfcOpeningElement"):
            continue
        data = _json_pset(product, SPEC_PSET)
        if data is None:
            raise LiftError(f"{product.is_a()} '{product.Name}' has no {SPEC_PSET} pset")
        elements.append(data)
        guids[key_for_element_legacy(data["id"])] = product.GlobalId
    elements.sort(key=lambda e: (ELEMENT_ORDER.get(e.get("type"), 99), e.get("id", "")))
    spec = BuildingSpec.model_validate({"building": building_data, "levels": levels, "elements": elements})
    geo = from_spec(spec)
    # The migrated opening ids differ from the legacy opening keys. Point the new keys at the
    # same GlobalIds so a recompile does not churn them.
    for opening in geo.openings:
        legacy = opening.id.removesuffix("-void").removesuffix("-well")
        old = guids.get(f"opening:{legacy}")
        if old:
            guids[key_for_opening(opening.id)] = old
    return geo, guids


def key_for_element_legacy(element_id: str) -> str:
    return f"element:{element_id}"


def lift(path: str | Path) -> tuple[GeoModel, GuidMap]:
    model = ifcopenshell.open(str(path))
    buildings = model.by_type("IfcBuilding")
    if len(buildings) != 1:
        raise LiftError("expected exactly one IfcBuilding")
    if _json_pset(buildings[0], MODEL_PSET) is not None:
        return _from_model_pset(model)
    return _from_legacy(model)
