"""Structured BIM instructions — the contract between the design layer and the IFC builder.

`core/derive.py` produces a `BuildingSpec` from a semantic `Design`; the IFC builder
consumes it. Neither side knows how the other works, and raw ops (core/ops.py) can
still edit a spec element by element.

All dimensions are metres. Coordinates are plan (x east, y north); z comes from levels.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from bricks.geometry import Bounds, Solid
from bricks.model import Connector, Material, PropertyValue

Point = tuple[float, float]

WallMaterial = Literal["masonry", "concrete", "timber", "plaster", "stone", "glass", "brick", "steel", "render"]
RoofShape = Literal["flat", "gable", "hip", "shed"]
FixtureKind = Literal[
    # domestic
    "bed", "double_bed", "bunk_bed", "sofa", "armchair", "coffee_table", "tv_stand", "dining_table", "chair",
    "desk", "bookshelf", "wardrobe", "dresser", "kitchen_counter", "island", "fridge", "oven", "sink",
    "dishwasher", "washing_machine", "toilet", "shower", "bathtub", "washbasin", "fireplace", "car",
    # workplace and education
    "conference_table", "reception_desk", "filing_cabinet", "locker", "whiteboard", "lectern", "printer",
    "server_rack", "school_desk",
    # retail and hospitality
    "shelving_unit", "display_case", "checkout_counter", "cafe_table", "stool", "bar_counter",
    # health
    "hospital_bed", "exam_table",
    # industry and logistics
    "pallet_rack", "workbench", "machine", "crate", "conveyor",
    # sport and assembly
    "treadmill", "weight_bench", "seating_row",
    # plant, site and landscape (these may also stand outside any room)
    "solar_panel", "water_tank", "hvac_unit", "boiler", "bench", "planter", "bollard", "bicycle_rack",
    "lamp_post", "picnic_table", "dumpster",
]


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
    """A wall centred on its axis: straight from `start` to `end`, or faceted along `path` (a curved
    wall is one wall whose path is the chord polyline; `start`/`end` are then its first/last point)."""

    type: Literal["wall"] = "wall"
    level: str
    start: Point
    end: Point
    path: Optional[list[Point]] = Field(None, min_length=2, description="Polyline axis for faceted (curved) walls")
    height: Optional[float] = Field(None, gt=0, description="Defaults to the level height")
    elevation: float = Field(0.0, ge=0, description="Offset above the level (a bridge deck on piers)")
    thickness: float = Field(0.2, gt=0)
    external: bool = False
    material: Optional[WallMaterial] = None
    radius: Optional[float] = Field(None, gt=0, description="True radius of a curved wall, kept for information")

    @model_validator(mode="after")
    def _ends(self) -> "Wall":
        if self.path:
            if len(self.path) == 2:
                self.start, self.end, self.path = self.path[0], self.path[1], None
            else:
                self.start, self.end = self.path[0], self.path[-1]
        return self

    @property
    def axis(self) -> list[Point]:
        return list(self.path) if self.path else [self.start, self.end]

    @property
    def length(self) -> float:
        pts = self.axis
        return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))

    def frame_at(self, offset: float) -> tuple[Point, float]:
        """Point on the axis `offset` metres from the start, and the axis direction there (radians)."""
        pts = self.axis
        left = max(0.0, offset)
        for a, b in zip(pts, pts[1:]):
            seg = math.dist(a, b)
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            if left <= seg or (a, b) == (pts[-2], pts[-1]):
                k = 0.0 if seg == 0 else min(left, seg) / seg
                return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k), angle
            left -= seg
        return pts[0], 0.0


class Slab(_Element):
    type: Literal["slab"] = "slab"
    level: str
    outline: list[Point] = Field(min_length=3)
    thickness: float = Field(0.2, gt=0)
    elevation: float = Field(0.0, ge=0, description="Offset above the level (a bridge deck on piers)")


class Roof(_Element):
    type: Literal["roof"] = "roof"
    level: str = Field(description="The roof sits on top of this level")
    outline: list[Point] = Field(min_length=3)
    thickness: float = Field(0.3, gt=0)
    shape: RoofShape = "flat"
    pitch: float = Field(30.0, ge=5, le=60, description="Degrees; gable/hip only")
    ridge: Optional[Literal["x", "y"]] = Field(None, description="Ridge direction for a gable; default: the long side")
    elevation: float = Field(0.0, ge=0, description="Offset above the level (a bridge deck on piers)")


class Door(_Element):
    type: Literal["door"] = "door"
    wall: str = Field(description="id of the host wall")
    offset: float = Field(ge=0, description="Distance along the wall from its start to the door's near edge")
    width: float = Field(0.9, gt=0)
    height: float = Field(2.1, gt=0)
    kind: Literal["single", "double", "sliding", "french", "garage", "revolving", "roller"] = "single"


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
    elevation: float = Field(0.0, ge=0, description="Offset above the level (a bridge deck on piers)")


class Beam(_Element):
    type: Literal["beam"] = "beam"
    level: str
    start: Point
    end: Point
    width: float = Field(0.2, gt=0)
    depth: float = Field(0.3, gt=0, description="Vertical size; the beam hangs below the top of the level")
    elevation: float = Field(0.0, ge=0, description="Offset above the level (a bridge deck on piers)")


class Space(_Element):
    type: Literal["space"] = "space"
    level: str
    outline: list[Point] = Field(min_length=3)
    height: Optional[float] = Field(None, gt=0)


class Stair(_Element):
    """A straight flight. `position` is the start of the ascent on the flight's centre line."""

    type: Literal["stair"] = "stair"
    level: str
    position: Point
    direction: float = Field(90.0, description="Ascent direction in degrees: 0 = east (+x), 90 = north (+y)")
    width: float = Field(1.0, gt=0)
    rise: Optional[float] = Field(None, gt=0, description="Total rise; defaults to the level height")
    riser: float = Field(0.178, gt=0, description="Maximum riser: the flight takes as many risers as the rise needs at this height or less (IBC 1011.5.2)")
    going: float = Field(0.28, gt=0)
    to_level: Optional[str] = Field(None, description="Level whose floor slab gets the stair opening")

    def steps(self, rise: float) -> int:
        return max(2, math.ceil(rise / self.riser - 1e-6))

    def run(self, rise: float) -> float:
        return self.steps(rise) * self.going


