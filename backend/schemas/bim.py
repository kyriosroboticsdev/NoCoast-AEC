"""Structured BIM instructions — the contract between the AI and the IFC builder.

The planner (rule-based today, an LLM later) produces a `BuildingSpec`.
The IFC builder consumes it. Neither side knows how the other works.

All dimensions are metres. Coordinates are plan (x, y); z comes from levels.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

Point = tuple[float, float]


class Building(BaseModel):
    name: str = "Generated Building"
    description: Optional[str] = None


class Level(BaseModel):
    id: str
    name: str
    height: float = Field(3.0, gt=0, description="Floor-to-floor height")
    elevation: Optional[float] = Field(None, description="Omit to stack on the level below")


class _Element(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None


class Wall(_Element):
    type: Literal["wall"] = "wall"
    level: str
    start: Point
    end: Point
    height: Optional[float] = Field(None, gt=0, description="Defaults to the level height")
    thickness: float = Field(0.2, gt=0)
    external: bool = False

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)


class Slab(_Element):
    type: Literal["slab"] = "slab"
    level: str
    outline: list[Point] = Field(min_length=3)
    thickness: float = Field(0.2, gt=0)


class Roof(_Element):
    type: Literal["roof"] = "roof"
    level: str = Field(description="The roof sits on top of this level")
    outline: list[Point] = Field(min_length=3)
    thickness: float = Field(0.3, gt=0)
    shape: Literal["flat"] = "flat"


class Door(_Element):
    type: Literal["door"] = "door"
    wall: str = Field(description="id of the host wall")
    offset: float = Field(ge=0, description="Distance along the wall from its start to the door's near edge")
    width: float = Field(0.9, gt=0)
    height: float = Field(2.1, gt=0)


class Window(_Element):
    type: Literal["window"] = "window"
    wall: str
    offset: float = Field(ge=0)
    width: float = Field(1.2, gt=0)
    height: float = Field(1.2, gt=0)
    sill_height: float = Field(0.9, ge=0)


class Column(_Element):
    type: Literal["column"] = "column"
    level: str
    position: Point
    width: float = Field(0.3, gt=0)
    depth: float = Field(0.3, gt=0)
    height: Optional[float] = Field(None, gt=0)


class Space(_Element):
    type: Literal["space"] = "space"
    level: str
    outline: list[Point] = Field(min_length=3)
    height: Optional[float] = Field(None, gt=0)


Element = Annotated[
    Union[Wall, Slab, Roof, Door, Window, Column, Space],
    Field(discriminator="type"),
]


def polygon_area(outline: list[Point]) -> float:
    n = len(outline)
    return abs(sum(outline[i][0] * outline[(i + 1) % n][1] - outline[(i + 1) % n][0] * outline[i][1] for i in range(n))) / 2


class BuildingSpec(BaseModel):
    building: Building = Building()
    levels: list[Level] = Field(min_length=1)
    elements: list[Element] = []

    @model_validator(mode="after")
    def _check(self) -> "BuildingSpec":
        errors: list[str] = []

        # Stack levels that have no explicit elevation.
        z = 0.0
        for level in self.levels:
            if level.elevation is None:
                level.elevation = z
            z = level.elevation + level.height

        level_ids = [l.id for l in self.levels]
        if len(set(level_ids)) != len(level_ids):
            errors.append("level ids must be unique")
        levels = {l.id: l for l in self.levels}

        # Give every element a stable id so openings and edits can refer to it.
        counters: dict[str, int] = {}
        for el in self.elements:
            if not el.id:
                counters[el.type] = counters.get(el.type, 0) + 1
                el.id = f"{el.type}-{counters[el.type]}"
        ids = [el.id for el in self.elements]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            errors.append(f"duplicate element ids: {sorted(dupes)}")

        walls = {el.id: el for el in self.elements if isinstance(el, Wall)}
        for el in self.elements:
            where = f"{el.type} '{el.id}'"
            if hasattr(el, "level") and el.level not in levels:
                errors.append(f"{where}: unknown level '{el.level}'")
            if isinstance(el, Wall) and el.length < 0.05:
                errors.append(f"{where}: wall is too short ({el.length:.3f} m)")
            if isinstance(el, (Slab, Roof, Space)) and polygon_area(el.outline) < 0.01:
                errors.append(f"{where}: outline has no area")
            if isinstance(el, (Door, Window)):
                wall = walls.get(el.wall)
                if wall is None:
                    errors.append(f"{where}: unknown host wall '{el.wall}'")
                    continue
                if el.offset + el.width > wall.length + 1e-6:
                    errors.append(f"{where}: runs past the end of wall '{wall.id}' ({el.offset + el.width:.2f} > {wall.length:.2f} m)")
                wall_h = wall.height or (levels[wall.level].height if wall.level in levels else 0)
                top = el.height + (el.sill_height if isinstance(el, Window) else 0)
                if wall_h and top > wall_h + 1e-6:
                    errors.append(f"{where}: top ({top:.2f} m) is above wall '{wall.id}' ({wall_h:.2f} m)")

        if errors:
            raise ValueError("; ".join(errors))
        return self
