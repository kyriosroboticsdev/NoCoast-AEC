"""IFC → (BuildingSpec, Design | None, GuidMap). Lets a saved IFC file be used as context again.

Scope (by design, see README): files produced by this system. Every element,
storey and the building carry a `NoCoast_Spec` pset with the exact spec JSON they
were compiled from, and the building carries the semantic `NoCoast_Design`, so
lifting is lossless and GlobalIds are recovered 1:1. A geometric lifter for foreign
IFC files (reading placements and extrusions back into walls/slabs/openings) is
future work and would plug in here.
"""

from __future__ import annotations

import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element

from core.guids import GuidMap, key_for_element, key_for_level, key_for_opening
from ifc.project import DESIGN_PSET, SPEC_PSET
from schemas.bim import ELEMENT_ORDER, BuildingSpec
from schemas.design import Design


class LiftError(ValueError):
    pass


def _json_pset(entity, name: str) -> dict | None:
    psets = ifcopenshell.util.element.get_psets(entity)
    payload = psets.get(name, {}).get("Json")
    return json.loads(payload) if payload else None


def _is_component_part(product) -> bool:
    """A copied element of an uploaded component other than its head (see ifc/components.py)."""
    return "NoCoast_ComponentPart" in ifcopenshell.util.element.get_psets(product)


def lift(path: str | Path) -> tuple[BuildingSpec, Design | None, GuidMap]:
    model = ifcopenshell.open(str(path))
    projects, sites, buildings = model.by_type("IfcProject"), model.by_type("IfcSite"), model.by_type("IfcBuilding")
    if len(projects) != 1 or len(sites) != 1 or len(buildings) != 1:
        raise LiftError("expected exactly one IfcProject, IfcSite and IfcBuilding")
    building_data = _json_pset(buildings[0], SPEC_PSET)
    if building_data is None:
        raise LiftError(f"not a NoCoast-generated file: IfcBuilding has no {SPEC_PSET} pset")
    design_data = _json_pset(buildings[0], DESIGN_PSET)
    design = Design.model_validate(design_data) if design_data else None

    guids: GuidMap = {"project": projects[0].GlobalId, "site": sites[0].GlobalId, "building": buildings[0].GlobalId}
    levels = []
    for storey in sorted(model.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0):
        data = _json_pset(storey, SPEC_PSET)
        if data is None:
            raise LiftError(f"storey '{storey.Name}' has no {SPEC_PSET} pset")
        levels.append(data)
        guids[key_for_level(data["id"])] = storey.GlobalId

    elements = []
    for product in model.by_type("IfcElement") + model.by_type("IfcSpace"):
        if product.is_a("IfcOpeningElement") or _is_component_part(product):
            continue  # component parts travel with their component (ifc/components.py)
        data = _json_pset(product, SPEC_PSET)
        if data is None:
            raise LiftError(f"{product.is_a()} '{product.Name}' has no {SPEC_PSET} pset")
        elements.append(data)
        guids[key_for_element(data["id"])] = product.GlobalId
        if product.is_a("IfcDoor") or product.is_a("IfcWindow"):
            for rel in product.FillsVoids or []:
                guids[key_for_opening(data["id"])] = rel.RelatingOpeningElement.GlobalId
    for opening in model.by_type("IfcOpeningElement"):  # stair wells: "<stair id> well"
        if opening.Name and opening.Name.endswith(" well"):
            guids[key_for_opening(opening.Name[:-5])] = opening.GlobalId

    # IFC has no element order; make the lifted spec deterministic.
    elements.sort(key=lambda e: (ELEMENT_ORDER.get(e["type"], 99), e["id"]))
    spec = BuildingSpec.model_validate({"building": building_data, "levels": levels, "elements": elements})
    return spec, design, guids
