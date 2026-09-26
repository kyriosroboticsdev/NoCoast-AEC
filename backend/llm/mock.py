"""Rule-based stand-in for a language model.

It answers the same two requests a real model gets — "program for this prompt" and
"edit ops for this prompt against this spec" — using regexes. It exists so the whole
pipeline (repair loop, ops, GlobalId stability, SSE, viewer) runs and is testable
with no model installed, and it is the fallback when the configured model is down.
"""

from __future__ import annotations

import json
import math
import re

from agents.template_planner import parse_program
from llm.base import LLMRequest, OnNote, OnText
from schemas.program import Program, Room

NUM = r"(\d+(?:\.\d+)?)"
STREAM_STEPS = 6  # the mock "streams" its answer in a few slices so the preview path gets exercised


class MockLLM:
    name = "mock"

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        prompt: str = request.meta.get("prompt", request.user)
        if request.schema_name == "program":
            reply = parse_program(prompt).model_dump(mode="json")
        elif request.schema_name == "edit":
            reply = self._edit(prompt, request.meta.get("spec") or {}, request.meta.get("program"))
        else:
            raise ValueError(f"mock has no answer for schema '{request.schema_name}'")
        if on_text:
            text = json.dumps(reply)
            for i in range(1, STREAM_STEPS + 1):
                on_text(text[: len(text) * i // STREAM_STEPS])
        return reply

    # --- edits -----------------------------------------------------------

    def _edit(self, prompt: str, spec: dict, program: dict | None) -> dict:
        text = prompt.lower().strip()
        ids = [e["id"] for e in spec.get("elements", [])]
        by_lower = {i.lower(): i for i in ids}  # the prompt is lowercased; ids are not
        levels = [l["id"] for l in spec.get("levels", [])]
        ops: list[dict] = []
        notes: list[str] = []

        m = re.search(r"\b(rename|call|name) (the )?(building|house|project) (to )?['\"]?([^'\"]+?)['\"]?$", text)
        if m:
            name = prompt.strip()[m.start(5):m.end(5)]
            return {"mode": "ops", "ops": [{"op": "set_building", "set": {"name": name}}], "notes": [f"renamed building to '{name}'"]}

        m = re.search(r"\b(remove|delete|drop)\b(.*)", text)
        if m:
            target = m.group(2)
            if "garage" in target:
                victims = [i for i in ids if i.startswith("garage") or i == "L1-space-garage"]
            elif "porch" in target:
                victims = [i for i in ids if i.startswith("porch")]
            elif re.search(r"\ball (the )?windows\b", target):
                victims = [e["id"] for e in spec["elements"] if e["type"] == "window"]
            else:
                victims = [i for i in ids if re.search(r"(?<![\w-])" + re.escape(i.lower()) + r"(?![\w-])", target)]
            if victims:
                ops = [{"op": "delete_element", "id": v} for v in victims]
                notes.append(f"deleted {len(victims)} element(s)")
                return {"mode": "ops", "ops": ops, "notes": notes}

        m = re.search(r"\b(storey|floor|ceiling|level)s? (height|heights)? ?(to|of|=)? ?" + NUM + r"\s*m", text)
        if m:
            h = float(m.group(4))
            ops = [{"op": "modify_level", "id": l, "set": {"height": h}} for l in levels]
            return {"mode": "ops", "ops": ops, "notes": [f"set every storey height to {h} m"]}

        m = re.search(r"\badd (a |an )?(window|door)\b.*?\b(to|on|in) (the )?([\w-]+)", text)
        if m and m.group(5) in by_lower:
            wall = next(e for e in spec["elements"] if e["id"] == by_lower[m.group(5)])
            if wall["type"] == "wall":
                length = math.dist(wall["start"], wall["end"])
                kind = m.group(2)
                width = 1.2 if kind == "window" else 0.9
                used = [(e["offset"], e["offset"] + e["width"]) for e in spec["elements"] if e["type"] in ("door", "window") and e["wall"] == wall["id"]]
                offset = 0.5
                while any(a - 0.1 < offset + width and offset < b + 0.1 for a, b in used) and offset + width < length:
                    offset += 0.25
                if offset + width <= length:
                    n = sum(1 for e in spec["elements"] if e["type"] == kind) + 1
                    el = {"type": kind, "id": f"{kind}-new-{n}", "wall": wall["id"], "offset": round(offset, 2), "width": width}
                    return {"mode": "ops", "ops": [{"op": "add_element", "element": el}], "notes": [f"added a {kind} to {wall['id']}"]}

        m = re.search(r"\b(widen|extend|lengthen|shorten|move|make) (the )?([\w-]+)\b.*?" + NUM + r"\s*m", text)
        if m and m.group(3) in by_lower:
            el = next(e for e in spec["elements"] if e["id"] == by_lower[m.group(3)])
            value = float(m.group(4))
            if el["type"] in ("door", "window"):
                return {"mode": "ops", "ops": [{"op": "modify_element", "id": el["id"], "set": {"width": value}}], "notes": [f"set {el['id']} width to {value} m"]}
            if el["type"] == "wall":
                return {"mode": "ops", "ops": [{"op": "modify_element", "id": el["id"], "set": {"thickness": value}}], "notes": [f"set {el['id']} thickness to {value} m"]}

        # Anything else is a change to the program: merge the prompt into the stored program and redesign.
        base = Program.model_validate(program) if program else parse_program("a house")
        delta = parse_program(prompt)
        rooms = list(base.rooms)
        storeys = base.storeys
        if re.search(r"\badd (a |an |another )?(storey|floor|level)\b", text):
            storeys += 1
            notes.append("added a storey")
        for room in delta.rooms:
            if room.name in {r.name for r in rooms}:
                if room.kind == "bedroom":
                    k = sum(1 for r in rooms if r.kind == "bedroom") + 1
                    room = Room(name=f"Bedroom {k}", level=room.level, kind="bedroom")
                else:
                    continue
            index = min(room.index, storeys - 1)
            if room.kind == "bedroom" and storeys > 1 and not re.search(r"ground|first floor|downstairs", text):
                index = storeys - 1
            rooms.append(Room(name=room.name, level=f"L{index + 1}", kind=room.kind, area=room.area))
            notes.append(f"added {room.name} on L{index + 1}")
        merged = base.model_copy(update={
            "storeys": storeys, "rooms": rooms, "notes": notes or ["redesigned from prompt"],
            "garage": base.garage or delta.garage, "porch": base.porch or delta.porch, "bright": base.bright or delta.bright,
            "footprint": delta.footprint or base.footprint,
        })
        return {"mode": "redesign", "program": merged.model_dump(mode="json"), "notes": merged.notes}
