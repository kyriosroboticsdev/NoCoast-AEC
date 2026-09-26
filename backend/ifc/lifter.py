"""IFC → (BuildingSpec, GuidMap). Lets a saved IFC file be used as LLM context again.

Scope (by design, see README): files produced by this system. Every element,
storey and the building carry a `NoCoast_Spec` pset with the exact spec JSON they
were compiled from, so lifting is lossless and GlobalIds are recovered 1:1. A
geometric lifter for foreign IFC files (reading placements and extrusions back
into walls/slabs/openings) is future work and would plug in here.
"""

from __future__ import annotations

import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element

from core.guids import GuidMap, key_for_element, key_for_level, key_for_opening
from ifc.project import SPEC_PSET
from schemas.bim import BuildingSpec


class LiftError(ValueError):
    pass


def _spec_json(entity) -> dict | None:
    psets = ifcopenshell.util.element.get_psets(entity)
    payload = psets.get(SPEC_PSET, {}).get("Json")
    return json.loads(payload) if payload else None


def lift(path: str | Path) -> tuple[BuildingSpec, GuidMap]:
    model = ifcopenshell.open(str(path))
    projects, sites, buildings = model.by_type("IfcProject"), model.by_type("IfcSite"), model.by_type("IfcBuilding")
    if len(projects) != 1 or len(sites) != 1 or len(buildings) != 1:
        raise LiftError("expected exactly one IfcProject, IfcSite and IfcBuilding")
    building_data = _spec_json(buildings[0])
    if building_data is None:
        raise LiftError(f"not a NoCoast-generated file: IfcBuilding has no {SPEC_PSET} pset")

    guids: GuidMap = {"project": projects[0].GlobalId, "site": sites[0].GlobalId, "building": buildings[0].GlobalId}
    levels = []
    for storey in sorted(model.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0):
        data = _spec_json(storey)
        if data is None:
            raise LiftError(f"storey '{storey.Name}' has no {SPEC_PSET} pset")
        levels.append(data)
        guids[key_for_level(data["id"])] = storey.GlobalId

    elements = []
    for product in model.by_type("IfcElement") + model.by_type("IfcSpace"):
        if product.is_a("IfcOpeningElement"):
            continue
        data = _spec_json(product)
        if data is None:
            raise LiftError(f"{product.is_a()} '{product.Name}' has no {SPEC_PSET} pset")
        elements.append(data)
        guids[key_for_element(data["id"])] = product.GlobalId
        if product.is_a("IfcDoor") or product.is_a("IfcWindow"):
            for rel in product.FillsVoids or []:
                guids[key_for_opening(data["id"])] = rel.RelatingOpeningElement.GlobalId

    # IFC has no element order; make the lifted spec deterministic.
    order = {"wall": 0, "slab": 1, "space": 2, "column": 3, "roof": 4, "door": 5, "window": 6}
    elements.sort(key=lambda e: (order.get(e["type"], 9), e["id"]))
    spec = BuildingSpec.model_validate({"building": building_data, "levels": levels, "elements": elements})
    return spec, guids
