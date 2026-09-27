"""Build steps — the small deltas the model streams to grow (or edit) a `GeoModel`.

The model answers `{"steps": [ {...}, {...} ]}`; each object is one `GeoStep`. A step is
applied the moment it is complete in the stream, the model is re-validated, and if the result
is buildable a preview is rendered — so the thing appears part by part. A step that cannot be
applied is rejected with a message and the model is left as it was; rejected steps are sent
back to the model afterwards.

One flat schema (every field optional except `step`) keeps the grammar small enough for
constrained decoders and tolerant of unconstrained ones. Eight step kinds, and all of the
expressiveness in `solids`:

    model  level  part  opening  assembly  instance  remove  note

This module also owns the **sugar**: `box`, `cylinder`, `wall`, bare `solid`, loose points.
Sugar is resolved here, so `schemas/geo.py` only ever stores the canonical form and there is
exactly one representation to compile, check and migrate.
"""

from __future__ import annotations

import math
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from schemas.geo import (MAX_LEVELS, GeoAssembly, GeoInstance, GeoLevel, GeoModel, GeoOpening, GeoPart, Placement,
                         Profile, Repeat, Solid, slug)
from schemas.geom2d import as_point, as_point3, r2

StepKind = Literal["model", "level", "part", "opening", "assembly", "instance", "remove", "note"]


class StepError(ValueError):
    """A step could not be applied; the message is meant for the model."""


class SolidStep(BaseModel):
    """One solid, with sugar. Give `op` and its fields, or one of the shorthands.

    box      [w, d, h]  a box centred in plan on `at`, rising h from it
    cylinder [d, h]     a d-diameter cylinder rising h
    wall     [[x,y], …] a polyline footprint, thickened by `thickness`, extruded `height`
    """

    model_config = ConfigDict(extra="ignore")

    op: Optional[str] = Field(None, description="extrude | revolve | sweep | mesh")
    at: Optional[list[float]] = Field(None, description="Origin of this solid inside the part: [x,y,z]")
    rotation: Optional[float] = Field(None, description="Degrees about the solid's axis")
    axis: Optional[list[float]] = Field(None, description="This solid's local +Z; [0,-1,0] stands a revolve up")
    ref: Optional[list[float]] = Field(None, description="This solid's local +X")
    profile: Optional[Profile] = None
    depth: Optional[float] = Field(None, description="extrude: distance along the local +Z")
    angle: Optional[float] = Field(None, description="revolve: degrees")
    axis_at: Optional[list[float]] = Field(None, description="revolve: a point on the axis, in the profile's plane")
    axis_dir: Optional[list[float]] = Field(None, description="revolve: axis direction in the profile's plane; default [0,1]")
    path: Optional[list[Any]] = Field(None, description="sweep: 3D polyline [[x,y,z], …]")
    faces: Optional[list[Any]] = Field(None, description="mesh: [[[x,y,z], …], …] outward-facing loops")
    box: Optional[list[float]] = Field(None, description="Shorthand: [width, depth, height]")
    cylinder: Optional[list[float]] = Field(None, description="Shorthand: [diameter, height]")
    wall: Optional[list[Any]] = Field(None, description="Shorthand: a plan polyline, thickened by `thickness`")
    thickness: Optional[float] = Field(None, description="wall shorthand: strip thickness")
    height: Optional[float] = Field(None, description="wall shorthand: extrusion height")

    def resolved(self) -> Solid:
        """The canonical `Solid` this step describes, with sugar expanded."""
        place: dict = {}
        if self.at is not None:
            place["at"] = as_point3(self.at)
        if self.rotation is not None:
            place["rotation"] = self.rotation
        if self.axis is not None:
            place["axis"] = as_point3(self.axis)
        if self.ref is not None:
            place["ref"] = as_point3(self.ref)

        if self.box is not None:
            if len(self.box) != 3:
                raise StepError("box is [width, depth, height]")
            w, d, h = (float(v) for v in self.box)
            return Solid(op="extrude", place=Placement(**place), profile=Profile(rect=(w, d)), depth=h)
        if self.cylinder is not None:
            if len(self.cylinder) != 2:
                raise StepError("cylinder is [diameter, height]")
            dia, h = (float(v) for v in self.cylinder)
            return Solid(op="extrude", place=Placement(**place), profile=Profile(circle=dia), depth=h)
        if self.wall is not None:
            if self.thickness is None or self.height is None:
                raise StepError("the wall shorthand needs `thickness` and `height`")
            return Solid(op="extrude", place=Placement(**place),
                         profile=Profile(band=self.wall, width=self.thickness), depth=self.height)

        op = (self.op or ("mesh" if self.faces else "sweep" if self.path else "revolve" if self.angle is not None else "extrude"))
        op = str(op).strip().lower()
        if op in ("prism", "extrusion"):
            op = "extrude"
        if op in ("revolution", "rotate"):
            op = "revolve"
        if op in ("brep", "faces", "shell"):
            op = "mesh"
        if op not in ("extrude", "revolve", "sweep", "mesh"):
            raise StepError(f"unknown solid op '{self.op}'; use extrude, revolve, sweep or mesh "
                            "(or the box / cylinder / wall shorthands)")
        depth = self.depth if self.depth is not None else (self.height if op == "extrude" else None)
        data: dict = {"op": op, "place": Placement(**place), "profile": self.profile, "depth": depth,
                      "angle": self.angle, "path": self.path, "faces": self.faces}
        if self.axis_at is not None:
            data["axis_at"] = as_point(self.axis_at)
        if self.axis_dir is not None:
            data["axis_dir"] = as_point(self.axis_dir)
        try:
            return Solid.model_validate({k: v for k, v in data.items() if v is not None})
        except ValidationError as exc:
            raise StepError(_fmt(exc)) from exc


class GeoStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step: StepKind
    id: Optional[str] = Field(None, description="Existing id to update/remove, or a new id; null = derived from name")
    name: Optional[str] = Field(None, description="model/level/part/assembly: display name")
    description: Optional[str] = Field(None, description="model only")
    level: Optional[str] = Field(None, description="Level id: 'L1' the ground level, 'L2' above it …, 'B1' below")
    height: Optional[float] = Field(None, description="level: floor-to-floor height in metres")
    elevation: Optional[float] = Field(None, description="level: metres above datum; null = stack on the level below")

    # part
    ifc: Optional[str] = Field(None, description="part: IFC entity name, e.g. IfcWall, IfcSlab, IfcCivilElement")
    ifc_type: Optional[str] = Field(None, description="part/assembly: PredefinedType, e.g. SOLIDWALL, FLOOR")
    at: Optional[list[float]] = Field(None, description="part/instance: frame origin [x,y,z] on its level")
    rotation: Optional[float] = Field(None, description="part/instance: degrees about the frame axis")
    axis: Optional[list[float]] = Field(None, description="part/instance: the frame's local +Z; default [0,0,1]")
    ref: Optional[list[float]] = Field(None, description="part/instance: the frame's local +X")
    solids: Optional[list[SolidStep]] = Field(None, description="part: the solids that make its body")
    solid: Optional[SolidStep] = Field(None, description="part: shorthand for a single solid; opening: the void")
    repeat: Optional[Repeat] = Field(None, description="part/instance: array by a transform")
    material: Optional[str] = Field(None, description="part: free-text material name")
    style: Optional[str] = Field(None, description="part: free-text colour key")

    # opening
    host: Optional[str] = Field(None, description="opening: the part the void is cut into")
    along: Optional[float] = Field(None, description="opening: distance along the host's local +X")
    up: Optional[float] = Field(None, description="opening: height above the host's local base")
    width: Optional[float] = Field(None, description="opening: void width")
    depth: Optional[float] = Field(None, description="opening: through-thickness; null = right through the host")
    fill: Optional[str] = Field(None, description="opening: id of the part that fills it")

    # assembly / instance
    parts: Optional[list[str]] = Field(None, description="assembly: part ids to group")
    of: Optional[str] = Field(None, description="instance: assembly id to copy")

    text: Optional[str] = Field(None, description="note: a remark for the user")

    @field_validator("id", "host", "fill", "of", "name", mode="before")
    @classmethod
    def _str(cls, v):
        return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v):
        return None if v is None else level_id(v)

    @field_validator("parts", mode="before")
    @classmethod
    def _parts(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return [str(p) for p in v]

    @field_validator("solids", mode="before")
    @classmethod
    def _solids(cls, v):
        if v is None:
            return None
        return [v] if isinstance(v, dict) else v


class GeoStepsResponse(BaseModel):
    steps: list[GeoStep] = Field(default_factory=list)

    @field_validator("steps", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        return [v] if isinstance(v, dict) else v


# --- helpers -----------------------------------------------------------------

def level_id(v) -> str:
    """'2', 'level 2', 'L2', 'basement' → 'L2' / 'B1'."""
    import re
    if isinstance(v, bool):
        raise ValueError("level must be an id like 'L2'")
    if isinstance(v, int):
        return f"L{v}"
    s = str(v).strip()
    m = re.match(r"^\s*(?:l|level\s*|floor\s*|storey\s*|story\s*)?(\d+)\s*$", s, re.IGNORECASE)
    if m:
        return f"L{int(m.group(1))}"
    m = re.match(r"^\s*(?:b|basement\s*(?:level\s*)?|cellar\s*|underground\s*)(\d*)\s*$", s, re.IGNORECASE)
    if m:
        return f"B{int(m.group(1) or 1)}"
    return s.upper() if re.match(r"^[lb]\d+$", s, re.IGNORECASE) else s


def _fmt(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        out = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"] if p != "__root__")
            msg = e["msg"].replace("Value error, ", "")
            out.append(f"{loc}: {msg}" if loc else msg)
        return "; ".join(out)
    text = str(exc)
    if "Value error, " in text:
        text = text.split("Value error, ", 1)[1].split(" [type=")[0]
    return text.strip()


def _need(step: GeoStep, attr: str) -> Any:
    v = getattr(step, attr)
    if v in (None, "", []):
        raise StepError(f"{step.step} needs `{attr}`")
    return v


def _placement(step: GeoStep) -> Placement:
    data: dict = {}
    if step.at is not None:
        data["at"] = as_point3(step.at)
    if step.rotation is not None:
        data["rotation"] = step.rotation
    if step.axis is not None:
        data["axis"] = as_point3(step.axis)
    if step.ref is not None:
        data["ref"] = as_point3(step.ref)
    try:
        return Placement(**data)
    except ValidationError as exc:
        raise StepError(_fmt(exc)) from exc


def _validated(model: GeoModel, what: str) -> GeoModel:
    try:
        return GeoModel.model_validate(model.model_dump())
    except ValidationError as exc:
        raise StepError(f"{what}: {_fmt(exc)}") from exc


def remove_id(model: GeoModel, id_: str) -> str:
    """Remove anything by id; removing a part cascades to the openings it hosts or fills, the
    assemblies that list it, and the instances of an assembly that ends up empty."""
    lvl = model.level(id_)
    if lvl is not None:
        gone = [p.id for p in model.parts if p.level == lvl.id]
        model.levels = [l for l in model.levels if l.id != lvl.id]
        if not model.levels:
            raise StepError("a model needs at least one level; add another before removing this one")
        notes = [remove_id(model, pid) for pid in gone]
        return f"removed level {lvl.id}" + (f" and its {len(gone)} part(s)" if gone else "")
    part = model.part(id_)
    if part is not None:
        model.parts = [p for p in model.parts if p.id != id_]
        before = len(model.openings)
        model.openings = [o for o in model.openings if o.host != id_]
        for o in model.openings:
            if o.fill == id_:
                o.fill = None
        cut = before - len(model.openings)
        for a in model.assemblies:
            a.parts = [p for p in a.parts if p != id_]
        empty = [a.id for a in model.assemblies if not a.parts]
        model.assemblies = [a for a in model.assemblies if a.parts]
        model.instances = [i for i in model.instances if i.of not in empty]
        extra = []
        if cut:
            extra.append(f"{cut} opening(s) in it")
        if empty:
            extra.append(f"assembly {', '.join(empty)} (now empty)")
        return f"removed part {id_}" + (f" and {', '.join(extra)}" if extra else "")
    if model.opening(id_) is not None:
        model.openings = [o for o in model.openings if o.id != id_]
        return f"removed opening {id_}"
    asm = model.assembly(id_)
    if asm is not None:
        model.assemblies = [a for a in model.assemblies if a.id != id_]
        gone = [i.id for i in model.instances if i.of == id_]
        model.instances = [i for i in model.instances if i.of != id_]
        return f"removed assembly {id_}" + (f" and its instance(s) {', '.join(gone)}" if gone else "")
    if model.instance(id_) is not None:
        model.instances = [i for i in model.instances if i.id != id_]
        return f"removed instance {id_}"
    known = sorted(model.all_ids())
    raise StepError(f"remove: nothing has id '{id_}' "
                    f"(known ids: {', '.join(known[:60])}{', …' if len(known) > 60 else ''})")


# --- the applier -------------------------------------------------------------

def apply_step(model: GeoModel, step: GeoStep) -> tuple[GeoModel, str]:
    """Return (new model, one-line description). Raises StepError; the input is never mutated."""
    m = model.model_copy(deep=True)
    k = step.step

    if k == "model":
        if step.name:
            m.name = step.name
        if step.description:
            m.description = step.description
        return m, f"model: {m.name}"

    if k == "note":
        text = _need(step, "text")
        m.notes.append(str(text))
        return m, f"note: {text}"

    if k == "level":
        above, below = m.storeys(), m.basements()
        if step.id or step.level:
            lid = level_id(step.id or step.level)
        else:
            lid = f"L{above + 1}"
        existing = m.level(lid)
        if existing is not None:
            if step.name:
                existing.name = step.name
            if step.height:
                existing.height = step.height
            if step.elevation is not None:
                existing.elevation = step.elevation
            return _validated(m, f"level {lid}"), f"level {lid}: {existing.display}, {existing.height:g} m"
        if len(m.levels) >= MAX_LEVELS:
            raise StepError(f"at most {MAX_LEVELS} levels are supported")
        try:
            new = GeoLevel(id=lid, name=step.name, height=step.height or 3.0, elevation=step.elevation)
        except ValidationError as exc:
            raise StepError(_fmt(exc)) from exc
        idx = int(new.id[1:])
        if not new.below_ground and idx != above + 1:
            raise StepError(f"levels are added in order; the next level id is L{above + 1}")
        if new.below_ground and idx != below + 1:
            raise StepError(f"levels below ground are added in order; the next one is B{below + 1}")
        m.levels.append(new)
        m = _validated(m, f"level {lid}")
        where = f" at {new.elevation:g} m" if new.elevation is not None else ""
        return m, f"level {lid}: {new.display}, {new.height:g} m{where}"

    if k == "part":
        existing = m.part(step.id) if step.id else None
        level = step.level or (existing.level if existing else "L1")
        if m.level(level) is None:
            raise StepError(f"part: unknown level '{level}' (levels: {', '.join(l.id for l in m.levels)}); "
                            "add it first with a level step")
        solid_steps = step.solids or ([step.solid] if step.solid else None)
        solids = None
        if solid_steps:
            solids = [s.resolved() for s in solid_steps]
        if existing is None:
            if solids is None:
                raise StepError("part needs `solids` (or the `solid` shorthand): at least one solid to make its body")
            pid = step.id or m.unique_id(step.name or step.ifc or "part")
            if pid in m.all_ids():
                raise StepError(f"id '{pid}' is already used; give this part a distinct id or name")
            try:
                part = GeoPart(id=pid, name=step.name, ifc=step.ifc or "IfcBuildingElementProxy", ifc_type=step.ifc_type,
                               level=level, place=_placement(step), solids=solids, repeat=step.repeat,
                               material=step.material, style=step.style)
            except ValidationError as exc:
                raise StepError(f"part '{pid}': {_fmt(exc)}") from exc
            m.parts.append(part)
            m = _validated(m, f"part '{pid}'")
            return m, f"part {pid}: " + _part_line(part)
        # Update in place: the id (and therefore the GlobalId) survives.
        data = existing.model_dump()
        data["level"] = level
        if step.name:
            data["name"] = step.name
        if step.ifc:
            data["ifc"] = step.ifc
        if step.ifc_type:
            data["ifc_type"] = step.ifc_type
        if step.material:
            data["material"] = step.material
        if step.style:
            data["style"] = step.style
        if any(v is not None for v in (step.at, step.rotation, step.axis, step.ref)):
            base = existing.place.model_dump()
            new_place = _placement(step).model_dump()
            for field, given in (("at", step.at), ("rotation", step.rotation), ("axis", step.axis), ("ref", step.ref)):
                if given is not None:
                    base[field] = new_place[field]
            data["place"] = base
        if solids is not None:
            data["solids"] = [s.model_dump() for s in solids]
        if step.repeat is not None:
            data["repeat"] = step.repeat.model_dump()
        try:
            part = GeoPart.model_validate(data)
        except ValidationError as exc:
            raise StepError(f"part '{existing.id}': {_fmt(exc)}") from exc
        m.parts = [part if p.id == part.id else p for p in m.parts]
        m = _validated(m, f"part '{part.id}'")
        return m, f"part {part.id}: updated — " + _part_line(part)

    if k == "opening":
        host_id = _need(step, "host")
        host = m.part(host_id)
        if host is None:
            raise StepError(f"opening: unknown host part '{host_id}' "
                            f"(parts: {', '.join(p.id for p in m.parts[:40]) or 'none'})")
        oid = step.id or m.unique_id(f"{host_id}-opening")
        if oid in m.all_ids() and m.opening(oid) is None:
            raise StepError(f"opening: id '{oid}' is already used by something else")
        if step.fill and m.part(step.fill) is None:
            raise StepError(f"opening: unknown fill part '{step.fill}'; add the part that fills the void first")
        solid = step.solid.resolved() if step.solid else None
        try:
            opening = GeoOpening(id=oid, host=host_id, solid=solid, along=step.along, up=step.up, width=step.width,
                                 height=step.height, depth=step.depth, fill=step.fill)
        except ValidationError as exc:
            raise StepError(f"opening '{oid}': {_fmt(exc)}") from exc
        _fits(host, opening)
        m.openings = [o for o in m.openings if o.id != oid]
        m.openings.append(opening)
        m = _validated(m, f"opening '{oid}'")
        return m, f"opening {oid}: in {host_id}" + (f", filled by {step.fill}" if step.fill else "")

    if k == "assembly":
        ids = _need(step, "parts")
        missing = [p for p in ids if m.part(p) is None]
        if missing:
            raise StepError(f"assembly: unknown part(s) {', '.join(missing)} "
                            f"(parts: {', '.join(p.id for p in m.parts[:40]) or 'none'})")
        aid = step.id or m.unique_id(step.name or "assembly")
        if aid in m.all_ids() and m.assembly(aid) is None:
            raise StepError(f"assembly: id '{aid}' is already used by something else")
        level = step.level or m.part(ids[0]).level
        try:
            asm = GeoAssembly(id=aid, name=step.name, parts=list(dict.fromkeys(ids)), ifc_type=step.ifc_type, level=level)
        except ValidationError as exc:
            raise StepError(f"assembly '{aid}': {_fmt(exc)}") from exc
        m.assemblies = [a for a in m.assemblies if a.id != aid]
        m.assemblies.append(asm)
        m = _validated(m, f"assembly '{aid}'")
        return m, f"assembly {aid}: {len(asm.parts)} part(s) — {', '.join(asm.parts[:8])}"

    if k == "instance":
        of = _need(step, "of")
        asm = m.assembly(of)
        if asm is None:
            raise StepError(f"instance: unknown assembly '{of}' "
                            f"(assemblies: {', '.join(a.id for a in m.assemblies) or 'none'})")
        iid = step.id or m.unique_id(f"{of}-copy")
        if iid in m.all_ids() and m.instance(iid) is None:
            raise StepError(f"instance: id '{iid}' is already used by something else")
        try:
            inst = GeoInstance(id=iid, of=of, place=_placement(step), repeat=step.repeat, level=step.level)
        except ValidationError as exc:
            raise StepError(f"instance '{iid}': {_fmt(exc)}") from exc
        m.instances = [i for i in m.instances if i.id != iid]
        m.instances.append(inst)
        m = _validated(m, f"instance '{iid}'")
        n = len(asm.parts) * inst.copies
        return m, f"instance {iid}: {inst.copies} copy(ies) of {of} ({n} part(s))"

    if k == "remove":
        note = remove_id(m, str(_need(step, "id")))
        return _validated(m, "remove"), note

    raise StepError(f"unknown step '{k}'")


def _part_line(part: GeoPart) -> str:
    lo, hi = part.local_extent()
    size = f"{hi[0] - lo[0]:.2f} x {hi[1] - lo[1]:.2f} x {hi[2] - lo[2]:.2f} m"
    what = ", ".join(s.op for s in part.solids)
    rep = f", {part.repeat.count}x" if part.repeat else ""
    return f'{part.ifc}{f" {part.name!r}" if part.name else ""} on {part.level}, {what}{rep}, {size}'


def _fits(host: GeoPart, opening: GeoOpening) -> None:
    """Reject an opening that misses its host outright — the commonest way a generated model
    ends up with a void hanging in mid-air next to the wall it was meant to pierce."""
    if opening.solid is not None:
        return
    lo, hi = host.local_extent()
    length = hi[0] - lo[0]
    tall = hi[2] - lo[2]
    if opening.along is None or opening.width is None or opening.height is None:
        return
    if length > 0 and opening.along + opening.width > length + 1e-6:
        raise StepError(f"opening '{opening.id}': it runs from {opening.along:g} to "
                        f"{opening.along + opening.width:g} m along host '{host.id}', which is only "
                        f"{length:.2f} m long in its own +X direction")
    if opening.along < lo[0] - 1e-6:
        raise StepError(f"opening '{opening.id}': along={opening.along:g} is before the start of host "
                        f"'{host.id}' (its local +X runs from {lo[0]:g} to {hi[0]:g})")
    if tall > 0 and (opening.up or 0.0) + opening.height > tall + 1e-6:
        raise StepError(f"opening '{opening.id}': its top is at {(opening.up or 0) + opening.height:g} m but host "
                        f"'{host.id}' is only {tall:.2f} m tall")


def describe_step(step: GeoStep) -> str:
    data = step.model_dump(exclude_none=True)
    return " ".join(f"{k}={v}" for k, v in data.items())


def expand_instances(model: GeoModel) -> list[GeoPart]:
    """Every part the model compiles to: the authored ones, then one copy per instance copy.

    Copy ids are `<instance>-<copy index>-<part>` (the index is left out for a single copy), so
    ids are stable under edits and a viewer selection resolves back to a real part."""
    out: list[GeoPart] = list(model.parts)
    for inst in model.instances:
        asm = model.assembly(inst.of)
        if asm is None:
            continue
        locals_ = [inst.repeat.transform(j) for j in range(inst.copies)] if inst.repeat else [Placement()]
        for i, local in enumerate(locals_):
            for pid in asm.parts:
                src = model.part(pid)
                if src is None:
                    continue
                copy = src.model_copy(deep=True)
                copy.id = f"{inst.id}-{pid}" if inst.copies == 1 else f"{inst.id}-{i + 1}-{pid}"
                copy.level = inst.level or src.level
                copy.place = _compose(inst.place, _compose(local, src.place))
                out.append(copy)
    return out


def _compose(outer: Placement, inner: Placement) -> Placement:
    """`outer` applied to `inner`: the frame you get by placing `inner` inside `outer`.

    Only the Z-rotation part composes exactly in one Placement, which is all instancing needs
    (bays repeat in plan). A non-vertical inner axis is carried through unrotated, and the plan
    rotation is summed — enough for arrays of upright parts and honest about its limits."""
    x, y, z = outer.basis()
    at = outer.apply(inner.at)
    ang = math.radians(outer.rotation)
    c, s = math.cos(ang), math.sin(ang)
    axis = inner.axis
    if axis == (0.0, 0.0, 1.0) or outer.axis != (0.0, 0.0, 1.0):
        new_axis = _rotate_by(outer, axis)
    else:
        new_axis = (r2(axis[0] * c - axis[1] * s), r2(axis[0] * s + axis[1] * c), axis[2])
    ref = _rotate_by(outer, inner.ref) if inner.ref is not None else None
    rot = inner.rotation if outer.axis != (0.0, 0.0, 1.0) else inner.rotation + outer.rotation
    return Placement(at=tuple(r2(v) for v in at), rotation=r2(rot), axis=new_axis, ref=ref)


def _rotate_by(frame: Placement, v) -> tuple[float, float, float]:
    x, y, z = frame.basis()
    return (r2(v[0] * x[0] + v[1] * y[0] + v[2] * z[0]),
            r2(v[0] * x[1] + v[1] * y[1] + v[2] * z[1]),
            r2(v[0] * x[2] + v[1] * y[2] + v[2] * z[2]))
