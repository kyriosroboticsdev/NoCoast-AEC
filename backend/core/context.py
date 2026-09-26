"""Render the current state as compact text for the LLM.

`describe_design` is what an edit prompt sees: rooms with their rectangles, exterior
sides and neighbours, then openings, stairs, fixtures and the roof — a 12-room house
is ~600 tokens. `describe_spec` (one line per element) is kept for the /context
endpoint and for raw element ops.
"""

from __future__ import annotations

import re

from core.derive import Derived
from schemas.bim import BuildingSpec
from schemas.design import Design

MAX_ELEMENTS = 400


def _pt(p) -> str:
    return f"({p[0]:g},{p[1]:g})"


def _outline(pts) -> str:
    return "[" + " ".join(_pt(p) for p in pts) + "]"


def describe_element(el) -> str:
    """`<type> id=<id> ...` — the explicit id= keeps small models from merging type and id into one token."""
    name = f' name="{el.name}"' if el.name and el.name != el.id else ""
    head = f"{el.type} id={el.id}{name}"
    if el.type == "wall":
        ext = " external" if el.external else ""
        h = f" h={el.height:g}" if el.height else ""
        return f"{head} {_pt(el.start)}->{_pt(el.end)} len={el.length:.2f} t={el.thickness:g}{h}{ext}"
    if el.type == "door":
        return f"{head} wall={el.wall} offset={el.offset:g} w={el.width:g} h={el.height:g} kind={el.kind}"
    if el.type == "window":
        return f"{head} wall={el.wall} offset={el.offset:g} w={el.width:g} h={el.height:g} sill={el.sill_height:g}"
    if el.type in ("slab", "roof"):
        shape = f" shape={el.shape}" if el.type == "roof" else ""
        return f"{head} outline={_outline(el.outline)} t={el.thickness:g}{shape}"
    if el.type == "space":
        return f"{head} outline={_outline(el.outline)}"
    if el.type == "column":
        return f"{head} at {_pt(el.position)} {el.width:g}x{el.depth:g}"
    if el.type == "beam":
        return f"{head} {_pt(el.start)}->{_pt(el.end)} {el.width:g}x{el.depth:g}"
    if el.type == "stair":
        return f"{head} at {_pt(el.position)} dir={el.direction:g} w={el.width:g} to={el.to_level}"
    if el.type == "fixture":
        return f"{head} kind={el.kind} at {_pt(el.position)} rot={el.rotation:g} {el.width:g}x{el.depth:g}x{el.height:g}"
    if el.type == "railing":
        return f"{head} path={_outline(el.path)} h={el.height:g}"
    if el.type == "pipe":
        return f"{head} kind={el.kind} at {_pt(el.position)} {el.bottom_level}->{el.top_level}"
    if el.type == "outlet":
        return f"{head} at {_pt(el.position)} h={el.height:g}"
    if el.type in ("light", "panel"):
        return f"{head} at {_pt(el.position)}"
    if el.type == "wire":
        return f"{head} path={_outline(el.path)} elevation={el.elevation:g}"
    return head


def describe_spec(spec: BuildingSpec) -> str:
    lines = [f'building "{spec.building.name}"' + (f": {spec.building.description}" if spec.building.description else "")]
    lines.append("levels:")
    for l in spec.levels:
        lines.append(f"  level id={l.id} name=\"{l.name}\" elevation={l.elevation:g} height={l.height:g}")
    by_level: dict[str, list] = {l.id: [] for l in spec.levels}
    walls = {el.id: el for el in spec.elements if el.type == "wall"}
    for el in spec.elements:
        if el.type == "pipe":
            level = el.bottom_level
        elif hasattr(el, "level"):
            level = el.level
        else:
            level = walls[el.wall].level
        by_level.setdefault(level, []).append(el)
    shown = 0
    for level_id, els in by_level.items():
        lines.append(f"elements on {level_id} ({len(els)}):")
        for el in els:
            if shown >= MAX_ELEMENTS:
                lines.append(f"  … {sum(len(v) for v in by_level.values()) - shown} more elements omitted")
                return "\n".join(lines)
            lines.append("  " + describe_element(el))
            shown += 1
    return "\n".join(lines)


SIDE_WORDS = {"N": "north", "S": "south", "E": "east", "W": "west"}


