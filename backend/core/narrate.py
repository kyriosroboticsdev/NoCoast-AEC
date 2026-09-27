"""Turn a build step into a line an architect would actually write, plus the numbers behind it.

The pipeline used to emit developer shorthand ("step 7: window win-kitchen-S: kitchen side S").
The same event now carries three things:

    message   "Standard window to the south elevation of the kitchen — 1.2 m wide, sill at 0.9 m"
    why       the model's own one-clause rationale, if it gave one (Step.why)
    facts     the quantities behind the move: areas, dimensions, storey, running gross floor area

The frontend renders these directly, so the trace reads like a design log rather than a debug log.
Everything here is pure formatting over a Design that has already been validated — it never raises:
a narration failure must not break a build.
"""

from __future__ import annotations

from typing import Any

from schemas.design import Design, RoomDef

SIDE_NAMES = {"N": "north", "S": "south", "E": "east", "W": "west", "center": "centre"}

# Which part of the job a step belongs to; the UI groups the trace under these.
PHASES: dict[str, str] = {
    "building": "brief", "note": "brief",
    "level": "massing",
    "room": "plan", "layout": "plan", "remove": "plan",
    "door": "circulation", "stair": "circulation",
    "window": "envelope", "balcony": "envelope", "porch": "envelope", "roof": "envelope", "material": "envelope",
    "column": "structure", "element": "structure",
    "furniture": "fitout", "custom": "fitout",
}
PHASE_TITLES = {
    "brief": "Setting out the brief",
    "massing": "Massing and storey stacking",
    "plan": "Planning the floor plates",
    "circulation": "Circulation and access",
    "envelope": "Envelope, openings and roof",
    "structure": "Structure and site works",
    "fitout": "Fit-out and equipment",
}


def phase_of(kind: str) -> str:
    return PHASES.get(kind, "plan")


def _f(value: Any, digits: int = 1) -> str:
    """A number the way a drawing would letter it: 3, 3.5, 30 — never 3.0 and never 3 for 30."""
    try:
        text = f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def side_name(side: Any) -> str:
    return SIDE_NAMES.get(str(side or "").upper(), SIDE_NAMES.get(str(side or ""), str(side or "")))


def level_name(design: Design | None, level_id: Any) -> str:
    lid = str(level_id or "L1").upper()
    level = design.level(lid) if design else None
    if level is not None and level.name:
        return level.name.lower()
    if lid.startswith("B"):
        n = lid[1:]
        return "the basement" if n in ("", "1") else f"basement level {n}"
    n = lid[1:]
    if n == "1":
        return "the ground floor"
    if n == "2":
        return "the first floor"
    return f"level {n}" if n else "the ground floor"


def _in_sentence(name: str) -> str:
    """"Living Room" → "living room", but "Landing L2" and "Bedroom 2" keep their designations."""
    return " ".join(w.lower() if w.isalpha() and not w.isupper() else w for w in name.split())


def room_name(design: Design | None, ref: Any) -> str:
    key = str(ref or "").strip()
    if not key:
        return "the room"
    if key.lower() in ("outside", "exterior", "out", "outdoors", "garden", "street"):
        return "outside"
    room = design.room(key) if design else None
    if room is not None:
        return f"the {_in_sentence(room.name)}"
    return "the " + key.replace("-", " ")


def _size(room: RoomDef | None) -> str:
    if room is None:
        return ""
    if room.rect is not None and room.poly is None:
        _, _, w, d = room.rect
        return f"{_f(w)} × {_f(d)} m, {_f(room.area_m2, 0)} m²"
    if room.poly is not None:
        return f"{len(room.poly)}-sided, {_f(room.area_m2, 0)} m²"
    if room.area:
        return f"~{_f(room.area, 0)} m² (to be placed)"
    return ""


def gross_area(design: Design) -> float:
    return round(sum(r.area_m2 for r in design.rooms if r.roofed), 1)


# --- facts ------------------------------------------------------------------

