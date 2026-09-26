"""The semantic design — what the language model builds up, step by step.

A Design says what the building contains and roughly where: storeys, rooms as
rectangles on the plan, doors between rooms, windows on a side of a room, stairs,
furniture, balconies, a porch, the roof kind. It never contains a wall or a
coordinate of an opening: `core/derive.py` derives every wall from the room
rectangles (shared edges become partitions, free edges become exterior walls),
places openings along those walls, and produces the geometric `BuildingSpec`.

Ids are stable handles: a room keeps its id when it moves, so the walls, spaces
and openings derived from it keep their ids and therefore their IFC GlobalIds.
All dimensions are metres; rectangles are [x, y, width, depth] with (x, y) the
south-west corner, x east, y north.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from schemas.bim import FixtureKind, RoofShape, WallMaterial

Side = Literal["N", "S", "E", "W"]
RoomKind = Literal["living", "kitchen", "dining", "office", "bedroom", "bathroom", "hall", "garage", "utility",
                   "storage", "other"]
DoorKind = Literal["single", "double", "sliding", "french", "garage"]
WindowKind = Literal["standard", "large", "floor", "small"]
Rect = tuple[float, float, float, float]

MAX_STOREYS = 40
KIND_WORDS: list[tuple[str, RoomKind]] = [
    (r"living|lounge|family|sitting|great room|salon", "living"), (r"kitchen", "kitchen"), (r"dining|breakfast", "dining"),
    (r"office|study|studio|library", "office"), (r"bed|master|guest|nursery|suite", "bedroom"),
    (r"bath|ensuite|en-suite|wc|toilet|powder|shower", "bathroom"), (r"hall|entry|foyer|corridor|landing|vestibule|lobby", "hall"),
    (r"garage|carport", "garage"), (r"laundry|utility|mud", "utility"), (r"stor|closet|pantry|walk-in", "storage"),
]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "room"


def guess_kind(name: str) -> RoomKind:
    low = name.lower()
    for pattern, kind in KIND_WORDS:
        if re.search(pattern, low):
            return kind
    return "other"


def _round(v: float) -> float:
    return round(float(v), 2)


LEVEL_ID = re.compile(r"^([LB])(\d+)$")


class LevelDef(BaseModel):
    id: str = Field(description="'L1' is the ground floor, 'L2' the storey above it …, 'B1' the first level below ground, 'B2' below that")
    name: Optional[str] = None
    height: float = Field(3.0, ge=2.2, le=12.0, description="Floor-to-floor height in metres")
    below_ground: bool = Field(False, description="Basement level: no windows, no roof; stacks downward from ground")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = str(v).strip().upper()
        if not LEVEL_ID.match(v) or int(v[1:]) < 1:
            raise ValueError(f"level ids look like 'L1', 'L2' … or 'B1', 'B2' for basements; got {v!r}")
        return v

    def model_post_init(self, __context) -> None:
        if self.id.startswith("B"):
            self.below_ground = True

    @property
    def index(self) -> int:
        """0 for the ground floor, positive above, negative below (B1 = -1)."""
        n = int(self.id[1:])
        return -n if self.id.startswith("B") else n - 1

    @property
    def display(self) -> str:
        if self.name:
            return self.name
        if self.index < 0:
            return "Basement" if self.index == -1 else f"Basement {-self.index}"
        return "Ground Floor" if self.index == 0 else f"Level {self.index + 1}"


class RoomDef(BaseModel):
    id: str
    name: str
    level: str = "L1"
    kind: RoomKind = "other"
    rect: Optional[Rect] = Field(None, description="[x, y, width, depth]; null = place it automatically")
    area: Optional[float] = Field(None, gt=0, description="Target m² when rect is null")

    @field_validator("rect")
    @classmethod
    def _rect(cls, v):
        if v is None:
            return None
        x, y, w, d = (_round(c) for c in v)
        if w < 0.8 or d < 0.8:
            raise ValueError(f"room rectangles must be at least 0.8 m in both directions, got {w} x {d}")
        return (x, y, w, d)

    @property
    def box(self) -> tuple[float, float, float, float]:
        x, y, w, d = self.rect  # type: ignore[misc]
        return x, y, _round(x + w), _round(y + d)

    @property
    def area_m2(self) -> float:
        return self.rect[2] * self.rect[3] if self.rect else (self.area or 0.0)


class DoorDef(BaseModel):
    id: str
    room: str
    to: str = Field("outside", description="Other room id, or 'outside'")
    side: Optional[Side] = Field(None, description="Exterior doors: which side of the room; null = pick one")
    at: float = Field(0.5, ge=0, le=1, description="Position along the wall, 0 = start (west/south end)")
    kind: DoorKind = "single"
    width: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)


class WindowDef(BaseModel):
    id: str
    room: str
    side: Side
    at: float = Field(0.5, ge=0, le=1)
    kind: WindowKind = "standard"
    width: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)
    sill: Optional[float] = Field(None, ge=0)


class StairDef(BaseModel):
    id: str
    room: str
    side: Side = Field("W", description="The flight runs along this wall of the room")
    to_level: Optional[str] = Field(None, description="null = the level above")
    width: float = Field(1.0, gt=0.6, le=3.0)


class FixtureDef(BaseModel):
    id: str
    room: str
    kind: FixtureKind
    side: Literal["N", "S", "E", "W", "center"] = Field("center", description="Against which wall (back to the wall)")
    at: float = Field(0.5, ge=0, le=1, description="Position along that wall")
    rotation: Optional[float] = Field(None, description="Degrees; null = face away from the wall")
    width: Optional[float] = Field(None, gt=0)
    depth: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)


class BalconyDef(BaseModel):
    id: str
    room: str
    side: Side
    depth: float = Field(1.5, ge=0.8, le=4.0)


class ColumnDef(BaseModel):
    id: str
    level: str = "L1"
    x: float
    y: float
    size: float = Field(0.3, gt=0)


class PorchDef(BaseModel):
    side: Side = "S"
    depth: float = Field(2.4, ge=1.0, le=5.0)


class RoofDef(BaseModel):
    kind: RoofShape = "flat"
    pitch: float = Field(30.0, ge=5, le=60)
    overhang: float = Field(0.3, ge=0, le=1.5)


class Design(BaseModel):
    name: str = "Generated Building"
    description: Optional[str] = None
    levels: list[LevelDef] = Field(default_factory=lambda: [LevelDef(id="L1")])
    rooms: list[RoomDef] = Field(default_factory=list)
    doors: list[DoorDef] = Field(default_factory=list)
    windows: list[WindowDef] = Field(default_factory=list)
    stairs: list[StairDef] = Field(default_factory=list)
    fixtures: list[FixtureDef] = Field(default_factory=list)
    balconies: list[BalconyDef] = Field(default_factory=list)
    columns: list[ColumnDef] = Field(default_factory=list)
    porch: Optional[PorchDef] = None
    roof: RoofDef = Field(default_factory=RoofDef)
    wall_material: Optional[WallMaterial] = None
    overrides: list[dict] = Field(default_factory=list, description="Raw element ops replayed after derivation")
    notes: list[str] = Field(default_factory=list)

    # --- lookups ------------------------------------------------------------

    def level(self, level_id: str) -> LevelDef | None:
        return next((l for l in self.levels if l.id == level_id), None)

    def room(self, ref: str) -> RoomDef | None:
        """By id, then by name (case-insensitive), then by slug of the name."""
        if ref is None:
            return None
        key = ref.strip()
        for r in self.rooms:
            if r.id == key:
                return r
        low, sl = key.lower(), slug(key)
        for r in self.rooms:
            if r.name.lower() == low or r.id == sl:
                return r
        return None

    def rooms_on(self, level_id: str) -> list[RoomDef]:
        return [r for r in self.rooms if r.level == level_id]

    def all_ids(self) -> set[str]:
        ids = {r.id for r in self.rooms} | {d.id for d in self.doors} | {w.id for w in self.windows}
        ids |= {s.id for s in self.stairs} | {f.id for f in self.fixtures} | {b.id for b in self.balconies}
        ids |= {c.id for c in self.columns} | {l.id for l in self.levels}
        return ids

    def unique_id(self, base: str) -> str:
        ids = self.all_ids()
        if base not in ids:
            return base
        n = 2
        while f"{base}-{n}" in ids:
            n += 1
        return f"{base}-{n}"

    def storeys(self) -> int:
        """Storeys above ground (what people count when they say 'two-storey house')."""
        return sum(1 for l in self.levels if l.index >= 0)

    def basements(self) -> int:
        return sum(1 for l in self.levels if l.index < 0)

    def ordered_levels(self) -> list[LevelDef]:
        return sorted(self.levels, key=lambda l: l.index)

    def level_above(self, level_id: str) -> LevelDef | None:
        cur = self.level(level_id)
        if cur is None:
            return None
        return next((l for l in self.ordered_levels() if l.index > cur.index), None)
