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

from agents import shapes
from agents.template_planner import parse_requirements, template_steps
from core.derive import DesignError, analyze
from llm.base import LLMRequest, OnNote, OnText
from schemas.bim import FixtureKind
from schemas.design import Design, RoomDef, slug
from solver.layout import place_rooms

NUM = r"(\d+(?:\.\d+)?)"
STREAM_STEPS = 8  # the mock "streams" its answer in slices so the preview path gets exercised


def _custom_parts(item: str) -> list[dict]:
    """A plausible shape for a furniture request that isn't in the fixed FixtureKind catalog —
    the mock's stand-in for a real model actually designing the piece with a `custom` step."""
    if "round" in item:  # a round top on four legs, ~1.1 m across, ~0.72 m tall (dining/coffee table height)
        legs = [(0.05, 0.05), (0.99, 0.05), (0.05, 0.99), (0.99, 0.99)]
        return [{"shape": "round", "x": 0.0, "y": 0.0, "z": 0.72, "w": 1.1, "h": 0.05}] + [
            {"shape": "box", "x": x, "y": y, "z": 0.0, "w": 0.06, "d": 0.06, "h": 0.72} for x, y in legs]
    return [{"shape": "box", "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0, "d": 0.6, "h": 0.75}]  # generic table-ish block


class MockLLM:
    name = "mock"

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None) -> dict:
        prompt: str = request.meta.get("prompt", request.user)
        if request.schema_name == "requirements":
            reply = {"summary": prompt[:80], "requirements": [r.model_dump(exclude_none=True) for r in parse_requirements(prompt)]}
        elif request.schema_name == "build":
            if request.meta.get("problems") or request.meta.get("unmet") or request.meta.get("issues"):
                reply = {"steps": self._fix(prompt, request.meta)}
            elif request.meta.get("editing"):
                reply = {"steps": self._edit(prompt, Design.model_validate(request.meta["design"]), request.meta.get("focus"))}
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
        """The mock cannot reason about its mistakes, but coordination issues come with steps that fix them:
        it applies those (once each) and leaves the rest for the pipeline to report."""
        steps, seen = [], set()
        for issue in meta.get("issues") or []:
            for s in issue.get("suggestions") or []:
                key = json.dumps(s, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    steps.append(s)
        return steps

    # --- edits -----------------------------------------------------------------

    def _edit(self, prompt: str, design: Design, focus: str | None = None) -> list[dict]:
        text = prompt.lower().strip()
        steps: list[dict] = []

        # A viewer selection (see core.context.describe_focus) stands in for the place the prompt leaves out.
        if focus:
            room = side = item = None
            m = re.search(r"wall id (\S+?); side=([NSEW])", focus)
            if m:
                room, side = re.sub(r"^\w+-wall-", "", m.group(1)).rsplit("-", 1)[0], m.group(2)
            m = m or re.search(r"room id ([\w-]+)", focus)
            if m and room is None:
                room = m.group(1)
            m = re.search(r"\b(door|window|stair|balcony|[a-z_]+) ([\w-]+) (of|on|in) the", focus)
            if m and design.room(m.group(2)) is None:
                item = m.group(2)
            if room and re.match(r"^(add|put) (a |an |another )?(large |big )?(window|door)( here| there| to it| on it)?$", text):
                kind = "large" if re.search(r"large|big", text) else "standard"
                if "window" in text:
                    return [{"step": "window", "room": room, "side": side or "S", "kind": kind}]
                return [{"step": "door", "room": room, "to": "outside", "side": side or "S"}]
            if item and re.match(r"^(remove|delete|drop)( this| it| that| the selected \w+)?$", text):
                return [{"step": "remove", "id": item}]

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

        m = re.search(r"\bmake (the )?([\w -]+?) l-shaped", text)
        if m and design.room(m.group(2).strip()):
            room = design.room(m.group(2).strip())
            poly = shapes.l_shape(design, room)
            if poly:
                return [{"step": "room", "id": room.id, "poly": poly}]
        m = re.search(r"\b(curved|rounded|round|bow) (wall|window|side)\b.*?\b(to|on|in|for) (the )?([\w -]+?)(?: on the (north|south|east|west)( side)?)?$", text)
        if m and design.room(m.group(5).strip()):
            room = design.room(m.group(5).strip())
            poly = shapes.curved_side(design, room, (m.group(6) or "")[:1].upper() or None)
            if poly:
                return [{"step": "room", "id": room.id, "poly": poly}]
        m = re.search(r"\badd (a |an )?(carport|courtyard|patio|terrace|pergola|gazebo|garden wall|fence|deck)\b", text)
        if m:
            what = m.group(2)
            top = design.levels[-1].id
            if what == "carport":
                return [{"step": "room", "name": "Carport", "kind": "carport", "level": "L1", "rect": shapes.beside(design, "L1", 6, 6)}]
            if what in ("courtyard", "patio"):
                return [{"step": "room", "name": "Courtyard", "kind": "courtyard", "level": "L1", "rect": shapes.beside(design, "L1", 4, 4)}]
            if what == "terrace":
                return [{"step": "room", "name": "Terrace", "kind": "terrace", "level": top, "rect": shapes.beside(design, top, 4, 4)}]
            if what in ("pergola", "gazebo"):
                return shapes.pergola_steps(design)
            if what in ("garden wall", "fence"):
                return shapes.garden_wall_steps(design)
            return shapes.deck_steps(design)

        m = re.search(r"\bput (a |an )?([\w ]+?) in (the )?([\w -]+)", text)
        if m and design.room(m.group(4).strip()):
            room = design.room(m.group(4).strip())
            item = m.group(2).strip()
            kind = item.replace(" ", "_").replace("-", "_")
            if kind in FixtureKind.__args__:
                return [{"step": "furniture", "room": room.id, "kind": kind, "side": "N"}]
            # Not in the fixed catalog: compose it instead of failing outright.
            return [{"step": "custom", "room": room.id, "name": item.title(), "side": "center", "parts": _custom_parts(item)}]

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