class Fixture(_Element):
    """Furniture, appliances, equipment and site objects as simple solids. `position` is the footprint
    centre; `rotation` (degrees) turns the piece, whose back faces -y before rotation."""

    type: Literal["fixture"] = "fixture"
    level: str
    kind: FixtureKind
    position: Point
    rotation: float = 0.0
    width: float = Field(gt=0)
    depth: float = Field(gt=0)
    height: float = Field(gt=0)
    elevation: float = Field(0.0, ge=0, description="Offset above the level (equipment on a raised deck or a roof)")


class ShapePart(BaseModel):
    """One solid of a CustomFixture, in the fixture's own local frame: `x, y, z` is the part's min
    corner (matching ifc/geometry.py::box), `w`/`d`/`h` its size. A "round" part ignores `d` and is
    a `w`-diameter cylinder instead of a box — for a round table top, a column, a cup."""

    shape: Literal["box", "round"] = "box"
    x: float = 0.0
    y: float = 0.0
    z: float = Field(0.0, ge=0)
    w: float = Field(gt=0, description="width (box) or diameter (round)")
    d: float = Field(0.1, gt=0, description="depth; ignored for a round part")
    h: float = Field(gt=0)


class CustomFixture(_Element):
    """A furniture/fixture piece the model designed itself out of `parts`, instead of picking a
    `Fixture.kind` from the fixed catalog — for shapes the catalog doesn't cover: a round table, an
    L-shaped bench, a custom plinth. `position` is the assembly's bounding-box centre, like Fixture."""

    type: Literal["custom"] = "custom"
    level: str
    position: Point
    rotation: float = 0.0
    parts: list[ShapePart] = Field(min_length=1, max_length=12)
    elevation: float = Field(0.0, ge=0, description="Offset above the level")


class Asset(_Element):
    """A placed brick (bricks/): any IFC element class, drawn from its evaluated solids.

    The solids are in the brick's own frame (its origin at 0, 0, 0); `position` + `elevation` put that
    origin on the level and `rotation` (about z) then `pitch` (raising the local x axis, for paths that
    climb) turn it. `bounds` is the solids' box in the brick's frame, `keepout` the boxes nothing else
    may enter, `path` the start and end it was placed along, if any."""

    type: Literal["asset"] = "asset"
    level: str
    brick: str
    ifc_class: str
    predefined_type: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    ref: Optional[str] = None
    position: Point
    elevation: float = 0.0
    rotation: float = 0.0
    pitch: float = 0.0
    bounds: Bounds
    solids: list[Solid] = Field(min_length=1)
    materials: dict[str, Material] = Field(default_factory=dict)
    params: dict[str, float] = Field(default_factory=dict)
    connectors: list[Connector] = Field(default_factory=list)
    properties: dict[str, PropertyValue] = Field(default_factory=dict)
    keepout: list[Bounds] = Field(default_factory=list)
    collides: bool = True
    path: Optional[tuple[tuple[float, float, float], tuple[float, float, float]]] = None
    note: Optional[str] = None

    @property
    def size(self) -> tuple[float, float, float]:
        x0, y0, z0, x1, y1, z1 = self.bounds
        return (round(x1 - x0, 4), round(y1 - y0, 4), round(z1 - z0, 4))

    @property
    def load_bearing(self) -> bool:
        return bool(self.properties.get("load_bearing"))


