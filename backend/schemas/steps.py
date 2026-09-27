"""Build steps — the small deltas the model streams to grow (or edit) a Design.

The model answers `{"steps": [ {...}, {...} ]}`; each object is one `Step`. A step is
applied the moment it is complete in the stream, the design is re-derived, and if the
result is buildable a preview is rendered — so the building appears room by room.
A step that cannot be applied is rejected with a message and the design is left as it
was; rejected steps are sent back to the model afterwards.

One flat schema (every field optional except `step`) keeps the grammar small enough
for constrained decoders and tolerant of unconstrained ones.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.bim import FixtureKind, RoofShape, WallMaterial
from schemas.design import (MAX_STOREYS, UNROOFED_KINDS, UNWALLED_KINDS, BalconyDef, ColumnDef, ComponentDef, CustomShapeDef, Design, DoorDef,
                            DoorKind, Edge, FixtureDef, FreeDef, FreeKind, LevelDef, PorchDef, RoofDef, RoomDef, RoomKind,
                            ShapePartDef, Side, StairDef, WindowDef, WindowKind, guess_kind, slug)

StepKind = Literal["building", "level", "room", "layout", "door", "window", "stair", "furniture", "custom", "component",
                   "balcony", "porch", "roof", "column", "material", "element", "remove", "note"]


class StepError(ValueError):
    """A step could not be applied; the message is meant for the model."""


class LayoutRoom(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    kind: Optional[str] = None
    rect: Optional[list[float]] = Field(None, description="[x, y, width, depth]")
    poly: Optional[list[Edge]] = Field(None, description="any outline instead of rect")
    roofed: Optional[bool] = None
    enclosed: Optional[bool] = None

    @field_validator("rect", mode="before")
    @classmethod
    def _rect(cls, v):
        return Step._rect(v)

    @field_validator("poly", mode="before")
    @classmethod
    def _poly(cls, v):
        return Step._poly(v)


class ShapePartStep(BaseModel):
    """One solid of a `custom` step's shape: a box (min corner x,y,z; size w,d,h), or a w-diameter
    cylinder (d ignored) when shape="round". A round top plus four box legs is a table."""

    model_config = ConfigDict(extra="ignore")
    shape: Literal["box", "round"] = "box"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = Field(gt=0)
    d: float = 0.1
    h: float = Field(gt=0)


class Step(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step: StepKind
    id: Optional[str] = Field(None, description="Existing id to update/remove, or a new id; null = derive from name")
    name: Optional[str] = Field(None, description="building/level/room: display name")
    description: Optional[str] = Field(None, description="building only")
    level: Optional[str] = Field(None, description="room/column: storey id ('L1' ground, 'L2' above …)")
    kind: Optional[str] = Field(None, description="room kind | door kind | window kind | furniture kind | roof kind")
    rect: Optional[list[float]] = Field(None, description="room: [x, y, width, depth] in metres, (x,y) = south-west corner")
    poly: Optional[list[Edge]] = Field(None, description="room: outline as vertices [[x,y],…]; an item may be {to:[x,y], through:[x,y]} (arc) or {to:[x,y], open:true} (no wall)")
    path: Optional[list[Edge]] = Field(None, description="element wall: polyline [[x,y],…] (arcs as for poly)")
    roofed: Optional[bool] = Field(None, description="room: false = no roof (courtyard, terrace)")
    enclosed: Optional[bool] = Field(None, description="room: false = no walls, columns instead (carport, pergola)")
    area: Optional[float] = Field(None, description="room: target m² when rect is null")
    room: Optional[str] = Field(None, description="door/window/stair/furniture/balcony: room id")
    to: Optional[str] = Field(None, description="door: other room id, or 'outside'; element beam: end point")
    side: Optional[str] = Field(None, description="N|S|E|W (furniture also 'center'); porch/balcony/window side")
    near: Optional[list[float]] = Field(None, description="[x, y]: a point on or next to the wall meant (any room shape)")
    wall: Optional[str] = Field(None, description="door/window: id of a free-standing wall element to sit in")
    at: Optional[float] = Field(None, description="0..1 position along the wall (0 = west/south end)")
    position: Optional[list[float]] = Field(None, description="element column: [x, y]; component: footprint centre [x, y]")
    component: Optional[str] = Field(None, description="component: id or name of an uploaded component to place")
    start: Optional[list[float]] = Field(None, description="element beam: [x, y]")
    end: Optional[list[float]] = Field(None, description="element beam: [x, y]")
    thickness: Optional[float] = Field(None, description="element wall/slab/roof")
    width: Optional[float] = None
    height: Optional[float] = None
    depth: Optional[float] = None
    elevation: Optional[float] = Field(None, description="element: metres above the level (a bridge deck on piers)")
    sill: Optional[float] = Field(None, description="window sill height")
    to_level: Optional[str] = Field(None, description="stair: level it reaches (null = the one above)")
    below_ground: Optional[bool] = Field(None, description="level: a basement (id B1, B2 …)")
    pitch: Optional[float] = Field(None, description="roof: degrees")
    overhang: Optional[float] = Field(None, description="roof: metres")
    x: Optional[float] = Field(None, description="column")
    y: Optional[float] = Field(None, description="column")
    rotation: Optional[float] = Field(None, description="furniture: degrees")
    material: Optional[str] = Field(None, description="material: masonry|concrete|timber|plaster|stone|glass")
    text: Optional[str] = Field(None, description="note: a remark for the user")
    rooms: Optional[list[LayoutRoom]] = Field(None, description="layout: every room of `level`, replacing the current ones")
    parts: Optional[list[ShapePartStep]] = Field(
        None, description="custom: 1-12 solids (box or round) that together make the shape, e.g. a round table top "
                          "plus box legs; each part's x,y,z is its own min corner in the shape's local frame")

    @field_validator("id", "room", "to", "to_level", "name", mode="before")
    @classmethod
    def _str(cls, v):
        return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v

    @field_validator("side", mode="before")
    @classmethod
    def _side(cls, v):
        if v is None:
            return None
        s = str(v).strip().lower()
        return {"n": "N", "north": "N", "s": "S", "south": "S", "e": "E", "east": "E", "w": "W", "west": "W",
                "c": "center", "center": "center", "centre": "center", "middle": "center"}.get(s, str(v))

    @field_validator("rect", mode="before")
    @classmethod
    def _rect(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            v = [v.get("x"), v.get("y"), v.get("width", v.get("w")), v.get("depth", v.get("d", v.get("height")))]
        return v

    @field_validator("poly", "path", mode="before")
    @classmethod
    def _poly(cls, v):
        if v is None:
            return None
        if isinstance(v, dict) and "points" in v:
            v = v["points"]
        if not isinstance(v, list):
            raise ValueError("poly/path is a list of points [[x, y], …]")
        out = []
        for item in v:
            if isinstance(item, dict):
                d = dict(item)
                if "to" not in d and "x" in d:
                    d = {"to": [d.pop("x"), d.pop("y")], **d}
                if "arc" in d and "through" not in d:
                    d["through"] = d.pop("arc")
                out.append(d)
            else:
                out.append({"to": item})
        return out

    @field_validator("near", "position", "start", "end", mode="before")
    @classmethod
    def _point(cls, v):
        if v is None:
            return None
        if isinstance(v, dict):
            v = [v.get("x"), v.get("y")]
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise ValueError("a point is [x, y]")
        return [float(v[0]), float(v[1])]

    @field_validator("level", "to_level", mode="before")
    @classmethod
    def _level(cls, v):
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError("level must be a storey id like 'L2'")
        if isinstance(v, int):
            return f"L{v}"
        s = str(v).strip()
        import re
        m = re.match(r"^\s*(?:l|level\s*|floor\s*|storey\s*)?(\d+)\s*$", s, re.IGNORECASE)
        if m:
            return f"L{int(m.group(1))}"
        m = re.match(r"^\s*(?:b|basement\s*(?:level\s*)?|cellar\s*)(\d*)\s*$", s, re.IGNORECASE)
        if m:
            return f"B{int(m.group(1) or 1)}"
        return s


class StepsResponse(BaseModel):
    steps: list[Step] = Field(default_factory=list)

    @field_validator("steps", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        return [v] if isinstance(v, dict) else v


def _need(step: Step, attr: str) -> str:
    v = getattr(step, attr)
    if v in (None, ""):
        raise StepError(f"{step.step} needs `{attr}`")
    return v


def _literal(step: Step, value, allowed: tuple, what: str):
    if value not in allowed:
        raise StepError(f"{step.step}: {what} must be one of {', '.join(allowed)}, got {value!r}")
    return value


def _pt_or_none(v):
    return None if v is None else (float(v[0]), float(v[1]))


def _fmt(exc: Exception) -> str:
    text = str(exc)
    if "Value error, " in text:
        text = text.split("Value error, ", 1)[1].split(" [type=")[0]
    return text.strip()


def _room_flags(kind: str, roofed, enclosed) -> dict:
    """Roof/wall flags: explicit values, else the RoomDef default for the kind (None)."""
    return {"roofed": roofed, "enclosed": enclosed}


def _flag_text(room: RoomDef) -> str:
    bits = []
    if not room.roofed:
        bits.append("no roof")
    if not room.enclosed:
        bits.append("no walls, columns")
    elif room.poly and any(e.open for e in room.poly):
        bits.append(f"{sum(1 for e in room.poly if e.open)} open edge(s)")
    return f" ({', '.join(bits)})" if bits else ""


def _remove(design: Design, id_: str) -> str:
    """Remove any def by id; rooms and levels cascade."""
    lvl = design.level(id_)
    if lvl is not None:
        gone = [r.id for r in design.rooms if r.level == id_]
        design.levels = [l for l in design.levels if l.id != id_]
        for rid in gone:
            _remove(design, rid)
        design.stairs = [s for s in design.stairs if s.to_level != id_]
        return f"removed level {id_}" + (f" and its rooms ({', '.join(gone)})" if gone else "")
    room = design.room(id_)
    if room is not None:
        rid = room.id
        design.rooms = [r for r in design.rooms if r.id != rid]
        n = (len(design.doors) + len(design.windows) + len(design.stairs) + len(design.fixtures)
             + len(design.custom_shapes) + len(design.components) + len(design.balconies))
        design.doors = [d for d in design.doors if d.room != rid and d.to != rid]
        design.windows = [w for w in design.windows if w.room != rid]
        design.stairs = [s for s in design.stairs if s.room != rid]
        design.fixtures = [f for f in design.fixtures if f.room != rid]
        design.custom_shapes = [cs for cs in design.custom_shapes if cs.room != rid]
        design.components = [c for c in design.components if c.room != rid]
        design.balconies = [b for b in design.balconies if b.room != rid]
        n -= (len(design.doors) + len(design.windows) + len(design.stairs) + len(design.fixtures)
              + len(design.custom_shapes) + len(design.components) + len(design.balconies))
        return f"removed room {rid}" + (f" and {n} item(s) in it" if n else "")
    free = design.element(id_)
    if free is not None:
        design.elements = [e for e in design.elements if e.id != id_]
        design.doors = [x for x in design.doors if x.wall != id_]
        design.windows = [x for x in design.windows if x.wall != id_]
        return f"removed {free.kind} {id_}"
    for attr in ("doors", "windows", "stairs", "fixtures", "custom_shapes", "components", "balconies", "columns"):
        items = getattr(design, attr)
        keep = [i for i in items if i.id != id_]
        if len(keep) != len(items):
            setattr(design, attr, keep)
            return f"removed {attr[:-1]} {id_}"
    if id_ == "porch" and design.porch:
        design.porch = None
        return "removed the porch"
    known = sorted(design.all_ids())
    raise StepError(f"remove: no room, level, door, window, stair, furniture or balcony has id '{id_}' "
                    f"(known ids: {', '.join(known[:60])}{', …' if len(known) > 60 else ''})")


def apply_step(design: Design, step: Step) -> tuple[Design, str]:
    """Return (new design, one-line description). Raises StepError; the input is never mutated."""
    d = design.model_copy(deep=True)
    k = step.step

    if k == "building":
        if step.name:
            d.name = step.name
        if step.description:
            d.description = step.description
        return d, f"building: {d.name}"

    if k == "note":
        text = _need(step, "text")
        d.notes.append(text)
        return d, f"note: {text}"

    if k == "level":
        above = d.storeys()
        below = d.basements()
        if step.id or step.level:
            lid = Step._level(step.id or step.level)
        else:
            lid = f"B{below + 1}" if step.below_ground else f"L{above + 1}"
        if not (lid[:1] in ("L", "B") and lid[1:].isdigit()):
            raise StepError(f"level ids look like 'L1', 'L2', … or 'B1' for a basement; got {lid!r}")
        existing = d.level(lid)
        if existing:
            if step.name:
                existing.name = step.name
            if step.height:
                existing.height = step.height
            return d, f"level {lid}: {existing.display}, {existing.height} m"
        if len(d.levels) >= MAX_STOREYS:
            raise StepError(f"at most {MAX_STOREYS} levels are supported")
        idx = int(lid[1:])
        if lid.startswith("L") and idx != above + 1:
            raise StepError(f"storeys must be added in order; the next level id is L{above + 1}")
        if lid.startswith("B") and idx != below + 1:
            raise StepError(f"basements must be added in order; the next basement id is B{below + 1}")
        try:
            d.levels.append(LevelDef(id=lid, name=step.name, height=step.height or 3.0))
        except ValueError as exc:
            raise StepError(str(exc)) from exc
        what = "basement" if lid.startswith("B") else "level"
        return d, f"{what} {lid}: {d.levels[-1].display}, {d.levels[-1].height} m"

    if k == "room":
        existing = d.room(step.id) if step.id else (d.room(step.name) if step.name else None)
        if existing is None:
            name = _need(step, "name")
            rid = slug(step.id or name)
            if rid in d.all_ids():
                raise StepError(f"id '{rid}' is already used; give the room a distinct name (e.g. 'Bedroom 2')")
            level = step.level or "L1"
            if d.level(level) is None:
                raise StepError(f"room '{name}': unknown level '{level}'; add it first with a level step "
                                f"(existing: {', '.join(l.id for l in d.levels)})")
            kind = _literal(step, step.kind, RoomKind.__args__, "room kind") if step.kind else guess_kind(name)
            try:
                room = RoomDef(id=rid, name=name, level=level, kind=kind, rect=tuple(step.rect) if step.rect else None,
                               poly=step.poly, area=step.area, **_room_flags(kind, step.roofed, step.enclosed))
            except ValueError as exc:
                raise StepError(f"room '{name}': {_fmt(exc)}") from exc
            d.rooms.append(room)
            where = f" at {list(room.rect)}" if room.rect else f" ({len(room.poly)}-sided, {room.area_m2:.0f} m²)" if room.poly else " (auto-placed)"
            return d, f"room {rid}: {name} on {level}{where}" + _flag_text(room)
        if step.name:
            existing.name = step.name
        if step.level:
            if d.level(step.level) is None:
                raise StepError(f"unknown level '{step.level}'")
            existing.level = step.level
        if step.kind:
            existing.kind = _literal(step, step.kind, RoomKind.__args__, "room kind")
            existing.roofed = step.roofed if step.roofed is not None else existing.kind not in UNROOFED_KINDS
            existing.enclosed = step.enclosed if step.enclosed is not None else existing.kind not in UNWALLED_KINDS
        try:
            if step.poly:
                existing.poly = None
                existing = existing.model_copy(update={"poly": step.poly, "rect": None})
                RoomDef.model_validate(existing.model_dump())
                d.rooms = [existing if r.id == existing.id else r for r in d.rooms]
            elif step.rect:
                existing.rect = tuple(step.rect)
                existing.poly = None
        except ValueError as exc:
            raise StepError(f"room '{existing.id}': {_fmt(exc)}") from exc
        if step.roofed is not None:
            existing.roofed = step.roofed
        if step.enclosed is not None:
            existing.enclosed = step.enclosed
        if step.area:
            existing.area = step.area
        return d, f"room {existing.id}: updated" + (f" -> {list(existing.rect)}" if step.rect else " -> new outline" if step.poly else "") + _flag_text(existing)

    if k == "layout":
        level = step.level or "L1"
        if d.level(level) is None:
            raise StepError(f"layout: unknown level '{level}' (existing: {', '.join(l.id for l in d.levels)})")
        if not step.rooms:
            raise StepError("layout needs `rooms`: every room of the storey with its rect")
        keep: list[RoomDef] = []
        seen: set[str] = set()
        for lr in step.rooms:
            rid = slug(lr.name)
            if rid in seen:
                raise StepError(f"layout: room '{lr.name}' appears twice")
            seen.add(rid)
            existing = d.room(rid)
            if existing is not None and existing.level != level:
                raise StepError(f"layout: '{rid}' is on {existing.level}, not {level}")
            other = next((i for i in d.all_ids() if i == rid and existing is None), None)
            if other is not None:
                raise StepError(f"layout: id '{rid}' is already used by something that is not a room")
            kind = _literal(step, lr.kind, RoomKind.__args__, "room kind") if lr.kind else (existing.kind if existing else guess_kind(lr.name))
            if not lr.rect and not lr.poly:
                raise StepError(f"layout: room '{lr.name}' needs a rect or poly")
            try:
                keep.append(RoomDef(id=rid, name=lr.name, level=level, kind=kind, rect=tuple(lr.rect) if lr.rect else None, poly=lr.poly,
                                    area=existing.area if existing else None, **_room_flags(kind, lr.roofed, lr.enclosed)))
            except ValueError as exc:
                raise StepError(f"layout: room '{lr.name}': {_fmt(exc)}") from exc
        gone = [r.id for r in d.rooms if r.level == level and r.id not in seen]
        d.rooms = [r for r in d.rooms if r.level != level]
        removed = []
        for rid in gone:
            d.rooms.append(RoomDef(id=rid, name=rid, level=level, kind="other", rect=None))  # so _remove cascades its items
            removed.append(_remove(d, rid))
        d.rooms += keep
        return d, f"layout {level}: {', '.join(r.id for r in keep)}" + (f"; {'; '.join(removed)}" if removed else "")

    if k == "door":
        if step.wall and not step.room:
            if d.element(step.wall) is None or d.element(step.wall).kind != "wall":
                raise StepError(f"door: unknown free wall '{step.wall}' (free walls: {', '.join(e.id for e in d.elements if e.kind == 'wall') or 'none'})")
            kind = _literal(step, step.kind or "single", DoorKind.__args__, "door kind")
            did = step.id or d.unique_id(f"door-{step.wall}")
            d.doors = [x for x in d.doors if x.id != did]
            d.doors.append(DoorDef(id=did, room=None, to="outside", wall=step.wall, near=_pt_or_none(step.near),
                                   at=step.at if step.at is not None else 0.5, kind=kind, width=step.width, height=step.height))
            return d, f"door {did}: in free wall {step.wall}"
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"door: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        to = (step.to or "outside").strip()
        if to.lower() not in ("outside", "exterior", "out", "outdoors", "garden", "street"):
            other = d.room(to)
            if other is None:
                raise StepError(f"door: unknown room '{to}' (rooms: {', '.join(r.id for r in d.rooms)})")
            to = other.id
        else:
            to = "outside"
        kind = _literal(step, step.kind or "single", DoorKind.__args__, "door kind")
        side = _literal(step, step.side, ("N", "S", "E", "W"), "side") if step.side else None
        did = step.id or d.unique_id(f"door-{room.id}-{to if to != 'outside' else (side or 'out').lower()}")
        d.doors = [x for x in d.doors if x.id != did]
        d.doors.append(DoorDef(id=did, room=room.id, to=to, side=side, near=_pt_or_none(step.near), at=step.at if step.at is not None else 0.5,
                               kind=kind, width=step.width, height=step.height))
        return d, f"door {did}: {room.id} -> {to}" + (f" ({kind})" if kind != "single" else "") + (f" near {step.near}" if step.near else "")

    if k == "window":
        kind = _literal(step, step.kind or "standard", WindowKind.__args__, "window kind")
        if step.wall and not step.room:
            if d.element(step.wall) is None or d.element(step.wall).kind != "wall":
                raise StepError(f"window: unknown free wall '{step.wall}' (free walls: {', '.join(e.id for e in d.elements if e.kind == 'wall') or 'none'})")
            wid = step.id or d.unique_id(f"win-{step.wall}")
            d.windows = [x for x in d.windows if x.id != wid]
            d.windows.append(WindowDef(id=wid, room=None, wall=step.wall, near=_pt_or_none(step.near), at=step.at if step.at is not None else 0.5,
                                       kind=kind, width=step.width, height=step.height, sill=step.sill))
            return d, f"window {wid}: in free wall {step.wall}"
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"window: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        side = _literal(step, step.side, ("N", "S", "E", "W"), "side") if step.side else None
        if side is None and step.near is None:
            raise StepError("window needs `side` (N|S|E|W) or `near` [x, y]")
        wid = step.id or d.unique_id(f"win-{room.id}-{side or 'near'}")
        d.windows = [x for x in d.windows if x.id != wid]
        d.windows.append(WindowDef(id=wid, room=room.id, side=side, near=_pt_or_none(step.near), at=step.at if step.at is not None else 0.5,
                                   kind=kind, width=step.width, height=step.height, sill=step.sill))
        where = f"side {side}" if side else f"near {step.near}"
        return d, f"window {wid}: {room.id} {where}" + (f" ({kind})" if kind != "standard" else "")

    if k == "stair":
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"stair: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        side = _literal(step, step.side, ("N", "S", "E", "W"), "side") if step.side else (None if step.near else "W")
        sid = step.id or d.unique_id(f"stair-{room.id}")
        d.stairs = [x for x in d.stairs if x.id != sid]
        d.stairs.append(StairDef(id=sid, room=room.id, side=side, near=_pt_or_none(step.near), to_level=step.to_level, width=step.width or 1.0))
        return d, f"stair {sid}: in {room.id} along " + (f"side {side}" if side else f"the wall near {step.near}")

    if k == "furniture":
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"furniture: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        kind = _literal(step, (step.kind or "").lower().replace(" ", "_").replace("-", "_"), FixtureKind.__args__, "furniture kind")
        side = _literal(step, step.side or "center", ("N", "S", "E", "W", "center"), "side")
        fid = step.id or d.unique_id(f"{kind}-{room.id}")
        d.fixtures = [x for x in d.fixtures if x.id != fid]
        d.fixtures.append(FixtureDef(id=fid, room=room.id, kind=kind, side=side, near=_pt_or_none(step.near), at=step.at if step.at is not None else 0.5,
                                     rotation=step.rotation, width=step.width, depth=step.depth, height=step.height))
        where = f" against the wall near {step.near}" if step.near else f" against side {side}" if side != "center" else " (centre)"
        return d, f"{kind} {fid}: in {room.id}{where}"

    if k == "custom":
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"custom: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        if not step.parts:
            raise StepError("custom needs `parts`: 1-12 box/round solids (x, y, z, w, d, h) that together make the shape")
        side = _literal(step, step.side or "center", ("N", "S", "E", "W", "center"), "side")
        name = step.name or "Custom object"
        cid = step.id or d.unique_id(slug(name))
        parts = [ShapePartDef(shape=p.shape, x=p.x, y=p.y, z=p.z, w=p.w, d=p.d, h=p.h) for p in step.parts]
        d.custom_shapes = [x for x in d.custom_shapes if x.id != cid]
        d.custom_shapes.append(CustomShapeDef(id=cid, room=room.id, name=name, side=side, near=_pt_or_none(step.near),
                                              at=step.at if step.at is not None else 0.5, rotation=step.rotation, parts=parts))
        return d, f"custom {cid}: \"{name}\" in {room.id} ({len(parts)} part(s))"

    if k == "component":
        cid = step.id
        existing = next((c for c in d.components if c.id == cid), None) if cid else None
        ref = step.component or (existing.asset if existing else None)
        asset = d.asset(ref) if ref else None
        if asset is None:
            available = ", ".join(f"{a.id} (\"{a.name}\")" for a in d.assets.values()) or "none: the user has not attached any"
            raise StepError(f"component: unknown component '{ref}'. Available components: {available}")
        room = d.room(step.room) if step.room else (d.room(existing.room) if existing else None)
        if room is None:
            raise StepError(f"component: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        side = _literal(step, step.side or (existing.side if existing and not step.position else "center"),
                        ("N", "S", "E", "W", "center"), "side")
        cid = cid or d.unique_id(slug(f"{asset.name}-{room.id}"))
        position = _pt_or_none(step.position) if step.position is not None else (
            existing.position if existing and step.side is None and step.near is None else None)
        rotation = step.rotation if step.rotation is not None else (existing.rotation if existing else None)
        comp = ComponentDef(id=cid, asset=asset.id, room=room.id, name=step.name or asset.name, side=side,
                            near=_pt_or_none(step.near), at=step.at if step.at is not None else 0.5,
                            rotation=rotation, position=position)
        d.components = [x for x in d.components if x.id != cid]
        d.components.append(comp)
        where = f" at {position}" if position else ("" if side == "center" else f" against the {side} wall")
        verb = "moved" if existing else "placed"
        return d, f"component {cid}: {verb} \"{asset.name}\" ({asset.width} × {asset.depth} × {asset.height} m) in {room.id}{where}"

    if k == "balcony":
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"balcony: unknown room '{step.room}'")
        side = _literal(step, step.side, ("N", "S", "E", "W"), "side") if step.side else None
        if side is None and step.near is None:
            raise StepError("balcony needs `side` (N|S|E|W) or `near` [x, y]")
        bid = step.id or d.unique_id(f"balcony-{room.id}-{side or 'near'}")
        d.balconies = [x for x in d.balconies if x.id != bid]
        d.balconies.append(BalconyDef(id=bid, room=room.id, side=side, near=_pt_or_none(step.near), depth=step.depth or 1.5))
        return d, f"balcony {bid}: {room.id} " + (f"side {side}" if side else f"near {step.near}")

    if k == "porch":
        side = _literal(step, step.side or "S", ("N", "S", "E", "W"), "side")
        d.porch = PorchDef(side=side, depth=step.depth or 2.4)
        return d, f"porch on side {side}"

    if k == "roof":
        kind = _literal(step, step.kind or "flat", RoofShape.__args__, "roof kind")
        d.roof = RoofDef(kind=kind, pitch=step.pitch or d.roof.pitch, overhang=step.overhang if step.overhang is not None else d.roof.overhang)
        return d, f"roof: {kind}" + (f", pitch {d.roof.pitch:g}°" if kind != "flat" else "")

    if k == "column":
        if step.x is None or step.y is None:
            raise StepError("column needs `x` and `y`")
        level = step.level or "L1"
        if d.level(level) is None:
            raise StepError(f"column: unknown level '{level}'")
        cid = step.id or d.unique_id("column")
        d.columns = [c for c in d.columns if c.id != cid]
        d.columns.append(ColumnDef(id=cid, level=level, x=step.x, y=step.y, size=step.width or 0.3))
        return d, f"column {cid} at ({step.x:g}, {step.y:g}) on {level}"

    if k == "element":
        kind = _literal(step, (step.kind or "").lower(), FreeKind.__args__, "element kind")
        level = step.level or "L1"
        if d.level(level) is None:
            raise StepError(f"element: unknown level '{level}' (levels: {', '.join(l.id for l in d.levels)})")
        eid = step.id or d.unique_id(slug(step.name) if step.name else kind)
        if eid in d.all_ids() and d.element(eid) is None:
            raise StepError(f"element: id '{eid}' is already used by something else")
        size = step.width
        try:
            e = FreeDef(id=eid, kind=kind, level=level, name=step.name, path=step.path, poly=step.poly,
                        at=_pt_or_none(step.position or step.near), start=_pt_or_none(step.start), end=_pt_or_none(step.end),
                        height=step.height, thickness=step.thickness, width=size, depth=step.depth, elevation=step.elevation or 0.0)
        except ValueError as exc:
            raise StepError(f"element '{eid}': {_fmt(exc)}") from exc
        d.elements = [x for x in d.elements if x.id != eid]
        d.elements.append(e)
        return d, f"{kind} {eid}" + (f' "{step.name}"' if step.name else "") + f" on {level}"

    if k == "material":
        mat = _literal(step, (step.material or step.kind or "").lower(), WallMaterial.__args__, "material")
        d.wall_material = mat
        return d, f"exterior walls: {mat}"

    if k == "remove":
        return d, _remove(d, _need(step, "id"))

    raise StepError(f"unknown step '{k}'")


def describe_step(step: Step) -> str:
    data = step.model_dump(exclude_none=True)
    return " ".join(f"{k}={v}" for k, v in data.items())