def step_facts(raw: dict, design: Design, elements: int | None = None) -> dict:
    """The quantities behind a step, for the UI to show without re-deriving anything."""
    kind = str(raw.get("step") or "")
    facts: dict[str, Any] = {"kind": kind, "phase": phase_of(kind)}
    level_id = raw.get("level")
    room = design.room(raw.get("room") or raw.get("id") or "") if (raw.get("room") or raw.get("id")) else None
    if room is None and raw.get("name"):
        room = design.room(str(raw["name"]))
    if room is not None:
        level_id = level_id or room.level
        facts["room"] = room.id
        facts["room_name"] = room.name
        facts["area"] = round(room.area_m2, 1)
        if room.rect is not None and room.poly is None:
            facts["width"], facts["depth"] = room.rect[2], room.rect[3]
    if level_id:
        facts["level"] = str(level_id)
        facts["level_name"] = level_name(design, level_id)
    if kind == "layout" and isinstance(raw.get("rooms"), list):
        names = [str(r.get("name")) for r in raw["rooms"] if isinstance(r, dict) and r.get("name")]
        plate = [design.room(n) for n in names]
        facts["rooms"] = names
        facts["plate_area"] = round(sum(r.area_m2 for r in plate if r is not None), 1)
    facts["gfa"] = gross_area(design)
    facts["storeys"] = design.storeys()
    facts["room_count"] = len(design.rooms)
    if elements is not None:
        facts["elements"] = elements
    if raw.get("why"):
        facts["why"] = str(raw["why"])
    return facts


# --- narration ---------------------------------------------------------------

def narrate_step(raw: dict, design: Design, fallback: str = "") -> str:
    """One professional sentence about a step that has just been applied to `design`."""
    try:
        return _narrate(raw, design) or fallback
    except Exception:  # noqa: BLE001 - narration is cosmetic and must never break a build
        return fallback