class Railing(_Element):
    type: Literal["railing"] = "railing"
    level: str
    path: list[Point] = Field(min_length=2)
    height: float = Field(1.0, gt=0)
    thickness: float = Field(0.05, gt=0)
    elevation: float = Field(0.0, description="Offset above the level (e.g. the top of a balcony slab)")


class Pipe(_Element):
    """A vertical riser — water supply/drain, or the electrical conduit stack — running through the
    building at one plan position. Not a routed network: one stack per system, see core/derive.py."""

    type: Literal["pipe"] = "pipe"
    kind: Literal["water", "electrical"] = "water"
    bottom_level: str = Field(description="Level the riser starts at")
    top_level: str = Field(description="Level the riser rises through to")
    position: Point
    diameter: float = Field(0.06, gt=0)


class Outlet(_Element):
    type: Literal["outlet"] = "outlet"
    level: str
    position: Point
    height: float = Field(0.3, gt=0, description="Mounting height above the floor")


class LightFixture(_Element):
    type: Literal["light"] = "light"
    level: str
    position: Point


class Panel(_Element):
    """The electrical distribution board the building's circuits run from."""

    type: Literal["panel"] = "panel"
    level: str
    position: Point


class Wire(_Element):
    """A branch-circuit run: a polyline at a fixed height above the level (in the ceiling/wall void)."""

    type: Literal["wire"] = "wire"
    level: str
    path: list[Point] = Field(min_length=2)
    elevation: float = Field(2.7, description="Height above the level the run sits at")


Element = Annotated[
    Union[Wall, Slab, Roof, Door, Window, Column, Beam, Space, Stair, Fixture, CustomFixture, Asset, Railing, Pipe,
          Outlet, LightFixture, Panel, Wire],
    Field(discriminator="type"),
]

ELEMENT_ORDER = {"wall": 0, "slab": 1, "space": 2, "column": 3, "beam": 4, "roof": 5, "pipe": 6, "door": 7,
                 "window": 8, "stair": 9, "outlet": 10, "panel": 11, "wire": 12, "fixture": 13, "custom": 13,
                 "asset": 13, "light": 14, "railing": 15}


def polygon_area(outline: list[Point]) -> float:
    n = len(outline)
    return abs(sum(outline[i][0] * outline[(i + 1) % n][1] - outline[(i + 1) % n][0] * outline[i][1] for i in range(n))) / 2


def is_axis_rectangle(outline: list[Point]) -> bool:
    pts = list(outline)
    if len(pts) == 5 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) != 4:
        return False
    xs, ys = {round(p[0], 6) for p in pts}, {round(p[1], 6) for p in pts}
    return len(xs) == 2 and len(ys) == 2


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
            if isinstance(el, (Wall, Beam)) and math.dist(el.start, el.end) < 0.05:
                errors.append(f"{where}: too short ({math.dist(el.start, el.end):.3f} m)")
            if isinstance(el, (Slab, Roof, Space)) and polygon_area(el.outline) < 0.01:
                errors.append(f"{where}: outline has no area")
            if isinstance(el, Roof) and el.shape != "flat" and not is_axis_rectangle(el.outline):
                errors.append(f"{where}: a {el.shape} roof needs a rectangular outline")
            if isinstance(el, Stair) and el.to_level is not None and el.to_level not in levels:
                errors.append(f"{where}: unknown to_level '{el.to_level}'")
            if isinstance(el, (Railing, Wire)) and sum(math.dist(a, b) for a, b in zip(el.path, el.path[1:])) < 0.05:
                errors.append(f"{where}: path has no length")
            if isinstance(el, Pipe):
                for attr in ("bottom_level", "top_level"):
                    if getattr(el, attr) not in levels:
                        errors.append(f"{where}: unknown level '{getattr(el, attr)}'")
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
