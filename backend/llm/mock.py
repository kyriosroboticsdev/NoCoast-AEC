"""Rule-based stand-in for a language model.

It answers the same requests a real model gets — a requirements checklist, build
steps for a prompt, edit steps against an existing design — using regexes and the
template planner's layout. It exists so the whole pipeline (streaming steps, repair
loop, checks, GlobalId stability, SSE, viewer) runs and is testable with no model
installed, and it is the fallback when the configured model is down.
"""

from __future__ import annotations

import json
import os
import re
import time

from agents import shapes
from agents.brick_words import mentioned_bricks
from agents.template_planner import brick_steps, parse_requirements, site_steps, template_steps
from core.derive import DesignError, analyze
from llm.base import LLMRequest, OnNote, OnText, OnThinking
from schemas.bim import FixtureKind
from schemas.design import Design, RoomDef, slug
from schemas.research import MAX_CALLS
from skills import skillbook
from solver.layout import place_rooms

NUM = r"(\d+(?:\.\d+)?)"
# The mock "streams" its answer in slices so the preview/draft path gets exercised. More slices means
# the UI updates more often; BIM_MOCK_DELAY paces them (seconds per slice) for demos and screenshots.
STREAM_STEPS = int(os.environ.get("BIM_MOCK_SLICES", 32))
STREAM_DELAY = float(os.environ.get("BIM_MOCK_DELAY", 0))


