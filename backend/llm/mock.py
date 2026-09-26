"""Rule-based stand-in for a language model.

It answers the same requests a real model gets — a requirements checklist, build
steps for a prompt, edit steps against an existing design — using regexes and the
template planner's layout. It exists so the whole pipeline (streaming steps, repair
loop, checks, GlobalId stability, SSE, viewer) runs and is testable with no model
installed, and it is the fallback when the configured model is down.
"""

from __future__ import annotations

import json
import re

from agents.template_planner import parse_requirements, template_steps
from core.derive import DesignError, analyze
from llm.base import LLMRequest, OnNote, OnText
from schemas.design import Design, RoomDef, slug
from solver.layout import place_rooms

NUM = r"(\d+(?:\.\d+)?)"
STREAM_STEPS = 8  # the mock "streams" its answer in slices so the preview path gets exercised


class MockLLM:
    name = "mock"

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        prompt: str = request.meta.get("prompt", request.user)
        if request.schema_name == "requirements":
            reply = {"summary": prompt[:80], "requirements": [r.model_dump(exclude_none=True) for r in parse_requirements(prompt)]}
        elif request.schema_name == "build":
            if request.meta.get("problems") or request.meta.get("unmet"):
                reply = {"steps": self._fix(prompt, request.meta)}
            elif request.meta.get("editing"):
                reply = {"steps": self._edit(prompt, Design.model_validate(request.meta["design"]))}
            else:
                reply = {"steps": template_steps(prompt)}
        else:
            raise ValueError(f"mock has no answer for schema '{request.schema_name}'")
        if on_text:
            text = json.dumps(reply)
            for i in range(1, STREAM_STEPS + 1):
                on_text(text[: len(text) * i // STREAM_STEPS])
        return reply

    # --- fix rounds ----------------------------------------------------------

    def _fix(self, prompt: str, meta: dict) -> list[dict]:
        """The mock cannot reason about its mistakes; it adds nothing (the pipeline reports the rest)."""
        return []

    # --- edits -----------------------------------------------------------------

    def _edit(self, prompt: str, design: Design) -> list[dict]:
        text = prompt.lower().strip()
        steps: list[dict] = []

        m = re.search(r"\b(rename|call|name) (the )?(building|house|project) (to )?['\"]?([^'\"]+?)['\"]?$", text)
        if m:
            return [{"step": "building", "name": prompt.strip()[m.start(5):m.end(5)]}]

        m = re.search(r"\b(remove|delete|drop)\b (the )?(.*)", text)
        if m:
            target = m.group(3).strip()
            if re.search(r"\ball (the )?windows\b", target):
                return [{"step": "remove", "id": w.id} for w in design.windows]
            if "porch" in target and design.porch:
                return [{"step": "remove", "id": "porch"}]
            room = design.room(target) or design.room(target.split(" ")[0])
            if room:
                return [{"step": "remove", "id": room.id}]
            for attr in ("doors", "windows", "stairs", "fixtures", "balconies"):
                for item in getattr(design, attr):
                    if item.id in target:
                        return [{"step": "remove", "id": item.id}]

        m = re.search(r"\b(storey|floor|ceiling|level)s? (height|heights)? ?(to|of|=)? ?" + NUM + r"\s*m", text)
        if m:
            return [{"step": "level", "id": l.id, "height": float(m.group(4))} for l in design.levels]

        m = re.search(r"\b(gable|pitched|hip(ped)?|flat) roof", text)
        if m:
            return [{"step": "roof", "kind": {"pitched": "gable", "hipped": "hip"}.get(m.group(1), m.group(1))}]

        m = re.search(r"\badd (a |an )?(large |big )?(window|door)\b.*?\b(to|on|in) (the )?([\w -]+?)(?: on the (north|south|east|west)( side)?)?$", text)
        if m:
            room = design.room(m.group(6).strip())
            if room:
                derived = analyze(design)
                side = (m.group(7) or "")[:1].upper() or (derived.rooms[room.id].sides[0] if derived.rooms[room.id].sides else "S")
                if m.group(3) == "window":
                    return [{"step": "window", "room": room.id, "side": side, "kind": "large" if m.group(2) else "standard"}]
                return [{"step": "door", "room": room.id, "to": "outside", "side": side}]

        m = re.search(r"\badd (a |an |another )?(balcony|stair|staircase)\b.*?\b(to|in|on) (the )?([\w -]+)", text)
        if m:
            room = design.room(m.group(5).strip())
            if room:
                if m.group(2) == "balcony":
                    derived = analyze(design)
                    side = derived.rooms[room.id].sides[0] if derived.rooms[room.id].sides else "S"
                    return [{"step": "balcony", "room": room.id, "side": side}, {"step": "door", "room": room.id, "to": "outside", "side": side, "kind": "sliding"}]
                return [{"step": "stair", "room": room.id, "side": "W"}]

        m = re.search(r"\bput (a |an )?([\w ]+?) in (the )?([\w -]+)", text)
        if m and design.room(m.group(4).strip()):
            kind = m.group(2).strip().replace(" ", "_")
            return [{"step": "furniture", "room": design.room(m.group(4).strip()).id, "kind": kind, "side": "N"}]

        if re.search(r"\badd (a |an |another )?(storey|floor|level)\b", text):
            lid = f"L{len(design.levels) + 1}"
            steps.append({"step": "level", "id": lid})
            below = design.rooms_on(design.levels[-1].id)
            hall = next((r for r in below if r.kind == "hall"), None)
            new = [RoomDef(id=f"landing-{len(design.levels) + 1}", name=f"Landing {len(design.levels) + 1}", level=lid, kind="hall", rect=hall.rect if hall else None)]
            rects = place_rooms([r.rect for r in new if r.rect], [RoomDef(id="bedroom-new", name="Bedroom", level=lid, kind="bedroom", area=16)])
            for r in new:
                steps.append({"step": "room", "name": r.name, "level": lid, "kind": r.kind, "rect": list(r.rect) if r.rect else None})
            n = sum(1 for r in design.rooms if r.kind == "bedroom") + 1
            steps.append({"step": "room", "name": f"Bedroom {n}", "level": lid, "kind": "bedroom", "rect": list(rects["bedroom-new"])})
            steps.append({"step": "door", "room": f"bedroom-{n}", "to": new[0].id})
            if hall:
                steps.append({"step": "stair", "room": hall.id, "side": "W"})
            return steps

        # Anything else: add the rooms the prompt names, auto-placed on the top storey (bedrooms) or L1.
        from agents.template_planner import ROOM_WORDS, NUM as CNUM, _num
        top = design.levels[-1].id
        for pattern, name, kind in ROOM_WORDS:
            for hit in re.finditer(r"(?:\b" + CNUM + r"[\s-]+)?\b(?:" + pattern + r")\b", text):
                n = _num(hit.group(1)) if hit.group(1) else 1
                existing = sum(1 for r in design.rooms if r.kind == kind)
                level = top if kind in ("bedroom", "bathroom") and len(design.levels) > 1 else "L1"
                if re.search(r"ground|first floor|downstairs", text):
                    level = "L1"
                for i in range(n):
                    label = f"{name} {existing + i + 1}" if kind == "bedroom" or existing or n > 1 else name
                    steps.append({"step": "room", "name": label, "level": level, "kind": kind, "area": 16})
        if steps:  # doors from each new room to whatever it ends up next to
            probe = design.model_copy(deep=True)
            from schemas.steps import Step, apply_step
            for s in steps:
                probe, _ = apply_step(probe, Step.model_validate(s))
            try:
                derived = analyze(probe)
                for s in list(steps):
                    rid = slug(s["name"])
                    info = derived.rooms.get(rid)
                    if info and info.neighbours:
                        hall = next((n for n in info.neighbours if probe.room(n).kind == "hall"), info.neighbours[0])
                        steps.append({"step": "door", "room": rid, "to": hall})
                    if info and info.sides:
                        steps.append({"step": "window", "room": rid, "side": info.sides[0]})
            except DesignError:
                pass
        return steps
