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
from schemas.design import (MAX_STOREYS, BalconyDef, ColumnDef, Design, DoorDef, DoorKind, FixtureDef, LevelDef, PorchDef, RoofDef,
                            RoomDef, RoomKind, Side, StairDef, WindowDef, WindowKind, guess_kind, slug)

StepKind = Literal["building", "level", "room", "layout", "door", "window", "stair", "furniture", "balcony", "porch", "roof",
                   "column", "material", "remove", "note"]


class StepError(ValueError):
    """A step could not be applied; the message is meant for the model."""


class LayoutRoom(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    kind: Optional[str] = None
    rect: list[float] = Field(description="[x, y, width, depth]")

    @field_validator("rect", mode="before")
    @classmethod
    def _rect(cls, v):
        return Step._rect(v)


class Step(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step: StepKind
    id: Optional[str] = Field(None, description="Existing id to update/remove, or a new id; null = derive from name")
    name: Optional[str] = Field(None, description="building/level/room: display name")
    description: Optional[str] = Field(None, description="building only")
    level: Optional[str] = Field(None, description="room/column: storey id ('L1' ground, 'L2' above …)")
    kind: Optional[str] = Field(None, description="room kind | door kind | window kind | furniture kind | roof kind")
    rect: Optional[list[float]] = Field(None, description="room: [x, y, width, depth] in metres, (x,y) = south-west corner")
    area: Optional[float] = Field(None, description="room: target m² when rect is null")
    room: Optional[str] = Field(None, description="door/window/stair/furniture/balcony: room id")
    to: Optional[str] = Field(None, description="door: other room id, or 'outside'")
    side: Optional[str] = Field(None, description="N|S|E|W (furniture also 'center'); porch/balcony/window side")
    at: Optional[float] = Field(None, description="0..1 position along the wall (0 = west/south end)")
    width: Optional[float] = None
    height: Optional[float] = None
    depth: Optional[float] = None
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
        n = len(design.doors) + len(design.windows) + len(design.stairs) + len(design.fixtures) + len(design.balconies)
        design.doors = [d for d in design.doors if d.room != rid and d.to != rid]
        design.windows = [w for w in design.windows if w.room != rid]
        design.stairs = [s for s in design.stairs if s.room != rid]
        design.fixtures = [f for f in design.fixtures if f.room != rid]
        design.balconies = [b for b in design.balconies if b.room != rid]
        n -= len(design.doors) + len(design.windows) + len(design.stairs) + len(design.fixtures) + len(design.balconies)
        return f"removed room {rid}" + (f" and {n} item(s) in it" if n else "")
    for attr in ("doors", "windows", "stairs", "fixtures", "balconies", "columns"):
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
            room = RoomDef(id=rid, name=name, level=level, kind=kind, rect=tuple(step.rect) if step.rect else None, area=step.area)
            d.rooms.append(room)
            return d, f"room {rid}: {name} on {level}" + (f" at {list(room.rect)}" if room.rect else " (auto-placed)")
        if step.name:
            existing.name = step.name
        if step.level:
            if d.level(step.level) is None:
                raise StepError(f"unknown level '{step.level}'")
            existing.level = step.level
        if step.kind:
            existing.kind = _literal(step, step.kind, RoomKind.__args__, "room kind")
        if step.rect:
            existing.rect = tuple(step.rect)
        if step.area:
            existing.area = step.area
        return d, f"room {existing.id}: updated" + (f" -> {list(existing.rect)}" if step.rect else "")

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
            keep.append(RoomDef(id=rid, name=lr.name, level=level, kind=kind, rect=tuple(lr.rect), area=existing.area if existing else None))
        gone = [r.id for r in d.rooms if r.level == level and r.id not in seen]
        d.rooms = [r for r in d.rooms if r.level != level]
        removed = []
        for rid in gone:
            d.rooms.append(RoomDef(id=rid, name=rid, level=level, kind="other", rect=None))  # so _remove cascades its items
            removed.append(_remove(d, rid))
        d.rooms += keep
        return d, f"layout {level}: {', '.join(r.id for r in keep)}" + (f"; {'; '.join(removed)}" if removed else "")

    if k == "door":
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
        d.doors.append(DoorDef(id=did, room=room.id, to=to, side=side, at=step.at if step.at is not None else 0.5, kind=kind,
                               width=step.width, height=step.height))
        return d, f"door {did}: {room.id} -> {to}" + (f" ({kind})" if kind != "single" else "")

    if k == "window":
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"window: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        side = _literal(step, _need(step, "side"), ("N", "S", "E", "W"), "side")
        kind = _literal(step, step.kind or "standard", WindowKind.__args__, "window kind")
        wid = step.id or d.unique_id(f"win-{room.id}-{side}")
        d.windows = [x for x in d.windows if x.id != wid]
        d.windows.append(WindowDef(id=wid, room=room.id, side=side, at=step.at if step.at is not None else 0.5, kind=kind,
                                   width=step.width, height=step.height, sill=step.sill))
        return d, f"window {wid}: {room.id} side {side}" + (f" ({kind})" if kind != "standard" else "")

    if k == "stair":
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"stair: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        side = _literal(step, step.side or "W", ("N", "S", "E", "W"), "side")
        sid = step.id or d.unique_id(f"stair-{room.id}")
        d.stairs = [x for x in d.stairs if x.id != sid]
        d.stairs.append(StairDef(id=sid, room=room.id, side=side, to_level=step.to_level, width=step.width or 1.0))
        return d, f"stair {sid}: in {room.id} along side {side}"

    if k == "furniture":
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"furniture: unknown room '{step.room}' (rooms: {', '.join(r.id for r in d.rooms)})")
        kind = _literal(step, (step.kind or "").lower().replace(" ", "_").replace("-", "_"), FixtureKind.__args__, "furniture kind")
        side = _literal(step, step.side or "center", ("N", "S", "E", "W", "center"), "side")
        fid = step.id or d.unique_id(f"{kind}-{room.id}")
        d.fixtures = [x for x in d.fixtures if x.id != fid]
        d.fixtures.append(FixtureDef(id=fid, room=room.id, kind=kind, side=side, at=step.at if step.at is not None else 0.5,
                                     rotation=step.rotation, width=step.width, depth=step.depth, height=step.height))
        return d, f"{kind} {fid}: in {room.id}" + (f" against side {side}" if side != "center" else " (centre)")

    if k == "balcony":
        room = d.room(_need(step, "room"))
        if room is None:
            raise StepError(f"balcony: unknown room '{step.room}'")
        side = _literal(step, _need(step, "side"), ("N", "S", "E", "W"), "side")
        bid = step.id or d.unique_id(f"balcony-{room.id}-{side}")
        d.balconies = [x for x in d.balconies if x.id != bid]
        d.balconies.append(BalconyDef(id=bid, room=room.id, side=side, depth=step.depth or 1.5))
        return d, f"balcony {bid}: {room.id} side {side}"

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
