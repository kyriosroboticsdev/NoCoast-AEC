"""The vocabulary shared by the brick library (bricks/) and the placed-brick element (schemas.bim.Asset).

`Phase` is also the construction order: core/construction.py and slicer/slice.py build in the order
listed here, so a brick's phase and the build sequence can never drift apart.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

Discipline = Literal["architecture", "interior", "plumbing", "electrical", "hvac", "fire", "structure", "site",
                     "transport", "energy", "data"]
Host = Literal["floor", "wall", "ceiling", "roof", "free", "span", "site", "site_span"]
Phase = Literal["foundation", "structure", "roof", "plumbing", "mechanical", "spaces", "electrical", "details", "site"]
Finish = Literal["wood", "soft", "sanitary", "appliance", "metal", "glass", "concrete", "plant", "water", "stone", "device",
                 "duct", "solar", "fire", "car"]
PortKind = Literal["water_cold", "water_hot", "drain", "power", "data", "air_supply", "air_return", "gas", "fire_water",
                   "flue", "refrigerant", "heating"]

PHASES: tuple[Phase, ...] = get_args(Phase)


class Port(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: PortKind
    direction: Literal["in", "out"] = "in"

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.direction}"
