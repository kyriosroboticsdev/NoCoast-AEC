"""Building program — what the LLM decides. Rooms, storeys and features, no coordinates.

The layout solver (solver/layout.py) turns a Program into a BuildingSpec. Keeping
geometry out of this schema is deliberate: language models are good at "three
bedrooms upstairs, kitchen next to the dining room" and bad at making polygons
close. All areas are m².

Small models fill every field they are shown, sometimes with junk (a 0×0 footprint,
a 0 m storey height). Those are coerced to "unspecified" rather than rejected, so
the repair loop is saved for real mistakes.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_STOREYS = 5
_LEVEL = re.compile(r"^\s*(?:l|level\s*)?(\d+)\s*$", re.IGNORECASE)


def level_id(index: int) -> str:
    """0-based storey index → id used everywhere else ("L1" is the ground floor)."""
    return f"L{index + 1}"


class Room(BaseModel):
    name: str = Field(description="Display name, e.g. 'Kitchen' or 'Bedroom 2'")
    level: str = Field("L1", description="Storey id: L1 = ground floor, L2 = the floor above it, and so on")
    area: Optional[float] = Field(None, description="Target floor area in m². null when not specified.")
    kind: Literal["living", "kitchen", "dining", "office", "bedroom", "bathroom", "hall", "garage", "other"] = "other"

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v):
        if isinstance(v, bool):
            raise ValueError("level must be a storey id like 'L2'")
        if isinstance(v, int):  # the schema says "L2"; a bare number is read as 1-based
            v = f"L{v}"
        m = _LEVEL.match(str(v))
        if not m or int(m.group(1)) < 1:
            raise ValueError(f"level must be a storey id like 'L1' or 'L2', got {v!r}")
        return f"L{int(m.group(1))}"

    @field_validator("area", mode="before")
    @classmethod
    def _area(cls, v):
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None

    @property
    def index(self) -> int:
        return int(self.level[1:]) - 1


class Program(BaseModel):
    name: str = Field("Generated Building", description="Building name")
    description: Optional[str] = Field(None, description="One sentence describing the design intent")
    storeys: int = Field(1, ge=1, le=MAX_STOREYS)
    storey_height: float = Field(3.0, description="Floor-to-floor height in metres (2–6); 3.0 when unspecified")
    rooms: list[Room] = Field(min_length=1)
    footprint: Optional[tuple[float, float]] = Field(
        None, description="Overall [width, depth] of the main block in metres, both ≥ 3. null to size it from the rooms."
    )
    garage: bool = Field(False, description="Attached single garage on the east side")
    porch: bool = Field(False, description="Front porch with columns on the south side")
    bright: bool = Field(False, description="Larger windows for natural light")
    roof: Literal["flat"] = Field("flat", description="Only flat roofs are supported so far")
    notes: list[str] = Field(default_factory=list, description="How the prompt was interpreted, for the user")

    @model_validator(mode="before")
    @classmethod
    def _coerce_junk(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        fp = data.get("footprint")
        if fp is not None:
            ok = isinstance(fp, (list, tuple)) and len(fp) == 2 and all(isinstance(x, (int, float)) and x >= 3 for x in fp)
            if not ok:
                data["footprint"] = None
        h = data.get("storey_height")
        if h is not None and not (isinstance(h, (int, float)) and 2 <= h <= 6):
            data["storey_height"] = 3.0
        if isinstance(data.get("storeys"), (int, float)) and data["storeys"] < 1:
            data["storeys"] = 1
        if data.get("name") in (None, ""):
            data["name"] = "Generated Building"
        return data

    @model_validator(mode="after")
    def _check(self) -> "Program":
        errors = []
        for room in self.rooms:
            if room.index >= self.storeys:
                errors.append(f"room '{room.name}' is on {room.level} but the building has only {self.storeys} storey(s) "
                              f"(L1..{level_id(self.storeys - 1)}); raise `storeys` or move the room")
        names = [r.name for r in self.rooms]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            errors.append(f"duplicate room names: {dupes} (number them: 'Bedroom 1', 'Bedroom 2')")
        if errors:
            raise ValueError("; ".join(errors))
        return self
