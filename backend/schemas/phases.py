"""Construction phases, in build order, and the phase of any IFC element class.

core/construction.py (the live build) and slicer/slice.py (the phase-by-phase slice preview) both
build in PHASES order. An element's phase comes from its IFC class — the most specific entry of
CLASS_PHASES the class inherits from — so a brick of any class, including one a model wrote, falls
into place without saying anything about construction.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, get_args

import ifcopenshell.ifcopenshell_wrapper as ifc_wrapper

Phase = Literal["foundation", "structure", "roof", "plumbing", "mechanical", "spaces", "electrical", "details", "site"]
PHASES: tuple[Phase, ...] = get_args(Phase)

CLASS_PHASES: dict[str, Phase] = {
    "IfcFooting": "foundation", "IfcPile": "foundation", "IfcSlab": "foundation",
    "IfcWall": "structure", "IfcColumn": "structure", "IfcBeam": "structure", "IfcMember": "structure",
    "IfcPlate": "structure", "IfcStair": "structure", "IfcRamp": "structure", "IfcChimney": "structure",
    "IfcTransportElement": "structure",
    "IfcRoof": "roof",
    "IfcFlowSegment": "plumbing", "IfcFlowFitting": "plumbing",
    "IfcEnergyConversionDevice": "mechanical", "IfcFlowMovingDevice": "mechanical",
    "IfcFlowStorageDevice": "mechanical", "IfcFlowTreatmentDevice": "mechanical", "IfcFlowController": "mechanical",
    "IfcSpace": "spaces",
    "IfcOutlet": "electrical", "IfcSwitchingDevice": "electrical", "IfcElectricDistributionBoard": "electrical",
    "IfcCableSegment": "electrical", "IfcDistributionControlElement": "electrical", "IfcElectricFlowStorageDevice": "electrical",
    "IfcGeographicElement": "site", "IfcCivilElement": "site",
}
SCHEMA = ifc_wrapper.schema_by_name("IFC4")


@lru_cache(maxsize=512)
def phase_for(ifc_class: str) -> Phase:
    """The phase of the nearest ancestor (or the class itself) listed in CLASS_PHASES; else details."""
    try:
        decl = SCHEMA.declaration_by_name(ifc_class)
    except (RuntimeError, IndexError):
        return "details"
    while decl is not None:
        if decl.name() in CLASS_PHASES:
            return CLASS_PHASES[decl.name()]
        decl = decl.supertype()
    return "details"