def describe_focus(design: Design, focus: str) -> str:
    """What the user has selected in the viewer, in words the model can act on. `focus` is a spec
    element id (`L1-wall-hall-W`, `door-kitchen-hall`, `L1-space-hall`, …) or a design id."""
    fid = focus.strip()

    def room_name(rid: str) -> str:
        r = design.room(rid)
        return f'the {r.name} ({r.level})' if r else f"room {rid}"

    m = re.match(r"^(?P<level>[A-Za-z]\w*?)-wall-(?P<a>[\w-]+)\+(?P<b>[\w-]+)$", fid)
    if m:
        return f"the partition wall between {room_name(m['a'])} and {room_name(m['b'])} (wall id {fid})"
    m = re.match(r"^(?P<level>[A-Za-z]\w*?)-wall-(?P<room>[\w-]+)-(?P<side>[NSEW])$", fid)
    if m:
        return f"the {SIDE_WORDS[m['side']]} exterior wall of {room_name(m['room'])} (wall id {fid}; side={m['side']})"
    m = re.match(r"^(?P<level>[A-Za-z]\w*?)-space-(?P<room>[\w-]+)$", fid)
    if m and design.room(m["room"]):
        return f"the room {room_name(m['room'])} (room id {m['room']})"
    m = re.match(r"^(?P<level>[A-Za-z]\w*?)-(floor|slab)$", fid)
    if m:
        return f"the floor slab of level {m['level']}"
    if fid in ("roof",) or fid.endswith("-roof"):
        return "the roof"
    r = design.room(fid)
    if r:
        return f"the room {room_name(r.id)} (room id {r.id})"
    for d in design.doors:
        if d.id == fid:
            where = f"to outside on side {d.side}" if d.to == "outside" else f"to {room_name(d.to)}"
            return f"the door {fid} of {room_name(d.room)} {where}"
    for w in design.windows:
        if w.id == fid:
            return f"the window {fid} on the {SIDE_WORDS.get(w.side, w.side)} wall of {room_name(w.room)}"
    for st in design.stairs:
        if st.id == fid:
            return f"the stair {fid} in {room_name(st.room)}"
    for f in design.fixtures:
        if f.id == fid:
            return f"the {f.kind.replace('_', ' ')} {fid} in {room_name(f.room)}"
    for b in design.balconies:
        if b.id == fid:
            return f"the balcony {fid} of {room_name(b.room)}"
    if fid.startswith("porch"):
        return "the porch"
    for c in design.columns:
        if c.id == fid:
            return f"the column {fid} on {c.level}"
    return f"the element {fid}"


def describe_design(design: Design, derived: Derived | None = None) -> str:
    """The semantic model as the edit prompt sees it."""
    lines = [f'building "{design.name}"' + (f": {design.description}" if design.description else "")]
    lines.append("levels: " + "; ".join(f"{l.id} \"{l.display}\" height={l.height:g}" + (" below ground" if l.below_ground else "") for l in design.ordered_levels()))
    if design.wall_material:
        lines.append(f"exterior walls: {design.wall_material}")
    for level in design.levels:
        rooms = design.rooms_on(level.id)
        if not rooms:
            lines.append(f"rooms on {level.id}: none")
            continue
        lines.append(f"rooms on {level.id}:")
        for r in rooms:
            rect = f" rect={[round(v, 2) for v in r.rect]} ({r.area_m2:.0f} m2)" if r.rect else " (auto-placed)"
            extra = ""
            if derived and r.id in derived.rooms:
                info = derived.rooms[r.id]
                extra = f" exterior={','.join(info.sides) or '-'} adjacent={','.join(info.neighbours) or '-'}"
            lines.append(f"  room id={r.id} \"{r.name}\" kind={r.kind}{rect}{extra}")
    if design.doors:
        lines.append("doors: " + "; ".join(f"{d.id} {d.room}->{d.to}" + (f" side={d.side}" if d.side else "") + (f" {d.kind}" if d.kind != "single" else "") for d in design.doors))
    if design.windows:
        lines.append("windows: " + "; ".join(f"{w.id} {w.room} side={w.side}" + (f" at={w.at:g}" if w.at != 0.5 else "") + (f" {w.kind}" if w.kind != "standard" else "") for w in design.windows))
    if design.stairs:
        lines.append("stairs: " + "; ".join(f"{s.id} in {s.room} side={s.side} to={s.to_level or 'level above'}" for s in design.stairs))
    if design.fixtures:
        lines.append("furniture: " + "; ".join(f"{f.id} {f.kind} in {f.room}" + (f" side={f.side}" if f.side != "center" else "") for f in design.fixtures))
    if design.balconies:
        lines.append("balconies: " + "; ".join(f"{b.id} {b.room} side={b.side} depth={b.depth:g}" for b in design.balconies))
    if design.columns:
        lines.append("columns: " + "; ".join(f"{c.id} {c.level} ({c.x:g},{c.y:g})" for c in design.columns))
    if design.porch:
        lines.append(f"porch: side={design.porch.side} depth={design.porch.depth:g}")
    lines.append(f"roof: {design.roof.kind}" + (f" pitch={design.roof.pitch:g}" if design.roof.kind != "flat" else ""))
    if design.overrides:
        lines.append(f"raw element overrides: {len(design.overrides)}")
    return "\n".join(lines)