def _custom_parts(item: str) -> list[dict]:
    """A plausible shape for a furniture request that isn't in the fixed FixtureKind catalog —
    the mock's stand-in for a real model actually designing the piece with a `custom` step."""
    if "round" in item:  # a round top on four legs, ~1.1 m across, ~0.72 m tall (dining/coffee table height)
        legs = [(0.05, 0.05), (0.99, 0.05), (0.05, 0.99), (0.99, 0.99)]
        return [{"shape": "round", "x": 0.0, "y": 0.0, "z": 0.72, "w": 1.1, "h": 0.05}] + [
            {"shape": "box", "x": x, "y": y, "z": 0.0, "w": 0.06, "d": 0.06, "h": 0.72} for x, y in legs]
    return [{"shape": "box", "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0, "d": 0.6, "h": 0.75}]  # generic table-ish block


def approach_for(prompt: str, steps: list[dict]) -> str:
    """The mock's stand-in for the design strategy a real model writes before it starts drawing."""
    levels = [s for s in steps if s.get("step") == "level"]
    plates = [s for s in steps if s.get("step") == "layout"]
    rooms = [r for s in plates for r in (s.get("rooms") or [])]
    free = [s for s in steps if s.get("step") == "element"]
    if free and not rooms:
        return ("A structure rather than a building: piers carry paired girders, the deck spans between them and "
                "parapets edge both sides. Everything is set out from the centreline so the spans stay equal.")
    parts = []
    if levels:
        above = [l for l in levels if not str(l.get("id", "L1")).startswith("B")]
        below = len(levels) - len(above)
        parts.append(f"{len(above)} storey{'s' if len(above) != 1 else ''} on a compact rectangular footprint"
                     + (f" over {below} basement level{'s' if below != 1 else ''}" if below else ""))
    if rooms:
        parts.append(f"{len(rooms)} rooms packed edge to edge so every shared edge becomes a partition and the "
                     f"outline of each plate becomes its slab and roof")
    strategy = "; ".join(parts) if parts else "a single compact volume"
    circ = ("A central hall carries the stair and links every room, so no room is reached through another. "
            if any(r.get("kind") == "hall" for r in rooms) else "")
    light = ("Habitable rooms are given a window on the first exterior side they own, which puts most glazing on "
             "the south and east elevations. " if rooms else "")
    return f"The parti: {strategy}. {circ}{light}Service rooms and the garage take the sides that get the least sun."


PUBLIC = {"office", "meeting", "reception", "classroom", "retail", "cafe", "clinic", "lab", "workshop", "gym",
          "auditorium", "ward", "warehouse"}


def _why(steps: list[dict], kinds: tuple[str, ...], n: int = 2) -> list[str]:
    whys = [s["why"].strip() for s in steps if s.get("step") in kinds and isinstance(s.get("why"), str) and s["why"].strip()]
    return [w[0].upper() + w[1:] + ("" if w.endswith(".") else ".") for w in dict.fromkeys(whys)][:n]


def thinking_for(schema: str, prompt: str, reply: dict, meta: dict | None = None) -> str:
    """The mock's stand-in for a thinking model's summarised reasoning, so the offline planner narrates
    its design the way a real model does: brief, parti, zoning, circulation, envelope, code."""
    if schema == "requirements":
        reqs = [r["text"] for r in reply.get("requirements", [])]
        return ("**Reading the brief**\n\nI count " + str(len(reqs)) + " things the client asked for: "
                + "; ".join(reqs[:8]) + ". Each becomes a check the finished model is measured against.")
    if schema != "build":
        return ""
    steps = reply.get("steps", [])
    meta = meta or {}
    if meta.get("code"):
        clauses = [re.sub(r":.*", "", str(line)) for line in meta["code"]]
        moves = _why(steps, ("door", "stair", "furniture", "window"), 4)
        return ("**Clearing the code review before issue**\n\n"
                + f"{len(clauses)} clause{'s' if len(clauses) != 1 else ''} fail the screen: " + "; ".join(clauses) + ". "
                + "None of them needs the plan reorganised, so the fixes are local and leave the parti alone.\n\n"
                + "**The moves**\n\n" + (" ".join(moves) or "No local move clears them; they go on the issue sheet as open items."))
    problems = [re.sub(r"^step \d+ \{.*?\}: |applying this step makes the design unbuildable: ", "", str(p))
                for k in ("problems", "unmet", "issues", "seen", "code") for p in (meta.get(k) or [])]
    if problems or meta.get("editing"):
        head = ("**Reworking what did not land**\n\n" + " ".join(f"{p.rstrip('.')}." for p in problems[:3]) + " "
                if problems else "**Reading the change against the current design**\n\n")
        whys = _why(steps, ("room", "layout", "door", "window", "stair", "furniture", "element", "roof", "remove"), 3)
        return head + (" ".join(whys) or (f"{len(steps)} targeted move(s); the rest of the model stays as it is." if steps
                                          else "Nothing worth forcing: the model stands as built and the gap is reported."))
    plates = [s for s in steps if s.get("step") == "layout"]
    rooms = [r for p in plates for r in (p.get("rooms") or [])]
    area = sum(float(r["rect"][2]) * float(r["rect"][3]) for r in rooms if len(r.get("rect") or []) == 4)
    public = any(r.get("kind") in PUBLIC for r in rooms)
    zoning = []
    for p in plates:
        names = [r.get("name") or r.get("id") for r in p.get("rooms") or []]
        level = {"L1": "Ground floor", "L2": "First floor", "L3": "Second floor"}.get(str(p.get("level")), str(p.get("level")))
        zoning.append(f"{level}: {', '.join(names)}")
    paras = [
        "**Reading the site and brief**\n\n" + (f"About {area:.0f} m² of net floor area across {len(plates)} plate"
                                                 f"{'s' if len(plates) != 1 else ''}. " if area else "")
        + ("A non-domestic building, so it is designed to the IBC: occupancy by use, exits by occupant load, "
           "accessible route to every public room." if public else
           "A dwelling, so the IRC governs: habitable room sizes, stair geometry, daylight and escape openings."),
        "**Parti and massing**\n\n" + reply["approach"],
    ]
    if zoning:
        paras.append("**Zoning the plates**\n\n" + ". ".join(zoning) + ". Public and shared rooms sit at grade next to "
                     "the entrance; quiet and private rooms go upstairs or to the back.")
    for title, kinds in (("Circulation and egress", ("door", "stair")), ("Envelope and daylight", ("window", "roof"))):
        whys = _why(steps, kinds)
        if whys:
            paras.append(f"**{title}**\n\n" + " ".join(whys))
    paras.append("**Checking it against the code before drawing**\n\n" + (
        "IBC 1005.3.2 wants 5 mm of door width per occupant and 1006.3.3 a second exit above 49 occupants; "
        "Table 2902.1 sets the WC count and ADA 404.2.3 an 815 mm clear door into every public room. "
        if public else
        "IRC R311.7.5 caps the riser at 196 mm with a 254 mm minimum tread, R303.1 wants glazing of 8 % of each "
        "habitable floor and R310 an escape window in every bedroom. ")
        + "Designed to those numbers, the code screen after compile should come back without failures.")
    return "\n\n".join(paras)


class MockLLM:
    name = "mock"
    vision = True

    def complete(self, request: LLMRequest, on_text: OnText | None = None, on_note: OnNote | None = None,
                 on_thinking: OnThinking | None = None) -> dict:
        prompt: str = request.meta.get("prompt", request.user)
        if request.schema_name == "requirements":
            reply = {"summary": prompt[:80], "requirements": [r.model_dump(exclude_none=True) for r in parse_requirements(prompt)]}
        elif request.schema_name == "research":
            reply = self._research(prompt, request.meta)
        elif request.schema_name == "look":
            reply = self._look(request.meta)
        elif request.schema_name == "build":
            if any(request.meta.get(k) for k in ("problems", "unmet", "issues", "seen", "code")):
                reply = {"steps": self._fix(prompt, request.meta)}
            elif request.meta.get("editing"):
                reply = {"steps": self._edit(prompt, Design.model_validate(request.meta["design"]), request.meta.get("focus"))}
            else:
                reply = {"steps": template_steps(prompt)}
            reply = {"approach": approach_for(prompt, reply["steps"]), **reply}
        else:
            raise ValueError(f"mock has no answer for schema '{request.schema_name}'")
        thought = thinking_for(request.schema_name, prompt, reply, request.meta) if on_thinking else ""
        if thought:
            words = thought.split(" ")
            slices = max(1, STREAM_STEPS // 2)
            for i in range(1, slices + 1):
                on_thinking(" ".join(words[: len(words) * i // slices]))
                if STREAM_DELAY:
                    time.sleep(STREAM_DELAY)
        if on_text and request.schema_name == "build":
            text = json.dumps(reply)
            for i in range(1, STREAM_STEPS + 1):
                on_text(text[: len(text) * i // STREAM_STEPS])
                if STREAM_DELAY:
                    time.sleep(STREAM_DELAY)
        return reply

    # --- research --------------------------------------------------------------

    def _research(self, prompt: str, meta: dict) -> dict:
        """Read the matching skills, then the card of every brick the prompt names, then search for each —
        MAX_CALLS per turn, continuing where the previous turn stopped (one log entry per call)."""
        mentions = mentioned_bricks(prompt)
        text = prompt + " " + " ".join(meta.get("checklist") or [])
        calls = [{"tool": "get_skill", "id": s.name} for s in skillbook().match(text, limit=2)] if mentions else []
        calls += [{"tool": "get_brick", "id": m.brick} for m in mentions]
        calls += [{"tool": "search_bricks", "query": m.phrase} for m in mentions]
        todo = calls[len(meta.get("log") or []):]
        return {"calls": todo[:MAX_CALLS], "done": len(todo) <= MAX_CALLS}

    # --- look ----------------------------------------------------------------

    def _look(self, meta: dict) -> dict:
        """Take one closer look at the first placed brick, then call it done; the mock cannot judge an image."""
        bricks = [b["id"] for b in (meta.get("design") or {}).get("bricks", [])]
        if meta.get("turn", 1) == 1 and bricks:
            return {"views": [{"target": bricks[0], "azimuth": 200, "elevation": 35, "note": f"a closer look at {bricks[0]}"}]}
        return {"done": True}

    # --- fix rounds ----------------------------------------------------------

    def _fix(self, prompt: str, meta: dict) -> list[dict]:
        """The mock cannot reason about its mistakes, but coordination issues and failing code clauses come with
        steps that fix them: it applies those (once each) and leaves the rest for the pipeline to report."""
        steps, seen = [], set()
        suggested = [s for issue in meta.get("issues") or [] for s in issue.get("suggestions") or []]
        for s in suggested + list(meta.get("remedies") or []):
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

        mentions = mentioned_bricks(prompt)
        if mentions and re.search(r"\b(add|put|install|place|fit|give)\b", text):
            found = brick_steps(mentions, design)
            if found:
                return found

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
        if re.search(r"\badd (a |an )?(foot)?bridge\b", text):
            return shapes.bridge_steps(design)
        # Equipment and site objects: things that stand outside the rooms, on the site or on the roof.
        if re.search(r"solar|photovoltaic|\bpv\b|water tank|cistern|rainwater|cycle (rack|park|store)|bike rack|"
                     r"bicycle|trees?\b|landscap|planting|bench|forecourt|car ?park|parking (bays?|spaces?|lot)|"
                     r"loading (bay|dock)|\byard\b|hardstanding", text):
            site = site_steps(text, design)
            if site:
                return site
        if re.search(r"\badd (a |an |some )?(fence|railings?|parapets?|balustrades?|handrails?)\b", text):
            return shapes.fence_steps(design)
        if re.search(r"\badd (a |an |some )?(external|outside|entrance|front) (steps?|stairs?)\b", text):
            return shapes.external_steps(design)
        m = re.search(r"\badd (a |an )?(carport|courtyard|patio|terrace|pergola|gazebo|garden wall|deck)\b", text)
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
            if what == "garden wall":
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
