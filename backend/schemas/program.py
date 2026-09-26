"""Building program — what the LLM decides. Rooms, storeys and features, no coordinates.

The layout solver (solver/layout.py) turns a Program into a BuildingSpec. Keeping
geometry out of this schema is deliberate: language models are good at "three
bedrooms upstairs, kitchen next to the dining room" and bad at making polygons
close. All areas are m².
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

MAX_STOREYS = 5


class Room(BaseModel):
    name: str = Field(description="Display name, e.g. 'Kitchen' or 'Bedroom 2'")
    level: int = Field(0, ge=0, description="0-based storey index; 0 is the ground floor")
    area: Optional[float] = Field(None, gt=0, description="Target floor area in m². Omit for a sensible default.")
    kind: Literal["living", "kitchen", "dining", "office", "bedroom", "bathroom", "hall", "garage", "other"] = "other"


class Program(BaseModel):
    name: str = Field("Generated Building", description="Building name")
    description: Optional[str] = Field(None, description="One sentence describing the design intent")
    storeys: int = Field(1, ge=1, le=MAX_STOREYS)
    storey_height: float = Field(3.0, gt=2.0, le=6.0, description="Floor-to-floor height in metres")
    rooms: list[Room] = Field(min_length=1)
    footprint: Optional[tuple[float, float]] = Field(
        None, description="Overall width × depth of the main block in metres. Omit to size it from the rooms."
    )
    garage: bool = Field(False, description="Attached single garage on the east side")
    porch: bool = Field(False, description="Front porch with columns on the south side")
    bright: bool = Field(False, description="Larger windows for natural light")
    roof: Literal["flat"] = Field("flat", description="Only flat roofs are supported so far")
    notes: list[str] = Field(default_factory=list, description="How the prompt was interpreted, for the user")

    @model_validator(mode="after")
    def _check(self) -> "Program":
        errors = []
        for room in self.rooms:
            if room.level >= self.storeys:
                errors.append(f"room '{room.name}' is on level {room.level} but the building has {self.storeys} storey(s)")
        if self.footprint is not None and (self.footprint[0] < 3 or self.footprint[1] < 3):
            errors.append("footprint must be at least 3 × 3 m")
        names = [r.name for r in self.rooms]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            errors.append(f"duplicate room names: {dupes}")
        if errors:
            raise ValueError("; ".join(errors))
        return self