def _narrate(raw: dict, design: Design) -> str:  # noqa: PLR0911, PLR0912 - one branch per step kind, flat on purpose
    kind = str(raw.get("step") or "")
    name = str(raw.get("name") or "")

    if kind == "building":
        return f"Opening the project as “{name or design.name}”" + (f" — {raw['description']}" if raw.get("description") else "")

    if kind == "note":
        return str(raw.get("text") or "Note")

    if kind == "level":
        lid = str(raw.get("id") or raw.get("level") or "")
        level = design.level(lid.upper()) if lid else None
        height = level.height if level else raw.get("height")
        where = level_name(design, lid)
        if lid.upper().startswith("B"):
            return f"Sinking {where}, {_f(height)} m floor-to-floor"
        return f"Stacking {where}, {_f(height)} m floor-to-floor"

    if kind == "room":
        room = design.room(str(raw.get("id") or name or ""))
        size = _size(room)
        label = room.name if room else (name or "room")
        return f"{label} on {level_name(design, room.level if room else raw.get('level'))}" + (f" — {size}" if size else "")

    if kind == "layout":
        lid = str(raw.get("level") or "L1")
        rooms = [design.room(str(r.get("name"))) for r in (raw.get("rooms") or []) if isinstance(r, dict)]
        rooms = [r for r in rooms if r is not None]
        area = sum(r.area_m2 for r in rooms)
        names = ", ".join(_in_sentence(r.name) for r in rooms[:8]) + (", …" if len(rooms) > 8 else "")
        return (f"Floor plate for {level_name(design, lid)}: {len(rooms)} rooms, {_f(area, 0)} m²"
                + (f" — {names}" if names else ""))

    if kind == "door":
        to = str(raw.get("to") or "outside")
        leaf = str(raw.get("kind") or "single")
        leaf_text = {"single": "single leaf", "double": "double doors", "sliding": "sliding", "french": "french doors",
                     "garage": "garage door"}.get(leaf, leaf)
        if raw.get("wall"):
            return f"Gate through {raw['wall']} — {leaf_text}"
        if to in ("outside", "exterior"):
            where = f" on the {side_name(raw['side'])} elevation" if raw.get("side") else ""
            entry = "Vehicle entry" if leaf == "garage" else "Entrance"
            return f"{entry} into {room_name(design, raw.get('room'))}{where} — {leaf_text}"
        return f"Doorway linking {room_name(design, raw.get('room'))} and {room_name(design, to)} — {leaf_text}"

    if kind == "window":
        glazing = str(raw.get("kind") or "standard")
        label = {"standard": "Window", "large": "Picture window", "floor": "Floor-to-ceiling glazing",
                 "small": "High-level window"}.get(glazing, f"{glazing} window")
        where = f"the {side_name(raw['side'])} elevation of " if raw.get("side") else ""
        return f"{label} to {where}{room_name(design, raw.get('room'))}"

    if kind == "stair":
        room = design.room(str(raw.get("room") or ""))
        rise = None
        if room is not None:
            level = design.level(room.level)
            rise = level.height if level else None
        along = f" along the {side_name(raw['side'])} wall" if raw.get("side") else ""
        to = f" up to {level_name(design, raw['to_level'])}" if raw.get("to_level") else ""
        return (f"Straight flight in {room_name(design, raw.get('room'))}{along}"
                + (f", rising {_f(rise)} m" if rise else "") + to)

    if kind == "furniture":
        item = str(raw.get("kind") or "fitting").replace("_", " ")
        side = raw.get("side")
        where = (f" against the {side_name(side)} wall" if side and side != "center" else
                 " in the middle of the room" if side == "center" else "")
        return f"{item.capitalize()} in {room_name(design, raw.get('room'))}{where}"

    if kind == "custom":
        parts = len(raw.get("parts") or [])
        return f"Purpose-made {name.lower() or 'piece'} for {room_name(design, raw.get('room'))} ({parts} solids)"

    if kind == "balcony":
        where = f"the {side_name(raw['side'])} side of " if raw.get("side") else ""
        return f"Balcony off {where}{room_name(design, raw.get('room'))}, {_f(raw.get('depth') or 1.5)} m deep"

    if kind == "porch":
        return f"Covered porch along the {side_name(raw.get('side') or 'S')} side, {_f(raw.get('depth') or 2.4)} m deep"

    if kind == "roof":
        shape = str(raw.get("kind") or design.roof.kind)
        pitch = raw.get("pitch") or design.roof.pitch
        return f"{shape.capitalize()} roof" + (f" at {_f(pitch, 0)}°" if shape != "flat" else "")

    if kind == "material":
        return f"Exterior envelope in {raw.get('material') or raw.get('kind')}"

    if kind == "column":
        return f"Column at ({_f(raw.get('x'))}, {_f(raw.get('y'))}) on {level_name(design, raw.get('level'))}"

    if kind == "element":
        what = str(raw.get("kind") or "element")
        label = name or what
        raised = f", {_f(raw['elevation'])} m above the level" if raw.get("elevation") else ""
        return f"{label.capitalize()} ({what}) on {level_name(design, raw.get('level'))}{raised}"

    if kind == "remove":
        return f"Taking out {room_name(design, raw.get('id'))}"

    return ""


def narrate_draft(raw: dict, design: Design) -> str:
    """What the model appears to be writing right now, from a half-finished step object."""
    kind = str(raw.get("step") or "")
    if not kind:
        return ""
    room = raw.get("room") or raw.get("name") or raw.get("id")
    where = f" in {room_name(design, room)}" if room else ""
    verbs = {
        "building": "Naming the project",
        "level": "Adding a storey",
        "room": f"Drawing {room_name(design, room) if room else 'a room'}",
        "layout": f"Setting out the plan of {level_name(design, raw.get('level'))}",
        "door": f"Placing a door{where}",
        "window": f"Cutting a window{where}",
        "stair": f"Setting out a stair{where}",
        "furniture": f"Placing {str(raw.get('kind') or 'a fitting').replace('_', ' ')}{where}",
        "custom": f"Designing a bespoke piece{where}",
        "balcony": f"Cantilevering a balcony{where}",
        "porch": "Adding a porch",
        "roof": "Choosing the roof form",
        "material": "Choosing the envelope material",
        "column": "Placing a column",
        "element": f"Building {str(raw.get('name') or raw.get('kind') or 'a structure')}",
        "remove": f"Removing {room_name(design, raw.get('id'))}",
        "note": "Writing a note",
    }
    return verbs.get(kind, f"Working on a {kind} step")
